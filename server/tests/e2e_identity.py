"""用户实名认证验证:校验位拦截、成年/未成年判定、明文不出接口、
重复提交 409、注销删除实名数据。

在 server/ 目录下运行:python -m tests.e2e_identity
"""
import asyncio
import json
import urllib.request

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import BASE, call, register_fresh_customer

_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_CHECK_CHARS = "10X98765432"


def make_id(birth: str, seq: str = "123") -> str:
    """构造合法身份证号:地址码 110101 + 出生日期 + 顺序码 + 真实校验位。"""
    body = f"110101{birth}{seq}"
    checksum = sum(int(d) * w for d, w in zip(body, _WEIGHTS)) % 11
    return body + _CHECK_CHARS[checksum]


def raw_call(method, path, token, body=None):
    """返回原始响应文本(验证明文不出接口用)。"""
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data) as resp:
        return resp.read().decode()


async def db_row(sql, **params):
    async with SessionLocal() as db:
        return (await db.execute(text(sql), params)).first()


async def main():
    adult_id = make_id("20000101")
    minor_id = make_id("20150601")

    # 1) 未实名状态
    user = register_fresh_customer()
    s = call("GET", "/auth/identity-status", user)
    assert s["verified"] is False, s
    print("✓ 初始状态未实名")

    # 2) 非法证号被拒:校验位错误 / 日期非法 / 长度不对
    bad_checksum = adult_id[:17] + ("0" if adult_id[17] != "0" else "1")
    err = call("POST", "/auth/verify-identity", user,
               {"real_name": "测试用户", "id_no": bad_checksum},
               expect_error=True)
    assert err["_error"] == 422 and "校验位" in err["detail"], err
    err = call("POST", "/auth/verify-identity", user,
               {"real_name": "测试用户", "id_no": make_id("20000230")},
               expect_error=True)
    assert err["_error"] == 422 and "出生日期" in err["detail"], err
    err = call("POST", "/auth/verify-identity", user,
               {"real_name": "测试用户", "id_no": "12345"}, expect_error=True)
    assert err["_error"] == 422, err
    print("✓ 非法身份证号 422(校验位/日期/长度)")

    # 3) 合法且成年:verified + is_adult,响应与状态接口均无证号明文
    raw = raw_call("POST", "/auth/verify-identity", user,
                   {"real_name": "王小明", "id_no": adult_id})
    r = json.loads(raw)
    assert r["verified"] is True and r["is_adult"] is True, r
    assert adult_id not in raw, "响应不得含证号明文"
    assert r["real_name"] == "王**", r
    raw = raw_call("GET", "/auth/identity-status", user)
    assert adult_id not in raw and json.loads(raw)["is_adult"] is True
    print("✓ 成年实名通过,打码姓名,接口无证号明文")

    # 4) 库里是密文;重复提交 409
    row = await db_row(
        "SELECT id_no_encrypted FROM user_identities "
        "WHERE real_name = '王小明' ORDER BY id DESC LIMIT 1")
    assert row and adult_id not in row[0], "库里必须是密文"
    err = call("POST", "/auth/verify-identity", user,
               {"real_name": "王小明", "id_no": adult_id}, expect_error=True)
    assert err["_error"] == 409, err
    print("✓ 证号加密落库,重复提交 409")

    # 5) 未成年:verified 但 is_adult=false
    minor = register_fresh_customer()
    r = call("POST", "/auth/verify-identity", minor,
             {"real_name": "李小朋", "id_no": minor_id})
    assert r["verified"] is True and r["is_adult"] is False, r
    print("✓ 未成年实名通过但 is_adult=false")

    # 6) 注销账号,实名数据一并删除
    before = await db_row(
        "SELECT count(*) FROM user_identities WHERE real_name = '李小朋'")
    assert before[0] >= 1
    call("DELETE", "/auth/me", minor)
    after = await db_row(
        "SELECT count(*) FROM user_identities WHERE real_name = '李小朋'")
    assert after[0] == before[0] - 1, "注销后实名记录应删除"
    print("✓ 注销账号实名数据一并删除")

    print("\ne2e_identity 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
