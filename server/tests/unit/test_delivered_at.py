"""后台「按送达处理」的单:送达时刻裁决时就写,写的是骑手上报那条配送异常的时刻。

原来 admin.resolve_delivery_issue 的 mark_delivered 只改状态、不写 delivered_at,
要等 24 小时后自动完成才顺手写成那一刻 —— 法定要留存的送达时间晚一天左右,
骑手当天的里程、按送达日汇总的统计、订单群「送达 24 小时后归档」都跟着歪。
完成时间照旧:自动确认收货的 24 小时从那次裁决起算,不从上报起算。

这类退化不报错,按源码守;行为由 e2e_delivery_issue 核对库里的时刻。
"""
import ast
import inspect
import textwrap
from pathlib import Path

from app.routers import admin
from app.services import auto_flow

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _assigns(fn_src: str, target: str) -> list[str]:
    """源码里给 `target`(如 order.delivered_at)赋的值,按语法树找(注释里写着不算)。"""
    out = []
    for node in ast.walk(ast.parse(textwrap.dedent(fn_src))):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if ast.unparse(t) == target:
                    out.append(ast.unparse(node.value))
    return out


def test_按送达处理写的是骑手上报的时刻():
    src = inspect.getsource(admin.resolve_delivery_issue)
    assert _assigns(src, "order.delivered_at") == ["issue.created_at"], \
        "按送达处理要当场写送达时刻,而且是骑手上报异常的那一刻(不是裁决时刻、不是完成时刻)"


def test_先行赔付的单送达时间照实留空():
    """餐没送到:退款那一支不许写送达时刻(0138 那次定的)。"""
    tree = ast.parse(textwrap.dedent(inspect.getsource(admin.resolve_delivery_issue)))
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "refund" in ast.unparse(node.test):
            body = "\n".join(ast.unparse(x) for x in node.body)
            assert "delivered_at" not in body, "先行赔付那一支写了送达时刻"


def test_自动确认收货从裁决起算():
    """送达时刻挪到了上报那一刻,自动完成的 24 小时仍从裁决起算 —— 完成时间照原来的口径。"""
    src = inspect.getsource(auto_flow.sweep_once)
    assert "mark_delivered" in src and "resolved_at" in src, \
        "自动确认收货没按「按送达处理」的裁决时刻计时:裁决拖了一天的单裁完当场就会自动完成"
    assert "func.coalesce(decided, Order.delivered_at, Order.updated_at)" in src


def _revisions() -> dict[str, tuple[str, object]]:
    out = {}
    for p in sorted(VERSIONS.glob("*.py")):
        vals = {}
        for n in ast.parse(p.read_text(encoding="utf-8")).body:
            if (isinstance(n, ast.Assign) and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Name)
                    and n.targets[0].id in ("revision", "down_revision")):
                vals[n.targets[0].id] = ast.literal_eval(n.value)
        out[vals["revision"]] = (p.name, vals.get("down_revision"))
    return out


def test_迁移只有一个头():
    """两条迁移接同一个上家,alembic upgrade head(CI、生产的迁移容器都用它)直接失败。"""
    revs = _revisions()
    downs: set = set()
    for _, d in revs.values():
        downs |= set(d) if isinstance(d, (tuple, list)) else ({d} if d else set())
    heads = sorted(r for r in revs if r not in downs)
    assert len(heads) == 1, f"迁移有多个头:{heads}"


def test_0139只补空值_可以重跑():
    name, down = _revisions()["0139"]
    assert down == "0138", name
    src = (VERSIONS / name).read_text(encoding="utf-8")
    assert "o.delivered_at IS NULL" in src, "只许补空着的送达时刻,不改已有的值"
    assert "resolution = 'mark_delivered'" in src
    assert "SET delivered_at = src.reported_at" in src
