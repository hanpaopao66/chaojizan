"""收款账户与打款风控:未登记不能提现、账号只回尾号、申请快照冻结、
改账户不影响在途、24h 内变更标黄人工加核。
在 server/ 目录下运行:python -m tests.e2e_payout_account
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal, engine
from tests.util import call, login

rider = login("13800000003")
admin = login("13800000000")

# 新注册骑手:未登记账户 → 提现 422(先于余额校验,引导先设置)
phone = f"139{int(time.time()) % 100000000:08d}"
fresh = call("POST", "/auth/register",
             body={"phone": phone, "password": "123456",
                   "name": "新骑手", "role": "rider"})["token"]
err = call("POST", "/riders/withdrawals", fresh,
           {"amount_cents": 1000}, expect_error=True)
assert err["_error"] == 422 and "收款账户" in err["detail"]
print(f"✓ 未登记收款账户不能提现:{err['detail']}")

# 银行类必填开户行
err = call("PUT", "/payout-account", fresh,
           {"kind": "bank_personal", "holder_name": "新骑手",
            "account_no": "6222020200112233445"}, expect_error=True)
assert err["_error"] == 422
saved = call("PUT", "/payout-account", fresh,
             {"kind": "bank_personal", "holder_name": "新骑手",
              "account_no": "6222020200112233445", "bank_name": "工商银行测试支行"})
assert saved["configured"] is True and saved["account_tail"] == "3445"
assert "account_no" not in saved, "普通接口不得回完整账号"
assert saved["recently_changed"] is True
got = call("GET", "/payout-account", fresh)
assert got["account_tail"] == "3445" and "account_no" not in got
print("✓ 登记成功:银行类必填开户行,接口只回尾 4 位")

# 演示骑手(seed 已登记支付宝):申请快照冻结
wd = call("POST", "/riders/withdrawals", rider, {"amount_cents": 1000})
mine = call("GET", "/riders/withdrawals", rider)
assert all("account_snapshot" not in x for x in mine), "普通接口不得泄漏快照"
rows = call("GET", "/admin/withdrawals?role=rider", admin)
rec = next(x for x in rows if x["id"] == wd["id"])
assert rec["account_kind"] == "alipay" and rec["account_holder"] == "王小王"
assert rec["account_no"] == "13800000003", "管理端应看到解密后的完整账号"
print("✓ 申请携带账户快照,管理端可见完整打款信息")

# 改账户不影响在途快照;新申请用新账户
call("PUT", "/payout-account", rider,
     {"kind": "wechat", "holder_name": "王小王", "account_no": "wxid_9999"})
rows = call("GET", "/admin/withdrawals?role=rider", admin)
rec = next(x for x in rows if x["id"] == wd["id"])
assert rec["account_kind"] == "alipay" and rec["account_no"] == "13800000003"
wd2 = call("POST", "/riders/withdrawals", rider, {"amount_cents": 1000})
rows = call("GET", "/admin/withdrawals?role=rider", admin)
rec2 = next(x for x in rows if x["id"] == wd2["id"])
assert rec2["account_kind"] == "wechat" and rec2["account_no"] == "wxid_9999"
assert rec2["account_recently_changed"] is True
print("✓ 快照冻结:改账户不影响在途申请;刚变更的新申请标黄加核")


async def backdate_account():
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE payout_accounts SET updated_at = now() - interval '2 days' "
            "WHERE user_id = (SELECT id FROM users WHERE phone = '13800000003')"))
        await db.commit()
    # 脚本里多次 asyncio.run:释放连接池,避免连接绑到已关闭的事件循环
    await engine.dispose()


asyncio.run(backdate_account())
wd3 = call("POST", "/riders/withdrawals", rider, {"amount_cents": 1000})
rows = call("GET", "/admin/withdrawals?role=rider", admin)
rec3 = next(x for x in rows if x["id"] == wd3["id"])
assert rec3["account_recently_changed"] is False
print("✓ 账户稳定超过 24h 后,新申请不再标黄")

# 恢复现场:登记回支付宝、驳回测试申请
call("PUT", "/payout-account", rider,
     {"kind": "alipay", "holder_name": "王小王", "account_no": "13800000003"})
asyncio.run(backdate_account())
for w in (wd, wd2, wd3):
    call("POST", f"/admin/withdrawals/{w['id']}/reject", admin, {"reason": "e2e清场"})

# ---------- 户名必须与实名一致(防顶替跑单) ----------
#
# 二要素核验只证明"这个姓名+证号真实且匹配",不证明拿手机的人就是他。
# 众包没有站长天天见人,而「实名张三、提现打给李四」是账号出租最硬的
# 信号 —— 它在资金侧,租号的人图的就是把钱收走。

# 1) 登记时就卡:演示骑手实名是「王小王」,填别人的名字要被挡回来
err = call("PUT", "/payout-account", rider,
           {"kind": "alipay", "holder_name": "李四",
            "account_no": "13800000003"}, expect_error=True)
assert err["_error"] == 422, err
assert "王小王" in str(err["detail"]), "提示里要带本人实名,否则他不知道该填什么"
print(f"✓ 户名与实名不符,登记就被挡:{err['detail'][:28]}…")

# 2) 只是写法不同的要放行 —— 空格、间隔号码位不统一是常态,
#    尤其是少数民族姓名,不能把这批人卡在提现门外
ok = call("PUT", "/payout-account", rider,
          {"kind": "alipay", "holder_name": " 王 小　王 ",
           "account_no": "13800000003"})
assert ok["configured"] is True
# 存的是证件上那一份,不是他输入的那一份 —— 带空格的户名银行不认,
# 而这个字符串会一路进提现快照和管理端打款界面
assert ok["holder_name"] == "王小王", ok["holder_name"]
print("✓ 「 王 小　王 」照常通过,且落库归一成证件写法「王小王」")

# 3) 没实名的骑手不卡登记 —— 他也没余额可提,真正的闸门在提现那一步
ok2 = call("PUT", "/payout-account", fresh,
           {"kind": "alipay", "holder_name": "随便谁", "account_no": "13900000000"})
assert ok2["configured"] is True
print("✓ 未实名的骑手允许先登记账户(他没有余额,闸门在提现)")


# 4) **提现那道闸要独立生效**:历史账户是在这条规则之前登记的,
#    只卡登记拦不住。绕过接口直接改库造出这种账户,再去提现
async def tamper_holder():
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE payout_accounts SET holder_name = '李四' "
            "WHERE user_id = (SELECT id FROM users WHERE phone = '13800000003')"))
        await db.commit()
    await engine.dispose()


asyncio.run(tamper_holder())
err = call("POST", "/riders/withdrawals", rider,
           {"amount_cents": 1000}, expect_error=True)
assert err["_error"] == 422, err
assert "王小王" in str(err["detail"]), err
print("✓ 历史账户(绕过登记闸口)在提现那一步被拦下")

# 恢复现场
call("PUT", "/payout-account", rider,
     {"kind": "alipay", "holder_name": "王小王", "account_no": "13800000003"})
asyncio.run(backdate_account())

print("\n收款账户与打款风控验证通过 🎉")
