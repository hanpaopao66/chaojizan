"""音乐作品的状态机(DEV-PROMPTS-41 §5.3)。照 app/state_machine.py 的写法:
(当前, 目标) → 允许的角色;表里没有的迁移一律抛 TransitionError,**不许在业务代码里直接改 status**。

```
draft ──提交(音乐人)──▶ reviewing ──通过(管理员)──▶ published ──下架(音乐人)──▶ withdrawn
  ▲                       │                              │                           │
  │                       └──驳回(管理员)──▶ rejected    └──下架(管理员,带原因)──▶ removed
  │                                            │                                     │
  └────────── 撤回提交(音乐人) ◀── reviewing   └──再提交(音乐人)──▶ reviewing      恢复 / 申诉改判(管理员)──▶ published
withdrawn ──再提交(音乐人)──▶ reviewing        rejected 申诉改判(管理员,换人)──▶ published
```

审核的单位是**作品**(M3),不是歌:一张专辑连里面的全部歌曲一起审,过审后歌曲不能改,
要改就下架重交。所以这里没有「歌曲的状态」—— 歌只有转码状态(pending / processing / ready / failed)。

申诉改判(§5.3)是唯一允许从 rejected / removed 直接回到 published 的路,角色是 `appeal`,
和视频、小程序同一个口径:**原审核人不能复核自己的决定**,每一步都写进 music_decisions。
"""
from ..state_machine import TransitionError

STATUS_LABELS = {
    "draft": "草稿",
    "reviewing": "审核中",
    "published": "已发布",
    "rejected": "未通过",
    "withdrawn": "已下架(音乐人自己)",
    "removed": "已下架(平台)",
}

#: artist = 音乐人;admin = 审核员;appeal = 申诉改判(另一名审核员);system = 清扫 / 注销
TRANSITIONS: dict[tuple[str, str], set[str]] = {
    ("draft", "reviewing"): {"artist"},
    ("reviewing", "draft"): {"artist"},          # 撤回提交
    ("reviewing", "published"): {"admin"},
    ("reviewing", "rejected"): {"admin"},
    ("rejected", "reviewing"): {"artist"},       # 改完再交
    ("withdrawn", "reviewing"): {"artist"},      # 下架过的再交
    ("published", "withdrawn"): {"artist"},      # 音乐人自己下架
    ("published", "removed"): {"admin"},         # 平台下架(带原因)
    ("removed", "published"): {"admin", "appeal"},   # 恢复 / 申诉改判
    ("rejected", "published"): {"appeal"},       # 申诉改判
}

#: 能改信息、增删歌曲、删除(软删)的状态(§5.3「只有 draft、rejected、withdrawn 能改」)
EDITABLE_STATUSES = ("draft", "rejected", "withdrawn")
#: 外人看得到的状态。别的一律 404(§3.3,不告诉你「有但看不了」)
PUBLIC_STATUSES = ("published",)
#: 能提交审核的状态
SUBMITTABLE_STATUSES = ("draft", "rejected", "withdrawn")


def assert_transition(current: str, target: str, role: str) -> None:
    allowed = TRANSITIONS.get((current, target))
    if allowed is None:
        raise TransitionError(
            f"作品不能从「{STATUS_LABELS.get(current, current)}」变为"
            f"「{STATUS_LABELS.get(target, target)}」")
    if role not in allowed:
        raise TransitionError("当前角色无权执行此操作", forbidden=True)


def transition(release, target: str, role: str) -> None:
    """校验并改状态。**唯一允许写 music_releases.status 的地方。**"""
    assert_transition(release.status, target, role)
    release.status = target


def editable(release) -> bool:
    return release.status in EDITABLE_STATUSES
