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

print("\n收款账户与打款风控验证通过 🎉")
