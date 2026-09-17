"""跨事件循环的连接池守卫。

## 守的是什么

e2e 脚本里常见这个形状:一个同步 helper 包着 `asyncio.run(...)`,被调好几次。
**每次 `asyncio.run` 都是一个新的事件循环**,而连接是绑在创建它的循环上的。
上一轮的循环关掉之后,下一轮从**模块级连接池**里拿到那条连接,就是

    RuntimeError: got Future attached to a different loop
    RuntimeError: Event loop is closed

数据库那半边大家都记得收(`await engine.dispose()`),**Redis 那半边容易漏** ——
`app/redis_client.py` 的 `pool` 是模块级的、整个进程一个。

## 为什么值得一道守卫

同一形状咬过三次:`e2e_upload_privacy`、`e2e_eta_dynamic`、`e2e_delivery_issue`
(2026-09-16)。而它**不是稳定复现的**:第一轮清扫碰不碰 Redis 取决于库里攒了多少
东西,所以表现成"单独跑绿、全量跑随机红",看着像被别的套件影响 ——
这种红最费排查时间。

## 判据是两条**都**要成立

1. 这个文件会跑**多个事件循环**(两处 `asyncio.run`,或者包着它的 helper 被调多次);
2. 它的 async 体**够得着 Redis**(顺着调用图走,不是看模块里有没有 redis 这个词)。

两条缺一条都不用加 —— 加一堆没用的 `disconnect` 只是噪音。这两条当初都写错过:
按「有 engine.dispose 没 pool.disconnect」这个**形状**挑出来的 11 个文件,
一个都不需要(它们的体是裸 SQL);而真的够得着 Redis 的 22 个里,
20 个只跑一个循环。交集就是上面那两个,都已经修好了。
"""
import ast
import pathlib

TESTS = pathlib.Path(__file__).resolve().parents[1]
APP = TESTS.parents[0] / "app"

#: 走到这些名字就算碰了 Redis
REDIS_NAMES = {"get_redis", "redis_client", "pool"}

#: **例外要写理由。** 空着 —— 现在一个都不需要
ALLOWED: dict[str, str] = {}


def _app_modules() -> dict[str, ast.Module]:
    mods = {}
    for p in APP.rglob("*.py"):
        name = "app." + str(p.relative_to(APP).with_suffix("")).replace("/", ".")
        name = name.removesuffix(".__init__")
        try:
            mods[name] = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError:
            pass
    return mods


MODS = _app_modules()


def _funcs(mod: str) -> dict:
    out: dict = {}
    for n in ast.walk(MODS[mod]):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(n.name, []).append(n)
    return out


def _imports(node, mod: str) -> dict:
    """名字 -> (来源模块, 原名)。含函数内的局部 import(这个项目里到处都是)。"""
    m: dict = {}
    for n in ast.walk(node):
        if isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                parts = mod.split(".")
                pkg = ".".join(parts[:len(parts) - n.level]) or "app"
                base = f"{pkg}.{base}" if base else pkg
            for a in n.names:
                m[a.asname or a.name] = (base, a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                m[a.asname or a.name.split(".")[0]] = (a.name, None)
    return m


def _reaches_redis(mod: str, fname: str, seen=None, depth=0) -> bool:
    """从 app 里的一个函数出发,顺着调用图看够不够得着 Redis。

    **宁可多报不可漏报**:解析不出来的调用就不往下走(可能漏),
    所以这道守卫配合上面那份 ALLOWED 用 —— 它拦的是最常见的那条路
    (helper → services.xxx → get_redis),不追求完备。
    """
    seen = seen if seen is not None else set()
    if (mod, fname) in seen or depth > 12 or mod not in MODS:
        return False
    seen.add((mod, fname))
    here = _funcs(mod)
    for fn in here.get(fname, []):
        scope = {**_imports(MODS[mod], mod), **_imports(fn, mod)}
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            base, attr = None, None
            if isinstance(f, ast.Name):
                attr = f.id
            elif isinstance(f, ast.Attribute):
                attr = f.attr
                base = f.value.id if isinstance(f.value, ast.Name) else None
            if attr in REDIS_NAMES or base in REDIS_NAMES:
                return True
            tgt = scope.get(base or attr)
            if tgt and tgt[0].startswith("app"):
                tmod, tname = tgt
                nxt = attr if (base or tname is None) else tname
                if _reaches_redis(tmod, nxt, seen, depth + 1):
                    return True
            if base is None and attr in here:
                if _reaches_redis(mod, attr, seen, depth + 1):
                    return True
    return False


def _run_hosts(tree) -> list:
    """每个 `asyncio.run(...)` 调用点 -> 包着它的函数名(None = 模块级)。"""
    out = []

    def walk(node, fname):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(ch, ch.name)
                continue
            if (isinstance(ch, ast.Call) and isinstance(ch.func, ast.Attribute)
                    and ch.func.attr == "run"
                    and isinstance(ch.func.value, ast.Name)
                    and ch.func.value.id == "asyncio"):
                out.append(fname)
            walk(ch, fname)

    walk(tree, None)
    return out


def _multi_loop(tree) -> bool:
    """会不会跑起多个事件循环。

    **只数文本里 `asyncio.run` 出现几次是不够的** —— 最危险的形状恰恰是
    只写了一次、包在 helper 里、helper 被调好几次(e2e_delivery_issue 就是这样,
    当初的扫描正因为这条过滤把它漏掉了)。
    """
    hosts = _run_hosts(tree)
    if len(hosts) >= 2:
        return True
    named = {h for h in hosts if h}
    for n in ast.walk(tree):
        if isinstance(n, (ast.For, ast.While, ast.AsyncFor, ast.ListComp, ast.SetComp,
                          ast.DictComp, ast.GeneratorExp)):
            for c in ast.walk(n):
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                        and c.func.id in named):
                    return True          # 循环里调,文本上只有一次
    for h in named:
        calls = sum(1 for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == h)
        if calls >= 2:
            return True
    return False


def _suspects() -> list:
    """两条都成立、又没收 Redis 池的文件。"""
    bad = []
    for p in sorted(TESTS.glob("*.py")):
        src = p.read_text(encoding="utf-8")
        if "asyncio.run(" not in src or "pool.disconnect" in src:
            continue
        tree = ast.parse(src, filename=str(p))
        if not _multi_loop(tree):
            continue
        imp = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app"):
                for a in n.names:
                    imp.setdefault(a.asname or a.name, (n.module, a.name))
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]:
            hit = False
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                    t = imp.get(n.func.id)
                    if t and _reaches_redis(*t):
                        hit = True
                        break
            if hit:
                bad.append(p.name)
                break
    return [b for b in bad if b not in ALLOWED]


def test_跑多个循环又碰_redis_的_e2e_必须收掉_redis_池():
    bad = _suspects()
    assert not bad, (
        "这些 e2e 会跑多个事件循环,而它们的 async 体够得着 Redis,"
        f"却只收了数据库引擎:{bad}\n"
        "在 finally 里补一行 `await pool.disconnect()`"
        "(from app.redis_client import pool)。\n"
        "不补的表现是「单独跑绿、全量跑随机红」——"
        "第一轮碰不碰 Redis 取决于库里攒了多少东西,最费排查时间。")


# ---------------- 守卫自己的自证 ----------------
#
# 这道守卫的两条判据当初都写错过,所以它自己也要被验一次:
# 判据写松了就永远绿,而永远绿的守卫比没有更糟 —— 它会让人以为查过了。

def test_判据认得出已知需要收池子的那个():
    """e2e_delivery_issue:helper 里一个 asyncio.run、被调多次、体里是 sweep_once。
    它现在已经补上了,所以要把「已修」那条过滤摘掉再看判据认不认。"""
    src = (TESTS / "e2e_delivery_issue.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert _multi_loop(tree), (
        "判据没认出它会跑多个循环 —— 它文本里只有一个 asyncio.run,"
        "包在 sweep() 里被调了两次")
    from app.services import auto_flow  # noqa: F401
    assert _reaches_redis("app.services.auto_flow", "sweep_once"), \
        "判据没认出 sweep_once 够得着 Redis"
    assert "pool.disconnect" in src, "它本来就该是修好的"


def test_只跑一个循环的不算():
    """e2e_eta_apology 整个测试就一个 `asyncio.run(main())`,
    虽然体里也走 sweep_once,但没有第二个循环,跨循环问题不存在。
    判据要是不认这一条,会拉一长串无关的文件进来。"""
    tree = ast.parse((TESTS / "e2e_eta_apology.py").read_text(encoding="utf-8"))
    assert not _multi_loop(tree), "只有一个事件循环的不该被算进来"


def test_纯_sql_的体不算():
    """按「有 engine.dispose 没 pool.disconnect」这个形状挑,会挑出一批
    体是裸 SQL 的文件(e2e_appeal、e2e_cancel_rules……)。它们够不着 Redis,
    加了也是白加。"""
    assert not _reaches_redis("app.services.audit", "run_audit"), \
        "run_audit 是纯 SQL 核对,不该判成碰 Redis"
    assert not _reaches_redis("app.routers.uploads", "_may_read_private"), \
        "_may_read_private 是权限判断,不该判成碰 Redis"
