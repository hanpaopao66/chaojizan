"""开发者规则页(#329、#334):`/rules/developer`,进规则留痕。

开发者不是交易三方之一,所以**不进** rules.AUDIENCES —— 那三端之间的对称性
(test_rules_symmetry)守的是「平台对用户、商家、骑手一视同仁」,开发者的规则形状不同。
但纪律一样:每个数字都从代码常量读,一个都不手写;规则变了自动记一版,
开发者要接受最新一版才能提交审核。

开发者协议和平台规则在法务定稿前一律标「草案」(#336)。
"""
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import miniapp_kv as kv
from .miniapp_package import MAX_FILE, MAX_FILES, MAX_ZIP
from .miniapp_platform import (APPEAL_WINDOW_DAYS, DOMAIN_CHANGES_PER_MONTH,
                               LAUNCH_PER_MINUTE, MAX_APPS, MAX_TESTERS, REASON_CODES,
                               REMOVED_DATA_RETENTION_DAYS, REPORT_REVIEW_THRESHOLD,
                               REPORTS_PER_DAY)
from .miniapp_publish import CHECKLIST, CHECKLIST_VERSION, UPLOADS_PER_HOUR

AUDIENCE = "developer"
LABEL = "开发者"


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:g} MB"


def developer_rules() -> dict:
    sections = [
        {
            "title": "状态",
            "items": [
                "**本规则与开发者协议是草案**,法务定稿前可能调整;每次调整都记在规则留痕里,"
                "并且要你重新接受后才能继续提交审核",
            ],
        },
        {
            "title": "费用与原则",
            "items": [
                "发布免费,没有年费、认证费、流量费",
                "**不卖位置**:目录没有竞价、没有付费推荐,排序规则公开(见下一节)",
                "本期不允许内购、广告、支付;小游戏只上免费单机",
                "你的应用拿到的是按应用隔离的 open_id,拿不到用户的手机号和平台账号 id",
            ],
        },
        {
            "title": "你的应用会怎么被看见",
            "items": [
                "精选位在前:人工挑选,每次变动的理由在透明中心公示",
                "其余按**首次上架时间**从新到旧 —— 发新版本不会往前挪,反复发版刷不上去",
                "搜索按名称精确命中 > 前缀 > 包含 > 一句话介绍或开发者名",
                "打开次数、评分、付费都不参与排序(代码里的纯函数,有守卫测试)",
            ],
        },
        {
            "title": "审核",
            "items": [
                "认证通过才能提交审核;未认证也可以建应用、传开发版、加体验者、用模拟器",
                f"审核按结构化清单逐项过(第 {CHECKLIST_VERSION} 版):"
                + ";".join(c["label"] for c in CHECKLIST),
                "结论只有通过或驳回;驳回必须写原因代码和给你看的说明",
                "不承诺具体时限,审核时长的中位数在透明中心照实公示",
                "上架后改名称、图标、描述、隐私政策,改动随下一个版本一起送审",
                *[f"　· {code}:{label}" for code, label in REASON_CODES.items()],
            ],
        },
        {
            "title": "数据",
            "items": [
                f"云存储按(应用, 用户)隔离:每个用户 ≤ {kv.MAX_KEYS} 个键、"
                f"合计 ≤ {_mb(kv.MAX_TOTAL_BYTES)},单个值 ≤ {kv.MAX_VALUE_BYTES // 1024} KB",
                "**你的服务端不能直读用户的云存储** —— 只有用户在你的应用里、经宿主才能读写",
                "用户可以随时查看、导出、清空自己在你的应用里的数据",
                f"应用被移除后,用户数据保留 {REMOVED_DATA_RETENTION_DAYS} 天供导出,然后清除",
                "每个应用都要有隐私政策和数据声明(收集什么、为什么);超出声明收集按 R302 处理",
            ],
        },
        {
            "title": "配额与限流",
            "items": [
                f"可创建的应用:个人 {MAX_APPS['individual']} 个、企业 {MAX_APPS['company']} 个",
                f"每个应用的体验者 {MAX_TESTERS} 人",
                f"上传版本:每个应用每小时 {UPLOADS_PER_HOUR} 次;包大小应用 ≤ {_mb(MAX_ZIP['app'])}、"
                f"小游戏 ≤ {_mb(MAX_ZIP['game'])},单文件 ≤ {_mb(MAX_FILE)},文件数 ≤ {MAX_FILES}",
                f"启动(换 initData):每个用户每分钟 {LAUNCH_PER_MINUTE} 次",
                f"云存储调用:每个(应用, 用户)每分钟 {kv.RATE_PER_MINUTE} 次",
                f"修改服务器域名:每个应用每月 {DOMAIN_CHANGES_PER_MONTH} 次,改完只对新启动生效",
                f"用户投诉:每人每天 {REPORTS_PER_DAY} 次;7 天内 {REPORT_REVIEW_THRESHOLD} 个不同的人"
                "投诉同一个应用,自动进入复审",
            ],
        },
        {
            "title": "处罚与申诉",
            "items": [
                "处罚分三种:暂停(整改后复审可恢复)、移除(终态)、紧急隔离(版本立即打不开)",
                "每个处罚都写原因代码和给你看的说明,记在你的审核记录里,并在透明中心公示"
                "(日期、应用名、原因类别、是否申诉及结果;不公开内部备注)",
                f"对任何不利结论可以在 {APPEAL_WINDOW_DAYS} 天内申诉一次,"
                "**系统强制换一名审核员复核**,原结论人不能处理你的申诉",
            ],
        },
    ]
    return {"audience": AUDIENCE, "audience_label": LABEL, "draft": True, "sections": sections}


async def current_revision(db: AsyncSession) -> int:
    """规则的最新版本号(读的时候顺手记一版,和三端规则页同一个做法)。"""
    from ..models import RuleRevision
    from .rules import record_if_changed

    await record_if_changed(AUDIENCE, developer_rules()["sections"], db)
    rev = await db.scalar(select(RuleRevision.revision).where(
        RuleRevision.audience == AUDIENCE).order_by(desc(RuleRevision.revision)).limit(1))
    return rev or 0
