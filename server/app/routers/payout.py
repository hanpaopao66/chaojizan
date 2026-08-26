"""收款账户:骑手/商家提现的打款目标。

账号密文落库(services/crypto.py),普通接口永远只回尾 4 位;
完整账号只在管理端打款界面解密展示。
提现申请时快照冻结——改账户不影响在途申请;
账户刚变更(24 小时内)发起的提现,管理后台标黄提示人工电话核实(只提示不拦截)。
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from ..db import get_db
from ..models import PayoutAccount, RiderProfile, User, VerifyStatus
from ..schemas import PayoutAccountIn, PayoutAccountOut
from ..security import require_role
from ..services.crypto import encrypt

router = APIRouter(prefix="/payout-account", tags=["收款账户"])

RECENT_WINDOW = timedelta(hours=24)

#: 比对户名前要抹掉的字符:各种空白 + 各种间隔号。
#:
#: 间隔号那几个码位是必须的 —— 少数民族姓名里的「·」,身份证上、
#: 银行系统里、手机输入法里常常是**不同的字符**(U+00B7 / U+2027 /
#: U+30FB / U+FF65 …)。不统一的话「买买提·艾力」和「买买提·艾力」
#: 会被判成两个人,而这恰恰是最不该被卡住的一批人。
_NAME_NOISE = dict.fromkeys(
    map(ord, " \t\u3000\u00a0\u00b7\u2027\u2022\u30fb\uff65"), None)


def normalize_holder_name(name: str) -> str:
    """户名比对用的归一化:抹掉空白与间隔号,不做别的。

    **不做同音字、简繁转换之类的模糊匹配** —— 那会把"不是同一个人"
    也判成同一个人,而这条检查存在的全部意义就是识别不是同一个人。
    """
    return (name or "").translate(_NAME_NOISE)


async def rider_real_name(db: AsyncSession, user: User) -> str:
    """骑手过审实名的姓名;未实名或非骑手返回空串。"""
    if user.role.value != "rider":
        return ""
    profile = await db.scalar(
        select(RiderProfile).where(RiderProfile.rider_id == user.id))
    if profile is None or profile.status != VerifyStatus.approved:
        return ""
    return (profile.real_name or "").strip()


async def ensure_holder_matches_identity(
    db: AsyncSession, user: User, holder_name: str,
) -> None:
    """收款户名必须与实名一致,不一致抛 422。

    ## 为什么要卡这一条

    二要素核验只证明「这个姓名+证号真实且匹配」,**不证明拿手机的人
    就是他**(见 riders.py 实名接口的注释)。众包没有站长天天见人,
    账号出租、顶替跑单是这个模式下唯一真正被抬高的风险。

    而「实名张三、提现打给李四」是这件事最硬的信号 —— 它在**资金侧**,
    比轨迹、比设备指纹都难伪造:租号的人图的就是把钱收走。
    查它不需要人脸,和「不做人脸认证」的立场不冲突。

    顺带也是收入归属问题:钱打给谁,和这笔钱算谁的收入,应当是同一个人。

    ## 只管骑手

    商家侧是另一套:主体名称在 `Merchant.license_subject`(企业或个体户
    全称),而且对公账户的户名本来就该是企业全称、不是自然人。
    规则不同,不能共用这一条,混着做会把对公账户全判成不一致。

    ## 没实名的不卡

    还没过实名的骑手允许先登记账户 —— 他也没有余额可提(接单要先实名)。
    真正的闸门在提现那一步,那里会再查一次。
    """
    expected = await rider_real_name(db, user)
    if not expected:
        return
    if normalize_holder_name(holder_name) != normalize_holder_name(expected):
        raise HTTPException(
            422,
            f"收款户名必须与实名一致。你的实名是「{expected}」,"
            f"请填本人的收款账户 —— 钱打给谁、这笔收入算谁的,得是同一个人。"
            f"确有困难请联系客服说明。")


def account_out(account: PayoutAccount | None) -> PayoutAccountOut:
    if account is None:
        return PayoutAccountOut(configured=False)
    return PayoutAccountOut(
        configured=True,
        kind=account.kind,
        holder_name=account.holder_name,
        bank_name=account.bank_name,
        account_tail=account.account_tail,
        updated_at=account.updated_at,
        recently_changed=account_recently_changed(account),
    )


def account_recently_changed(account: PayoutAccount) -> bool:
    updated = account.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated < RECENT_WINDOW


@router.get("", response_model=PayoutAccountOut)
async def my_payout_account(
    user: User = Depends(require_role("rider", "merchant")),
    db: AsyncSession = Depends(get_db),
):
    account = await db.scalar(
        select(PayoutAccount).where(PayoutAccount.user_id == user.id))
    return account_out(account)


@router.put("", response_model=PayoutAccountOut)
async def save_payout_account(
    payload: PayoutAccountIn,
    user: User = Depends(require_role("rider", "merchant")),
    db: AsyncSession = Depends(get_db),
):
    """登记/更换收款账户(一人一户,更换即覆盖)。

    换账户后 24 小时内的提现会被人工加核——防止账号被盗后改卡跑款。

    骑手的户名必须与实名一致,见 [ensure_holder_matches_identity]。
    """
    await ensure_holder_matches_identity(db, user, payload.holder_name)
    # 比对通过之后**存实名的写法,不存他输入的写法**。
    #
    # 比对是抹掉空白和间隔号做的,所以「 王 小　王 」也算通过 —— 但那个
    # 字符串会一路进提现快照、进管理端打款界面,而银行那边不认带空格的
    # 户名。既然已经确认是同一个人,就存证件上的那一份,省掉一类
    # "审核过了却打不出去"的失败。没有实名可依的(商家、未实名骑手)
    # 照旧存输入值。
    verified = await rider_real_name(db, user)
    holder = verified or payload.holder_name.strip()
    account = await db.scalar(
        select(PayoutAccount).where(PayoutAccount.user_id == user.id))
    account_no = payload.account_no.strip()
    if account is None:
        account = PayoutAccount(user_id=user.id, role=user.role.value)
        db.add(account)
    account.kind = payload.kind
    account.holder_name = holder
    account.account_no_encrypted = encrypt(account_no)
    account.account_tail = account_no[-4:]
    account.bank_name = payload.bank_name.strip()
    account.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(account)
    return account_out(account)
