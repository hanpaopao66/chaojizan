"""订单变成「已完成」的地方都要写完成时刻 completed_at(法定记录:交易完成时间要留存)。

自取单核销(orders.pickup_verify)、后台先行赔付(admin.resolve_delivery_issue)原来都只改了状态、
没写 completed_at —— 不报错,只是那一单的完成时间永远是空的,顾客信用分只好拿下单时间顶
(customer_credit 里的 coalesce)。历史数据由迁移 0138 补。

这里扫一遍源码:直接写 `x.status = OrderStatus.COMPLETED` 的函数,同一个函数里也必须写
`x.completed_at = ...`。按变量写状态的两处(/transition、清扫自动完成)在 `== OrderStatus.COMPLETED`
的分支里写,行为由 e2e 验(e2e_pickup、e2e_delivery_issue 核对库里的时刻)。
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def _assigns(fn: ast.AST, attr: str, value=None) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and t.attr == attr:
                    if value is None or ast.unparse(node.value) == value:
                        return True
    return False


def _completing_functions() -> list[tuple[str, ast.AST]]:
    out = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    _assigns(fn, "status", "OrderStatus.COMPLETED"):
                out.append((f"{path.relative_to(APP)}:{fn.name}", fn))
    return out


def test_every_place_that_completes_an_order_writes_completed_at():
    found = _completing_functions()
    names = [n for n, _ in found]
    # 扫不到这两处说明扫描方式和代码对不上了(改名、换写法),不能让它空转着变绿
    assert "routers/orders.py:pickup_verify" in names and \
        "routers/admin.py:resolve_delivery_issue" in names, names
    missing = [n for n, fn in found if not _assigns(fn, "completed_at")]
    assert not missing, f"这些地方把订单改成已完成,却没写完成时刻 completed_at:{missing}"


def test_pickup_verify_writes_delivered_at_too():
    """自取单没有「送达」这一步,核销那一刻就是送达(和 /transition 完成自取单一样)。"""
    fn = dict(_completing_functions())["routers/orders.py:pickup_verify"]
    assert _assigns(fn, "delivered_at")
