"""视频稿件状态机(DEV-PROMPTS-40 §5.8)。照 app/state_machine.py 的写法:
(当前, 目标) → 允许的角色;表里没有的迁移一律抛 TransitionError,**不许在业务代码里直接改 status**。

```
draft ──提交──▶ processing ──转码完成──▶ reviewing ──通过──▶ published ──下架──▶ removed
  ▲                │                          │                   │  └─UP 主设为私密─▶ (visibility=private)
  │                └─转码失败──▶ failed        └─驳回──▶ rejected   └─UP 主删除──▶ deleted(软删,30 天后清媒体)
  └──────────── rejected / failed 可以修改后重新提交 ─────────────┘
```

图里没画、但 §5.8 文字要求的两处:

- **scheduled**:「scheduled_at:审核通过后到点才变 published,由后台清扫任务推进」——
  过审了、时间没到的稿件既不是 reviewing(已经审完)也不是 published(还不能公开),单列一格;
- **UP 主删除**不只发生在 published:草稿、审核中、被驳回的稿件 UP 主也能删(S5,用户的数据用户说了算)。

申诉改判(S6)是唯一允许从 rejected / removed 直接回到 published 的路,角色是 `appeal`,
和小程序 I5 同一个口径:改判不走正常的状态迁移,每一步都写进 video_decisions。

已发布稿件的**改动**不动 status(线上那一版照常在线),改动自己的小状态机在 PENDING_TRANSITIONS。
"""
from ..state_machine import TransitionError

STATUS_LABELS = {
    "draft": "草稿",
    "processing": "转码中",
    "reviewing": "审核中",
    "scheduled": "已通过,等待定时发布",
    "published": "已发布",
    "rejected": "未通过",
    "failed": "转码失败",
    "removed": "已下架",
    "deleted": "已删除",
}

#: uploader = UP 主;system = 转码回调 / 清扫任务;admin = 审核员;appeal = 申诉改判(另一名审核员)
TRANSITIONS: dict[tuple[str, str], set[str]] = {
    ("draft", "processing"): {"uploader"},
    ("processing", "reviewing"): {"system"},
    ("processing", "failed"): {"system"},
    ("reviewing", "published"): {"admin"},
    ("reviewing", "scheduled"): {"admin"},
    ("scheduled", "published"): {"system"},
    ("reviewing", "rejected"): {"admin"},
    ("published", "removed"): {"admin"},
    ("scheduled", "removed"): {"admin"},
    # rejected / failed 可以修改后重新提交:先回到草稿,再走「提交」
    ("rejected", "draft"): {"uploader"},
    ("failed", "draft"): {"uploader"},
    # 申诉成立(S6)
    ("rejected", "published"): {"appeal"},
    ("rejected", "scheduled"): {"appeal"},
    ("removed", "published"): {"appeal"},
    # UP 主删除(软删,30 天后清媒体;注销账号时立即清)
    **{(s, "deleted"): {"uploader", "system"}
       for s in ("draft", "processing", "reviewing", "scheduled", "published", "rejected",
                 "failed", "removed")},
}

#: 已发布稿件的改动(pending_changes["state"])。None = 没有改动
PENDING_LABELS = {
    "editing": "改动未提交",
    "processing": "改动转码中",
    "reviewing": "改动审核中",
    "rejected": "改动未通过",
    "failed": "改动转码失败",
}
PENDING_TRANSITIONS: dict[tuple[str | None, str | None], set[str]] = {
    (None, "editing"): {"uploader"},
    ("editing", "processing"): {"uploader"},
    ("editing", "reviewing"): {"uploader"},   # 只改了文字、没有新分 P 要转码
    ("processing", "reviewing"): {"system"},
    ("processing", "failed"): {"system"},
    ("reviewing", None): {"admin", "appeal"},  # 通过:改动搬到线上,清空
    ("reviewing", "rejected"): {"admin"},
    ("rejected", None): {"appeal", "uploader"},   # 申诉改判 / UP 主放弃改动
    ("rejected", "editing"): {"uploader"},
    ("failed", "editing"): {"uploader"},
    ("editing", None): {"uploader"},          # 放弃改动
    ("processing", None): {"uploader"},
    ("failed", None): {"uploader"},
}


def assert_transition(current: str, target: str, role: str) -> None:
    allowed = TRANSITIONS.get((current, target))
    if allowed is None:
        raise TransitionError(
            f"稿件不能从「{STATUS_LABELS.get(current, current)}」变为"
            f"「{STATUS_LABELS.get(target, target)}」")
    if role not in allowed:
        raise TransitionError("当前角色无权执行此操作", forbidden=True)


def assert_pending_transition(current: str | None, target: str | None, role: str) -> None:
    allowed = PENDING_TRANSITIONS.get((current, target))
    if allowed is None:
        raise TransitionError(
            f"改动不能从「{PENDING_LABELS.get(current, '无改动') if current else '无改动'}」变为"
            f"「{PENDING_LABELS.get(target, '无改动') if target else '无改动'}」")
    if role not in allowed:
        raise TransitionError("当前角色无权执行此操作", forbidden=True)


def transition(video, target: str, role: str) -> None:
    """校验并改状态。唯一允许写 videos.status 的地方。"""
    assert_transition(video.status, target, role)
    video.status = target


def pending_state(video) -> str | None:
    return (video.pending_changes or {}).get("state")


def store_pending(video, pc: dict | None) -> None:
    """写 pending_changes。JSONB 列没有变更跟踪:原地改了字典 SQLAlchemy 看不出来,
    所以一律整个换掉并显式标脏 —— 否则「改动」会在提交时悄悄丢掉。"""
    from sqlalchemy.orm.attributes import flag_modified

    video.pending_changes = pc
    if hasattr(video, "_sa_instance_state"):   # 单测里的替身不是 ORM 对象,没有变更跟踪要标
        flag_modified(video, "pending_changes")


def set_pending_state(video, target: str | None, role: str, **extra) -> None:
    """改动的状态迁移。target=None 表示清掉改动(通过后搬到线上,或放弃)。"""
    cur = pending_state(video)
    assert_pending_transition(cur, target, role)
    if target is None:
        store_pending(video, None)
        return
    pc = dict(video.pending_changes or {})
    pc["state"] = target
    pc.update(extra)
    store_pending(video, pc)


#: 线上有一版的状态(已发布、等定时发布)。这些稿件再改,改动进 pending_changes
LIVE_STATUSES = ("published", "scheduled")
#: UP 主可以直接改内容的状态(还没有线上版本)
EDITABLE_STATUSES = ("draft", "rejected", "failed")
