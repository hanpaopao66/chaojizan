"""骑手上岗管理验证:考试强制开关、80 分通过/不及格重考、
上线卡点、装备申领→发放留痕、宽限(开关关)不拦。

在 server/ 目录下运行:python -m tests.e2e_rider_onboarding
"""
import asyncio
import json
from pathlib import Path

from tests.util import call, login, register_fresh_rider

admin = login("13800000000")
BANK = {q["id"]: q for q in json.loads(
    (Path(__file__).resolve().parent.parent / "app" / "data"
     / "rider_quiz.json").read_text(encoding="utf-8"))["questions"]}


def take_exam(rider, correct=10):
    """按题库作答:correct 题答对,其余答错。"""
    qs = call("GET", "/riders/exam/questions", rider)
    answers = {}
    for i, q in enumerate(qs):
        right = BANK[q["id"]]["answer"]
        answers[str(q["id"])] = right if i < correct else (right + 1) % 4
    return call("POST", "/riders/exam/submit", rider, {"answers": answers})


async def main():
    rider = await register_fresh_rider("上岗测试骑手")

    # 1) 开关关(默认):未考试也能上线(存量宽限)
    call("POST", "/riders/online", rider, {"is_online": True})
    call("POST", "/riders/online", rider, {"is_online": False})
    print("✓ 考试开关默认关:存量骑手不受影响")

    call("POST", "/admin/flags/rider_exam_required", admin, {"value": "on"})
    try:
        # 2) 开关开:未通过考试上线 403
        err = call("POST", "/riders/online", rider, {"is_online": True},
                   expect_error=True)
        assert err["_error"] == 403 and "培训考试" in err["detail"], err
        print("✓ 强制开启后,未通过考试上线 403")

        # 3) 不及格(7 题对=70 分)不通过,可重考;满分通过后可上线
        r = take_exam(rider, correct=7)
        assert r["score"] == 70 and r["passed"] is False, r
        status = call("GET", "/riders/exam/status", rider)
        assert status["passed"] is False and status["best_score"] == 70
        r = take_exam(rider, correct=10)
        assert r["score"] == 100 and r["passed"] is True, r
        call("POST", "/riders/online", rider, {"is_online": True})
        print("✓ 70 分不过可重考,100 分通过后正常上线")
    finally:
        call("POST", "/admin/flags/rider_exam_required", admin,
             {"value": "off"})

    # 4) 装备:申领→重复 409→发放留痕
    call("POST", "/riders/gear", rider, {"item": "helmet"})
    err = call("POST", "/riders/gear", rider, {"item": "helmet"},
               expect_error=True)
    assert err["_error"] == 409, err
    reqs = call("GET", "/admin/rider-gear?status=requested", admin)
    mine = next(g for g in reqs if g["item"] == "helmet"
                and g["rider_phone"])
    call("POST", f"/admin/rider-gear/{mine['id']}/issue", admin,
         {"note": "到站点自取"})
    gear = call("GET", "/riders/gear", rider)
    assert any(g["item"] == "helmet" and g["status"] == "issued"
               and "自取" in g["note"] for g in gear)
    err = call("POST", "/riders/gear", rider, {"item": "bike"},
               expect_error=True)
    assert err["_error"] == 422, err
    print("✓ 装备申领防重、发放留痕、非法装备 422")

    print("\ne2e_rider_onboarding 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
