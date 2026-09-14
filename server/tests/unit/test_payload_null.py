"""手写 dict 请求体里的 null 当成「没传」,不能变成字面的 "None" 存进库。

`str(payload.get("k", ""))` 挡不住 null:键在、值是 None 时 get 的缺省值不起作用,
str(None) 就是 "None"。后台记违规时 `"order_no": null` 就这样存成了订单号 "None"
—— 违规记录挂在一个不存在的单上,同一类再记一条不挂单的还会撞上 (kind, order_no) 那条
只放过 NULL 的唯一索引,回「这一单的这类问题已经判定过了」。

路由里一律写成 `str(payload.get("k") or "")`(null、不传一样走缺省值);这里扫源码拦新写进来的。
"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

APP = Path(__file__).resolve().parents[2] / "app"


def _str_of_get(path: Path, root: Path = APP) -> list[str]:
    """文件里 `str(X.get("常量键"...))` 这种写法(get 的结果直接进 str,中间没有 or)。"""
    hits = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str"
                and len(node.args) == 1 and isinstance(node.args[0], ast.Call)
                and isinstance(node.args[0].func, ast.Attribute) and node.args[0].func.attr == "get"
                and node.args[0].args and isinstance(node.args[0].args[0], ast.Constant)):
            hits.append(f"{path.relative_to(root)}:{node.lineno}")
    return hits


def test_request_bodies_never_str_a_raw_get():
    files = sorted((APP / "routers").glob("*.py")) + sorted(APP.glob("schemas*.py"))
    assert len(files) > 40, "扫描范围不对"
    hits = [h for f in files for h in _str_of_get(f)]
    assert not hits, ("这些地方 str(payload.get(键, 缺省)) 遇到 null 会得到字面的 \"None\","
                      f"改成 str(payload.get(键) or 缺省):{hits}")


def test_the_scan_catches_the_old_shape(tmp_path):
    """扫描本身得认得出老写法(扫描器坏了会一直绿)。"""
    p = tmp_path / "x.py"
    p.write_text('a = str(payload.get("order_no", "")).strip() or None\n'
                 'b = str(payload.get("order_no") or "").strip() or None\n', encoding="utf-8")
    assert _str_of_get(p, tmp_path) == ["x.py:1"]


def test_violation_order_no_null_empty_blank_all_stored_as_null(monkeypatch):
    """后台记违规:订单号传 null、空串、空白都存 NULL;真单号原样存。"""
    from app.models import UserRole
    from app.routers import admin as ra
    from app.services import customer_credit, enforcement

    added = []

    class _DB:
        async def get(self, model, key, **kw):
            return SimpleNamespace(id=key, role=UserRole.customer)

        def add(self, obj):
            added.append(obj)

        async def commit(self):
            pass

        async def rollback(self):
            pass

        async def refresh(self, obj):
            pass

    async def _nothing(*a, **kw):
        return ""

    monkeypatch.setattr(customer_credit, "invalidate", _nothing)
    monkeypatch.setattr(enforcement, "level_for", _nothing)
    kind = next(r.kind for r in enforcement.CATALOG if r.audience == "customer")
    for raw in (None, "", "   ", " E2E0001 "):
        body = {"kind": kind, "subject_id": 7, "note": "测试", "order_no": raw}
        asyncio.run(ra.record_violation(body, admin=SimpleNamespace(id=1), db=_DB()))
    body = {"kind": kind, "subject_id": 7, "note": "测试"}   # 不传这个键
    asyncio.run(ra.record_violation(body, admin=SimpleNamespace(id=1), db=_DB()))
    assert [v.order_no for v in added] == [None, None, None, "E2E0001", None]
