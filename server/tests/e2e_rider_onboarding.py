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
        # correct 给大数 = 全对。题数由服务端决定(现在是 5),
        # 这里不写死题数,免得服务端一调就挂
        answers[str(q["id"])] = right if i < correct else (right + 1) % 4
    return call("POST", "/riders/exam/submit", rider, {"answers": answers})


async def set_grace(value: str):
    """宽限截止日。测试必须自己控制 —— 否则跑在窗口开着的库上,
    硬卡点那条会被静默跳过。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import settings
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO platform_flags (key, value)
                VALUES ('rider_training_grace_until', :v)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """), {"v": value})
    finally:
        await engine.dispose()


async def main():
    rider = await register_fresh_rider("上岗测试骑手")
    # 助手会给新骑手写一条培训记录(完整入驻的骑手都该有)。
    # 本用例要验的是"没培训会怎样",所以先清掉
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import settings
    me = call("GET", "/auth/me", rider)["id"]
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM rider_exams WHERE rider_id = :r"), {"r": me})
    finally:
        await engine.dispose()

    # 1) 宽限窗口内:没培训也能上线,但要提醒 ——
    #    存量骑手不能某天早上全部上不了线,挡了就是让他今天没饭吃
    await set_grace("2099-12-31")
    on = call("POST", "/riders/online", rider, {"is_online": True})
    assert on["is_online"] is True, on
    assert on.get("warning") and "培训" in on["warning"], on
    call("POST", "/riders/online", rider, {"is_online": False})
    print("✓ 宽限窗口内:放行 + 提醒(存量骑手不受硬卡)")

    try:
        # 2) 宽限过期:没培训不能上线。
        #    食安培训是法定要求(123 号令第二十九条,罚则第四十四条)
        await set_grace("2020-01-01")
        err = call("POST", "/riders/online", rider, {"is_online": True},
                   expect_error=True)
        assert err["_error"] == 403 and "培训" in err["detail"], err
        print("✓ 宽限过期:未完成食安培训不能上线")

        # 3) 答错当场讲解、可重来;全对即完成 ——
        #    法规要的是培训到位,不是判他不及格把他挡在外面
        r = take_exam(rider, correct=3)
        assert r["passed"] is False, r
        assert r["wrong"], "答错要把错在哪讲出来"
        assert all(w.get("answer_text") for w in r["wrong"]), \
            "只回一个「错了」等于什么都没培训"
        r = take_exam(rider, correct=99)   # 全对
        assert r["passed"] is True and r["score"] == 100, r
        on = call("POST", "/riders/online", rider, {"is_online": True})
        assert on["is_online"] is True and not on.get("warning"), on
        print("✓ 答错有讲解可重来;全对后正常上线")
    finally:
        await set_grace("2020-01-01")

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
