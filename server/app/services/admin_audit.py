"""管理员写操作留痕。

模型和「为什么需要」写在 `models.AdminActionLog` 的文档里。
这个文件只放写入口 —— 一个函数,别的地方不要自己 `db.add(AdminActionLog(...))`,
否则字段口径迟早各写各的。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AdminActionLog, User

#: `detail` 里绝对不许出现的键。留痕是给运营复盘的,
#: 不是第二份敏感数据副本 —— 身份证号、银行卡号在主表里已经是加密存的,
#: 抄进 JSONB 等于把加密绕过去了。
_FORBIDDEN = {
    "id_card", "id_card_no", "idcard", "bank_account", "bank_card",
    "card_no", "account_no", "password", "token", "api_key", "secret",
}


def _clean(detail: dict | None) -> dict:
    """挡掉敏感键。

    **是抛异常不是静默丢弃** —— 静默丢弃的话,写的人以为记下来了,
    查的人以为没发生过,两头都不知道中间掉了东西。
    """
    if not detail:
        return {}
    bad = sorted(k for k in detail if k.lower() in _FORBIDDEN)
    if bad:
        raise ValueError(
            f"管理员留痕的 detail 里不许放这些键:{bad}。"
            "留痕是给运营复盘的,不是第二份敏感数据副本。"
        )
    return dict(detail)


async def log_admin_action(
    db: AsyncSession,
    admin: User,
    action: str,
    *,
    target_type: str = "",
    target_id: str | int = "",
    detail: dict | None = None,
) -> None:
    """记一条管理员写操作。

    **只 add 不 commit** —— 留痕必须和业务改动在同一个事务里:
    业务回滚了留痕也得跟着回滚,不然会留下"批过但没生效"的假记录;
    反过来业务成功而留痕失败,那是这个函数的 bug,应该让整笔一起失败,
    而不是悄悄放过去。

    :param action: 点分标识,如 `merchant.approve`。用固定词表而不是自由文本,
        将来要按动作聚合(这个月批了多少家)。
    """
    db.add(AdminActionLog(
        admin_id=admin.id,
        admin_phone=admin.phone or "",
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        detail=_clean(detail),
    ))
