"""会话权限的唯一判定处(DEV-PROMPTS-40 §5.6,#344)。

接口和客户端都照这里:接口拒绝不该做的事,客户端据 `perms` 决定按钮出不出现 ——
两处用同一份真值表(单测 `tests/unit/test_chat_perms.py` 锁住),不会出现
「按钮点得到、点了报错」或者「按钮藏了、接口却放行」。
"""
from dataclasses import dataclass
from datetime import datetime, timezone

#: 管理员权限(owner 全有)
ADMIN_RIGHTS = ("change_info", "delete_messages", "ban_users", "invite_users",
                "pin_messages", "add_admins", "post_messages", "edit_messages", "anonymous")
#: 群成员默认权限可以细分的项
MEMBER_PERMS = ("send_messages", "send_media", "send_stickers", "send_polls",
                "embed_links", "invite_users", "pin_messages", "change_info")
DEFAULT_MEMBER_PERMS = {
    "send_messages": True, "send_media": True, "send_stickers": True, "send_polls": True,
    "embed_links": True, "invite_users": True, "pin_messages": False, "change_info": False,
}
#: 新管理员缺省拿到的权限(任免时可以改)
DEFAULT_ADMIN_RIGHTS = {
    "change_info": True, "delete_messages": True, "ban_users": True, "invite_users": True,
    "pin_messages": True, "add_admins": False, "post_messages": True, "edit_messages": True,
    "anonymous": False,
}
SLOW_MODES = (0, 10, 30, 60, 300, 900, 3600)
#: 表情回应可用集合(群管理员可以收窄)
REACTIONS = ("👍", "👎", "❤️", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "😢", "🎉",
             "🤩", "🙏", "👌", "😍", "💯", "🤣", "⚡", "🏆", "💔", "🤨", "😐", "😭",
             "👀", "🤝", "✍️", "🤗", "😎", "😘")
SETTINGS_DEFAULTS: dict = {
    "slow_mode": 0,
    "join_by_request": False,
    "default_perms": DEFAULT_MEMBER_PERMS,
    "reactions": "all",          # "all" / "none" / [表情...]
    "signatures": False,         # 频道:帖子显示发帖管理员
    "history_visible": True,     # 群:新成员能不能看到进群前的消息
    "protected": False,          # 禁止转发、保存
}
#: 群人数上限(D7)。2026-09-16 从 1000 提到 20 万,和 Telegram 超级群同一档。
#:
#: 这个数**不是一行常量的事**。1000 人时「每条消息把成员全查出来再逐个推」
#: 还撑得住,20 万就不行 —— 同一批把 chat_push.notify_message 改成分批扫了。
#: 规格 D7 原话就是「群放到 20 万:要换成大群那套分发」。
GROUP_MAX_MEMBERS = 200_000

#: 逐个成员写用户事件的上限。超过这个数就不写了,靠会话事件 + 会话列表过滤兜底
#: (见 chat_store.delete_chat 的注释)。20 万条 user_event 会让解散群这个请求直接超时,
#: 而那时候群已经标成删除了 —— 事务回滚的话就是「点了没反应」,再点一次还是超时。
BULK_MEMBER_EVENTS_MAX = 1000
#: 编辑窗口:发出后 48 小时内能改(频道管理员不限)
EDIT_WINDOW_HOURS = 48


def chat_settings(settings: dict | None) -> dict:
    out = dict(SETTINGS_DEFAULTS)
    out["default_perms"] = dict(DEFAULT_MEMBER_PERMS)
    for k, v in (settings or {}).items():
        if k == "default_perms" and isinstance(v, dict):
            for pk, pv in v.items():
                if pk in DEFAULT_MEMBER_PERMS:
                    out["default_perms"][pk] = bool(pv)
        elif k in out:
            out[k] = v
    return out


def _active_restriction(restrictions: dict | None, now: datetime) -> dict | None:
    r = restrictions or {}
    until = r.get("until")
    if until:
        try:
            t = datetime.fromisoformat(until)
        except (TypeError, ValueError):
            t = None
        if t is not None and t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t is not None and t <= now:
            return None           # 限制到期,自动解除
    return r if r.get("perms") is not None else None


@dataclass(frozen=True)
class Perms:
    """某人在某会话里此刻能做什么。`as_dict()` 原样给客户端。"""

    in_chat: bool
    is_owner: bool = False
    is_admin: bool = False
    send_messages: bool = False
    send_media: bool = False
    send_stickers: bool = False
    send_polls: bool = False
    embed_links: bool = False
    invite_users: bool = False
    pin_messages: bool = False
    change_info: bool = False
    delete_others: bool = False
    ban_users: bool = False
    add_admins: bool = False
    edit_others: bool = False
    anonymous: bool = False
    slow_mode_exempt: bool = False

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


NOBODY = Perms(in_chat=False)


def perms_for(chat_type: str, settings: dict | None, role: str | None,
              rights: dict | None = None, restrictions: dict | None = None,
              now: datetime | None = None) -> Perms:
    """纯函数:会话类型 + 会话设置 + 这个人的角色 / 权限 / 限制 → 能做什么。"""
    now = now or datetime.now(timezone.utc)
    if role not in ("owner", "admin", "member", "restricted"):
        return NOBODY
    s = chat_settings(settings)
    if chat_type in ("private", "saved"):
        # 私聊两个人对等;收藏夹只有自己。没有管理员这回事
        return Perms(in_chat=True, send_messages=True, send_media=True, send_stickers=True,
                     send_polls=chat_type == "saved", embed_links=True, pin_messages=True,
                     slow_mode_exempt=True)
    if role == "owner":
        return Perms(in_chat=True, is_owner=True, is_admin=True,
                     **{k: True for k in ("send_messages", "send_media", "send_stickers",
                                          "send_polls", "embed_links", "invite_users",
                                          "pin_messages", "change_info", "delete_others",
                                          "ban_users", "add_admins", "edit_others")},
                     anonymous=bool((rights or {}).get("anonymous")),
                     slow_mode_exempt=True)
    if role == "admin":
        r = {**{k: False for k in ADMIN_RIGHTS}, **{k: bool(v) for k, v in (rights or {}).items()
                                                    if k in ADMIN_RIGHTS}}
        can_post = r["post_messages"] if chat_type == "channel" else True
        return Perms(in_chat=True, is_admin=True, send_messages=can_post, send_media=can_post,
                     send_stickers=can_post, send_polls=can_post, embed_links=can_post,
                     invite_users=r["invite_users"], pin_messages=r["pin_messages"],
                     change_info=r["change_info"], delete_others=r["delete_messages"],
                     ban_users=r["ban_users"], add_admins=r["add_admins"],
                     edit_others=r["edit_messages"] and chat_type == "channel",
                     anonymous=r["anonymous"] and chat_type == "group", slow_mode_exempt=True)
    # 普通成员 / 被限制的成员
    if chat_type == "channel":
        # 订阅者只能看、回应;频道里没有「成员发言」
        return Perms(in_chat=True)
    base = dict(s["default_perms"])
    active = _active_restriction(restrictions, now)
    if active is not None:
        for k, v in (active.get("perms") or {}).items():
            if k in base and not v:
                base[k] = False
    elif role == "restricted":
        pass  # 限制已到期:按群的默认权限
    if not base["send_messages"]:
        base.update(send_media=False, send_stickers=False, send_polls=False, embed_links=False)
    return Perms(in_chat=True, **{k: bool(base[k]) for k in MEMBER_PERMS})


def can_edit_message(chat_type: str, perms: Perms, *, mine: bool, age_hours: float,
                     kind: str) -> bool:
    """能不能改这条消息:自己的文字 / 带说明的媒体,48 小时内;频道有 edit_messages 的管理员不限。"""
    if kind in ("service", "poll", "sticker", "dice", "call", "voice", "video_note",
                "location", "contact"):
        return False
    if chat_type == "channel" and (perms.edit_others or (mine and perms.is_admin)):
        return True
    return mine and age_hours <= EDIT_WINDOW_HOURS


def can_delete_for_all(chat_type: str, perms: Perms, *, mine: bool) -> bool:
    """「为双方 / 所有人删除」:私聊随时都行;群里自己的或者有 delete_messages;频道要管理员。"""
    if chat_type in ("private", "saved"):
        return True
    if chat_type == "channel":
        return perms.delete_others or (mine and perms.is_admin)
    return mine or perms.delete_others


def reaction_allowed(settings: dict | None, emoji: str) -> bool:
    rule = chat_settings(settings)["reactions"]
    if rule == "none":
        return False
    allowed = REACTIONS if rule == "all" else tuple(rule)
    return emoji in allowed
