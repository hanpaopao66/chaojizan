"""社交关系变化之后要通知的地方(拉黑、联系人)。

放在单独一个模块里,是为了让 routers/social.py 不直接依赖实时网关和聊天模块:
拉黑之后要做的事(给我的其他设备发用户事件、让正在进行的通话挂断……)
由各模块在这里接上,社交接口本身只管改关系。
"""


async def on_block_changed(user_id: int, other_id: int, blocked: bool) -> None:
    from .rt_events import emit_user_event_now  # 实时网关(#343)
    await emit_user_event_now(user_id, "block", {"user_id": other_id, "blocked": blocked})
