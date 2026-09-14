"""顾客信用分 —— 现在是 services/credit.py 里三种角色之一(2026-09-14 起商家、骑手也有)。

这个模块只为兼容还在 `from ..services import customer_credit` 的调用点留着:
`invalidate` 就是 credit.invalidate,打掉的是这个人**所有角色**的缓存(一个账号只有一个角色,
多删两个不存在的键不费事)。新代码直接用 services.credit —— 订单完成、判定改变时要连店主和
骑手一起打,用 credit.invalidate_order。
"""
from .credit import invalidate  # noqa: F401
