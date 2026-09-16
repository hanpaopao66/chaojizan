"""音乐作品状态机(DEV-PROMPTS-41 §5.3)。

- 允许的迁移和文档里那张图逐条对上;图上没有的一律 TransitionError;
- 角色分得清:音乐人能提交 / 撤回 / 下架自己的,管理员能通过 / 驳回 / 下架 / 恢复,
  申诉改判是单独的角色(换人复核在 services/music.resolve_appeal 里判);
- transition() 是唯一写 status 的地方 —— 源码里搜得到的 `.status =` 只能在它里面。
"""
import inspect
import re

import pytest

from app.services import music_state as ms
from app.state_machine import TransitionError


class _R:
    def __init__(self, status: str):
        self.status = status


def test_the_whole_transition_table():
    """§5.3 那张图:每一条箭头一行,角色也要对。"""
    assert ms.TRANSITIONS == {
        ("draft", "reviewing"): {"artist"},
        ("reviewing", "draft"): {"artist"},
        ("reviewing", "published"): {"admin"},
        ("reviewing", "rejected"): {"admin"},
        ("rejected", "reviewing"): {"artist"},
        ("withdrawn", "reviewing"): {"artist"},
        ("published", "withdrawn"): {"artist"},
        ("published", "removed"): {"admin"},
        ("removed", "published"): {"admin", "appeal"},
        ("rejected", "published"): {"appeal"},
    }


def test_happy_path():
    r = _R("draft")
    ms.transition(r, "reviewing", "artist")
    assert r.status == "reviewing"
    ms.transition(r, "published", "admin")
    assert r.status == "published"
    ms.transition(r, "withdrawn", "artist")
    ms.transition(r, "reviewing", "artist")
    ms.transition(r, "rejected", "admin")
    ms.transition(r, "reviewing", "artist")   # 改完再交
    assert r.status == "reviewing"


def test_illegal_transitions_are_409_shaped():
    for cur, target in (("draft", "published"), ("published", "reviewing"),
                        ("withdrawn", "published"), ("rejected", "removed"),
                        ("removed", "withdrawn"), ("draft", "removed")):
        with pytest.raises(TransitionError) as e:
            ms.transition(_R(cur), target, "admin")
        assert not e.value.forbidden, f"{cur}->{target} 应该是 409(状态不允许)而不是 403"


def test_roles_are_not_interchangeable():
    """音乐人不能自己把作品改成已发布;管理员不能替音乐人提交。"""
    with pytest.raises(TransitionError) as e:
        ms.transition(_R("reviewing"), "published", "artist")
    assert e.value.forbidden, "角色不对是 403"
    with pytest.raises(TransitionError) as e:
        ms.transition(_R("draft"), "reviewing", "admin")
    assert e.value.forbidden
    # 申诉改判只有 appeal 这个角色能做(换人由 resolve_appeal 判)
    with pytest.raises(TransitionError):
        ms.transition(_R("rejected"), "published", "admin")
    ms.transition(_R("rejected"), "published", "appeal")


def test_editable_and_public_sets():
    assert ms.EDITABLE_STATUSES == ("draft", "rejected", "withdrawn")
    assert ms.SUBMITTABLE_STATUSES == ("draft", "rejected", "withdrawn")
    assert ms.PUBLIC_STATUSES == ("published",)
    assert ms.editable(_R("draft")) and not ms.editable(_R("published"))
    assert not ms.editable(_R("reviewing")), "审核中不能改,不然审的和发的不是一版"
    assert not ms.editable(_R("removed")), "被平台下架的要走申诉,不是改了重发"


def test_every_status_has_a_label():
    statuses = {s for pair in ms.TRANSITIONS for s in pair}
    assert statuses <= set(ms.STATUS_LABELS), statuses - set(ms.STATUS_LABELS)


def test_only_the_state_machine_writes_status():
    """业务代码里不许直接改 music_releases.status —— 只有 transition() 能写。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app"
    offenders = []
    files = [p for p in list(root.glob("services/music*.py")) + list(root.glob("routers/music*.py"))
             if p.name != "music_state.py"]   # 状态机自己当然写 status
    for path in files:
        # 三引号里的东西(文档字符串、内嵌 SQL)换成等量空行:行号不变,也不会误伤
        src = re.sub(r'"""(.*?)"""', lambda m: "\n" * m.group(0).count("\n"),
                     path.read_text(encoding="utf-8"), flags=re.S)
        for n, line in enumerate(src.splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"\b(r|rel|release)\.status\s*=(?!=)", code):
                offenders.append(f"{path.name}:{n}:{line.strip()}")
    assert not offenders, f"这些地方绕过了状态机:{offenders}"
    assert "release.status = target" in inspect.getsource(ms.transition)
