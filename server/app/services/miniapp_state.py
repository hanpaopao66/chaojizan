"""小程序开放平台的四个状态机(#320,DEV-PROMPTS-39 §5.8)。

照订单状态机(state_machine.py)的写法:**所有状态变更必须经过 assert_transition**,
业务代码里不直接改 status。非法迁移抛 TransitionError,路由层转成 409。

- 开发者:unverified → pending → verified | rejected;rejected → pending(重新提交);
  verified ⇄ suspended;任意 → closed;
- 应用:draft →(首个版本发布)online ⇄ offline(开发者自己下架/上架);
  online/offline → suspended(平台处罚)→ online(整改后复审通过)或 removed(终态);
- 版本:uploaded →(可选)trial → reviewing → approved | rejected;reviewing → withdrawn;
  trial → uploaded(换了别的版本当体验版);
  approved → released;发布新版后旧的 released → superseded;回滚把一个 superseded
  重新变成 released(当前那个变 superseded);
- 能力申请:requested → approved | rejected;approved → revoked;rejected → requested(重新申请)。
"""
from ..state_machine import TransitionError

DEVELOPER = {
    "unverified": {"pending", "verified", "closed"},
    "pending": {"verified", "rejected", "closed"},
    "rejected": {"pending", "closed"},
    "verified": {"suspended", "closed"},
    "suspended": {"verified", "closed"},
    "closed": set(),
}

APP = {
    "draft": {"online", "removed"},
    "online": {"offline", "suspended", "removed"},
    "offline": {"online", "suspended", "removed"},
    "suspended": {"online", "removed"},
    "removed": set(),
}

VERSION = {
    "uploaded": {"trial", "reviewing"},
    # 换了另一个版本当体验版,原来那个退回「已上传」
    "trial": {"reviewing", "uploaded"},
    "reviewing": {"approved", "rejected", "withdrawn"},
    "withdrawn": {"reviewing", "trial"},
    "rejected": set(),
    "approved": {"released"},
    "released": {"superseded"},
    "superseded": {"released"},
}

CAPABILITY = {
    "requested": {"approved", "rejected"},
    "approved": {"revoked"},
    "rejected": {"requested"},
    "revoked": {"requested"},
}

_MACHINES = {"developer": DEVELOPER, "app": APP, "version": VERSION, "capability": CAPABILITY}

LABELS = {
    "unverified": "未认证", "pending": "审核中", "verified": "已认证", "rejected": "未通过",
    "suspended": "已暂停", "closed": "已注销",
    "draft": "草稿", "online": "在线", "offline": "已下架", "removed": "已移除",
    "uploaded": "已上传", "trial": "体验版", "reviewing": "审核中", "withdrawn": "已撤回",
    "approved": "审核通过", "released": "当前版本", "superseded": "历史版本",
    "requested": "申请中", "revoked": "已收回",
}

# 版本能不能从托管出口出去(隔离的另说,见 quarantined)
SERVABLE_VERSION_STATES = {"uploaded", "trial", "reviewing", "withdrawn", "approved",
                           "released", "superseded"}


def assert_transition(machine: str, current: str, target: str) -> None:
    allowed = _MACHINES[machine].get(current)
    if allowed is None or target not in allowed:
        raise TransitionError(
            f"不能从「{LABELS.get(current, current)}」变为「{LABELS.get(target, target)}」")
