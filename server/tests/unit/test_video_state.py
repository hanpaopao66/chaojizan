"""视频稿件状态机(DEV-PROMPTS-40 §5.8):合法迁移放行、非法迁移抛错、角色不对拒绝。"""
from types import SimpleNamespace

import pytest

from app.services import video_state as vs
from app.state_machine import TransitionError

#: §5.8 图上的每一条箭头(加上文字要求的定时发布那一格),以及谁能走
LEGAL = [
    ("draft", "processing", "uploader"),       # 提交
    ("processing", "reviewing", "system"),     # 转码完成
    ("processing", "failed", "system"),        # 转码失败
    ("reviewing", "published", "admin"),       # 通过
    ("reviewing", "scheduled", "admin"),       # 通过,但设了定时发布
    ("scheduled", "published", "system"),      # 清扫任务到点推进
    ("reviewing", "rejected", "admin"),        # 驳回
    ("published", "removed", "admin"),         # 下架
    ("published", "deleted", "uploader"),      # UP 主删除
    ("rejected", "draft", "uploader"),         # 修改后重新提交
    ("failed", "draft", "uploader"),
    ("rejected", "published", "appeal"),       # 申诉改判(S6)
    ("removed", "published", "appeal"),
]

ILLEGAL = [
    ("draft", "published"),        # 不能跳过转码和审核
    ("draft", "reviewing"),        # 不能跳过转码
    ("processing", "published"),   # 不能跳过审核
    ("reviewing", "draft"),
    ("published", "reviewing"),    # 改已发布的稿件不改 status(改动走 pending_changes)
    ("published", "draft"),
    ("removed", "draft"),          # 下架了不能自己改了重来,只能申诉
    ("rejected", "reviewing"),     # 要先回草稿再提交
    ("deleted", "published"),      # 删除是终点
    ("deleted", "draft"),
    ("scheduled", "reviewing"),
    ("failed", "reviewing"),
]


@pytest.mark.parametrize("cur,target,role", LEGAL)
def test_legal_transitions(cur, target, role):
    v = SimpleNamespace(status=cur)
    vs.transition(v, target, role)
    assert v.status == target


@pytest.mark.parametrize("cur,target", ILLEGAL)
def test_illegal_transitions_raise(cur, target):
    v = SimpleNamespace(status=cur)
    with pytest.raises(TransitionError) as e:
        vs.transition(v, target, "admin")
    assert not e.value.forbidden and "不能从" in e.value.message
    assert v.status == cur, "非法迁移不能改掉状态"


@pytest.mark.parametrize("cur,target,wrong", [
    ("reviewing", "published", "uploader"),   # UP 主不能自己过审
    ("reviewing", "rejected", "uploader"),
    ("published", "removed", "uploader"),
    ("draft", "processing", "admin"),         # 提交是 UP 主的事
    ("processing", "reviewing", "uploader"),  # 转码完成只能由系统推进
    ("rejected", "published", "admin"),       # 改判驳回只能走申诉
    ("removed", "published", "admin"),
])
def test_wrong_role_is_forbidden(cur, target, wrong):
    v = SimpleNamespace(status=cur)
    with pytest.raises(TransitionError) as e:
        vs.transition(v, target, wrong)
    assert e.value.forbidden


def test_uploader_can_delete_from_any_non_terminal_state():
    for s in ("draft", "processing", "reviewing", "scheduled", "published", "rejected", "failed",
              "removed"):
        v = SimpleNamespace(status=s)
        vs.transition(v, "deleted", "uploader")
        assert v.status == "deleted"


def test_every_status_has_a_label():
    from app.models import VIDEO_STATUSES
    assert set(vs.STATUS_LABELS) == set(VIDEO_STATUSES)
    for (a, b) in vs.TRANSITIONS:
        assert a in VIDEO_STATUSES and b in VIDEO_STATUSES


def test_pending_changes_machine():
    """已发布稿件的改动:编辑 → 转码 / 审核 → 通过清空 / 驳回;线上版本的 status 一直不动。"""
    v = SimpleNamespace(status="published", pending_changes=None)
    vs.set_pending_state(v, "editing", "uploader", fields={"title": "新"})
    assert v.pending_changes == {"state": "editing", "fields": {"title": "新"}}
    vs.set_pending_state(v, "processing", "uploader")
    with pytest.raises(TransitionError):
        vs.set_pending_state(v, "editing", "uploader")   # 转码中不能再改
    vs.set_pending_state(v, "reviewing", "system")
    with pytest.raises(TransitionError) as e:
        vs.set_pending_state(v, None, "uploader")        # 审核中不能撤回,也不能自己「通过」
    assert e.value.forbidden
    vs.set_pending_state(v, "rejected", "admin", reject_code="V202")
    assert v.pending_changes["reject_code"] == "V202" and v.status == "published"
    vs.set_pending_state(v, "editing", "uploader")
    vs.set_pending_state(v, "reviewing", "uploader")
    vs.set_pending_state(v, None, "admin")
    assert v.pending_changes is None and v.status == "published"
    with pytest.raises(TransitionError):
        vs.set_pending_state(v, "reviewing", "uploader")  # 没有改动不能直接进审核
