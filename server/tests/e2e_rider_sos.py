"""骑手 SOS 验证:紧急联系人加密落库/打码展示、触发落单带位置、
后台列表标红与跟进/结案留痕、误触窗口内自助撤销、跟进后不可撤销。

在 server/ 目录下运行:python -m tests.e2e_rider_sos
"""
import asyncio

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import call, login, register_fresh_rider

admin = login("13800000000")


async def main():
    rider = await register_fresh_rider("SOS测试骑手")

    # 1) 紧急联系人:校验、加密落库(库里无明文)、接口打码
    err = call("POST", "/riders/me/emergency-contacts", rider,
               {"contacts": [{"name": "家人", "phone": "123"}]},
               expect_error=True)
    assert err["_error"] == 422
    call("POST", "/riders/me/emergency-contacts", rider,
         {"contacts": [{"name": "家人", "phone": "13900000001"},
                       {"name": "朋友", "phone": "13900000002"}]})
    contacts = call("GET", "/riders/me/emergency-contacts", rider)
    assert len(contacts) == 2
    assert "****" in contacts[0]["phone"], contacts  # 打码展示
    rider_id = call("GET", "/auth/me", rider)["id"]
    async with SessionLocal() as db:
        enc = (await db.execute(text(
            "SELECT emergency_contacts_enc FROM rider_profiles "
            "WHERE rider_id = :rid"), {"rid": rider_id})).scalar()
    assert enc and "13900000001" not in enc, "明文不得落库"
    print("✓ 紧急联系人加密落库,接口打码展示")

    # 2) 触发 SOS:落单带位置;后台 open 列表可见
    r = call("POST", "/riders/sos", rider,
             {"lat": 30.66, "lng": 104.08, "note": "被堵在小区里"})
    sos_id = r["id"]
    assert r["cancel_window_seconds"] > 0
    listed = call("GET", "/admin/rider-emergencies?status=open", admin)
    mine = next(e for e in listed if e["id"] == sos_id)
    assert mine["lat"] == 30.66 and "被堵" in mine["note"]
    print("✓ SOS 触发落单带位置,后台加急可见")

    # 3) 误触窗口内自助撤销
    call("POST", f"/riders/sos/{sos_id}/cancel", rider)
    listed = call("GET", "/admin/rider-emergencies?status=cancelled", admin)
    assert any(e["id"] == sos_id for e in listed)
    print("✓ 窗口内自助撤销")

    # 4) 再触发一单:客服跟进后骑手不可再撤销;跟进/结案留痕
    r2 = call("POST", "/riders/sos", rider, {"lat": 30.66, "lng": 104.08})
    call("POST", f"/admin/rider-emergencies/{r2['id']}/update", admin,
         {"status": "following", "note": "已电话回访,骑手安全,车坏了"})
    err = call("POST", f"/riders/sos/{r2['id']}/cancel", rider,
               expect_error=True)
    assert err["_error"] == 409, err
    err = call("POST", f"/admin/rider-emergencies/{r2['id']}/update", admin,
               {"status": "closed", "note": ""}, expect_error=True)
    assert err["_error"] == 422  # 结案必须留痕
    call("POST", f"/admin/rider-emergencies/{r2['id']}/update", admin,
         {"status": "closed", "note": "已协助叫拖车,结案"})
    closed = call("GET", "/admin/rider-emergencies?status=closed", admin)
    target = next(e for e in closed if e["id"] == r2["id"])
    assert len(target["actions"]) == 2 and target["actions"][1]["admin_id"]
    print("✓ 跟进后不可自助撤销,处置双留痕")

    print("\ne2e_rider_sos 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
