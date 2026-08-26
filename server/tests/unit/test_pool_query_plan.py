"""抢单池那条查询:`parent_order_no = ''` 必须渲染成**字面量**(#303)。

## 这组测试守什么

`orders.parent_order_no` 上有普通索引,而全库 99.8% 的单这一列是 `''`
(只有追加单才有值)。把 `''` 写成绑定参数时,PostgreSQL 的预备语句
**第 6 次执行**起会切「通用计划」—— 通用计划按 n_distinct 估选择度,
于是认定 `parent_order_no = $n` 很挑,一头扎进 `ix_orders_parent_order_no`,
把整张表当过滤条件扫一遍。

开发库 134728 单上实测同一条抢单池查询:

    前 5 次        0.32 ~ 0.61 ms   走 ix_orders_status
    第 6 次起      22   ~ 27   ms   走 ix_orders_parent_order_no,
                                    Rows Removed by Filter: 134427

骑手端前台**每 5 秒**打一次这个接口,连接上的预备语句一旦切过去就一直
是慢的,而且随订单表增长线性变差。接口实测 38.12ms → 8.66ms。

这个坑不会报错、不会告警,只是慢 —— 而且慢在一个"看起来最没问题"的
写法上(`Order.parent_order_no == ""` 谁看都觉得对)。所以这里把
**渲染结果**锁住:有人把 NOT_APPEND_ORDER 改回 `== ""`,这条就红。
"""
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import NOT_APPEND_ORDER, Order
from app.state_machine import GRABBABLE_STATUSES


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(),
                            compile_kwargs={"render_postcompile": True}))


def test_不是追加单这个条件渲染成字面量而不是绑定参数():
    sql = _sql(select(Order.id).where(NOT_APPEND_ORDER))
    assert "parent_order_no = ''" in sql, sql
    # 反面:一旦退回绑定参数,这里会出现 %(parent_order_no_1)s
    assert "parent_order_no_1" not in sql, sql


def test_抢单池整条查询里其余取值仍走绑定参数():
    """只有这一个 `''` 要字面量,别把整条 SQL 都拼成字面量。"""
    stmt = (select(Order.id)
            .where(Order.rider_id.is_(None),
                   Order.status.in_(GRABBABLE_STATUSES),
                   Order.pickup.is_(False),
                   Order.self_delivery.is_(False),
                   NOT_APPEND_ORDER)
            .order_by(Order.created_at).limit(200))
    sql = _sql(stmt)
    assert "parent_order_no = ''" in sql, sql
    assert "status IN (%(status_1_1)s, %(status_1_2)s)" in sql, sql
    import re
    assert re.search(r"LIMIT %\(param_\d+\)s", sql), sql


def test_按具体单号找追加单仍然走绑定参数():
    """`parent_order_no = <某个单号>` 是**挑的**,那条正该用索引、
    正该走绑定参数 —— 别顺手把它也改成字面量(那才是 SQL 注入面)。"""
    sql = _sql(select(Order.id).where(Order.parent_order_no == "SZ123"))
    assert "SZ123" not in sql, sql
    assert "parent_order_no_1" in sql, sql


def test_全仓不再有裸写的空串比较():
    """新代码要用 NOT_APPEND_ORDER,不能再直接写 `== ""`。"""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    hits = [str(p.relative_to(root)) for p in root.rglob("*.py")
            if 'parent_order_no == ""' in p.read_text(encoding="utf-8")]
    assert hits == [], f"这些文件还在裸写空串比较:{hits}"
