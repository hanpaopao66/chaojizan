"""骑手入驻:实名当场核验 + 食安培训卡点(#165-#167)。

## 门槛为什么只有姓名 + 身份证号

逐条核过法规:

- **人脸认证不做**:《人脸识别技术应用安全管理办法》(网信办+公安部,
  2025-06-01 施行)明写"存在其他非人脸方式能达到同等业务要求的,
  **不得将人脸识别作为唯一验证方式**",并鼓励优先用国家人口基础信息库 ——
  二要素核验正是那个方式;
- **健康证不是法定要求**:《网络餐饮服务食品安全监督管理办法》要求餐食封装、
  避免送餐人员直接接触食品,送餐员因此不属于"直接接触入口食品的人员"。
  四川已明确取消。所以选填;
- **身份证照片不收**:二要素核验不需要它,而它是敏感个人影像;
- **食品安全培训是法定要求**(总局令第 123 号第二十九条,罚则第四十四条):
  受托方应当对配送人员进行食安培训、留存记录 ≥2 年。**这条不能省。**

在 server/ 目录下运行:python -m tests.e2e_rider_verify
"""
import asyncio
import json
import time
from pathlib import Path

from tests.util import call, login

admin = login("13800000000")


def make_id(prefix17: str) -> str:
    """拼一个校验位正确的身份证号(测试用,非真实号码)。"""
    from app.services.idcheck import _CHECK_CHARS, _WEIGHTS
    return prefix17 + _CHECK_CHARS[
        sum(int(d) * w for d, w in zip(prefix17, _WEIGHTS)) % 11]


def set_grace(value: str):
    """设置存量骑手的培训宽限截止日。

    测试必须自己控制它 —— 否则跑在"宽限窗口开着"的库上,
    硬卡点那一条会被静默跳过,测了个寂寞。
    """
    async def go():
        # 每次用独立引擎:asyncio.run 每次新建事件循环,
        # 而共享的 SessionLocal 连接池绑在第一个循环上,复用会炸
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
    asyncio.run(go())


def fresh_rider(name="新骑手"):
    phone = "138" + str(int(time.time() * 1000))[-8:]
    token = call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "name": name, "role": "rider",
    })["token"]
    return token, phone


ADULT_ID = make_id("51010119900101001")
MINOR_ID = make_id("51010120150101001")

rider, phone = fresh_rider()

# ---------- 1. 未认证不能上线 ----------
err = call("POST", "/riders/online", rider, {"is_online": True},
           expect_error=True)
assert err["_error"] == 403, err
print(f"✓ 未认证不能上线:{err['detail']}")

prof = call("GET", "/riders/profile", rider)
assert prof["status"] == "unsubmitted", prof
assert prof["id_verified"] is False, prof
print("✓ 初始状态 unsubmitted")

# ---------- 2. 提交:只要姓名 + 身份证号,不传任何照片 ----------
err = call("POST", "/riders/profile", rider,
           {"real_name": "王小明", "id_card_no": "123"}, expect_error=True)
assert err["_error"] == 422, err
print("✓ 证号格式非法被拒")

# 校验位错的号必须拦下 —— 拦不住等于没有实名
bad = ADULT_ID[:17] + ("0" if ADULT_ID[17] != "0" else "1")
err = call("POST", "/riders/profile", rider,
           {"real_name": "王小明", "id_card_no": bad}, expect_error=True)
assert err["_error"] == 422 and "校验位" in err.get("detail", ""), err
print("✓ 校验位不正确被拒")

err = call("POST", "/riders/profile", rider,
           {"real_name": "小朋友", "id_card_no": MINOR_ID}, expect_error=True)
assert err["_error"] == 422 and "18" in err.get("detail", ""), err
print("✓ 未满 18 周岁被拒")

# **不传身份证照片、不传健康证** —— 这是这一批的核心
prof = call("POST", "/riders/profile", rider,
            {"real_name": "王小明", "id_card_no": ADULT_ID})
assert prof["status"] == "approved", \
    f"二要素核验通过就该当场生效,不该再 pending 等人工:{prof}"
assert prof["id_verified"] is True, prof
assert prof["health_cert_photo_url"] == "", "健康证没填也要能过"
print("✓ 只填姓名+证号 → 二要素核验 → **当场 approved**,没有等待人工审")

# ---------- 3. 证号绝不出接口 ----------
blob = json.dumps(prof, ensure_ascii=False)
assert ADULT_ID not in blob, "身份证号明文出现在返回体里"
assert prof["real_name"] != "王小明", "姓名要打码"
assert prof["real_name"].startswith("王"), prof
print(f"✓ 证号不出接口,姓名打码为「{prof['real_name']}」")

# 后台也不给证号 —— 一个列表接口不该批量吐出几百个身份证号
rows = call("GET", "/admin/rider-profiles?status=approved", admin)
mine = next((p for p in rows if p["rider_phone"] == phone), None)
assert mine is not None, "后台应能看到这条记录"
assert ADULT_ID not in json.dumps(rows, ensure_ascii=False), \
    "管理后台列表批量吐出了身份证号明文"
assert mine["id_verified"] is True, mine
print("✓ 管理后台可见记录,但列表里没有证号明文")

err = call("GET", "/admin/rider-profiles", rider, expect_error=True)
assert err["_error"] == 403, err
print("✓ 非管理员不能访问审核接口")

# ---------- 4. 食安培训:法定要求,上线前必须完成 ----------
tr = call("GET", "/riders/training", rider)
assert tr["done"] is False, tr
assert tr["sections"], "培训内容不能是空的"
assert "123" in tr["why"], "要告诉骑手这是法律要求平台做的,不是平台加的规矩"
assert 1 <= tr["minutes"] <= 10, tr
print(f"✓ 培训内容 {tr['minutes']} 分钟 / {len(tr['sections'])} 节 / "
      f"版本 {tr['version']}")

# 先验宽限窗口:存量骑手不能某天早上全部上不了线
set_grace("2099-12-31")
on = call("POST", "/riders/online", rider, {"is_online": True})
assert on["is_online"] is True, on
assert on.get("warning") and "培训" in on["warning"], \
    f"宽限期内要提醒他去培训,但不能挡住他上线:{on}"
print(f"✓ 宽限窗口内:放行 + 提醒(挡了就是让他今天没饭吃)")
call("POST", "/riders/online", rider, {"is_online": False})

# 宽限过期 → 硬卡点
set_grace("2020-01-01")
err = call("POST", "/riders/online", rider, {"is_online": True},
           expect_error=True)
assert err["_error"] == 403 and "培训" in err.get("detail", ""), err
print("✓ 宽限过期:实名通过但没培训 → 不能上线(第二十九条是有罚则的)")

# 宽限日期写错也不能放行 —— 配置错误不该让合规卡点形同虚设
set_grace("这不是日期")
err = call("POST", "/riders/online", rider, {"is_online": True},
           expect_error=True)
assert err["_error"] == 403, err
print("✓ 宽限配置写错:仍然卡住(不因配置错误而放行)")
set_grace("2020-01-01")

# 答错:当场给正确答案和理由,可以立刻重来 —— 这才是「培训」
bank = {q["id"]: q for q in json.loads(
    (Path("app/data/rider_quiz.json")).read_text(encoding="utf-8"))["questions"]}
qs = call("GET", "/riders/exam/questions", rider)
wrong_answers = {}
for q in qs:
    right = bank[q["id"]]["answer"]
    wrong_answers[str(q["id"])] = 0 if right != 0 else 1
res = call("POST", "/riders/exam/submit", rider, {"answers": wrong_answers})
assert res["passed"] is False, res
assert res["wrong"], "答错了要把错在哪讲出来"
for w in res["wrong"]:
    assert "answer_text" in w and w["answer_text"], \
        "只回一个「错了」等于什么都没培训"
print(f"✓ 答错 {len(res['wrong'])} 题:当场给正确答案与解释,可重答")

# 全对 → 完成
qs = call("GET", "/riders/exam/questions", rider)
res = call("POST", "/riders/exam/submit", rider,
           {"answers": {str(q["id"]): bank[q["id"]]["answer"] for q in qs}})
assert res["passed"] is True and res["score"] == 100, res
print(f"✓ 全对 → 培训完成:{res['message']}")

on = call("POST", "/riders/online", rider, {"is_online": True})
assert on["is_online"] is True, on
assert on.get("warning", "") == "", on
print("✓ 培训完成后正常上线")

# ---------- 5. 培训记录留痕(法定 ≥2 年) ----------
st = call("GET", "/riders/exam/status", rider)
assert st["passed"] is True and st["version"], st
print(f"✓ 培训记录留痕(内容版本 {st['version']}) —— "
      f"第二十九条要求保存不少于二年")

# ---------- 6. 已通过不能自行改 ----------
err = call("POST", "/riders/profile", rider,
           {"real_name": "改名", "id_card_no": ADULT_ID}, expect_error=True)
assert err["_error"] == 409, err
print("✓ 已通过认证不能自行修改(需客服)")

# ---------- 7. 后台仍可撤销(事后发现问题) ----------
rid = mine["rider_id"]
call("POST", f"/admin/rider-profiles/{rid}/reject", admin,
     {"reason": "核验后发现证件异常"})
prof = call("GET", "/riders/profile", rider)
assert prof["status"] == "rejected", prof
err = call("POST", "/riders/online", rider, {"is_online": True},
           expect_error=True)
assert err["_error"] == 403, err
print("✓ 后台撤销后立即不能上线(当场核验不等于此后不可复核)")

# ---------- 8. 健康证:只有本地有规章的城市才卡 ----------
#
# 国家层面不要求送餐员持健康证(不属于"直接接触入口食品的人员",
# 四川已明确取消)。杭州等地有地方规章 —— 做成城市级清单,默认空。
def set_cities(value):
    call("POST", "/admin/flags/health_cert_cities", admin, {"value": value})


rider2, phone2 = fresh_rider("健康证测试")
call("POST", "/riders/profile", rider2,
     {"real_name": "钱七", "id_card_no": make_id("51010119900202002")})
qs = call("GET", "/riders/exam/questions", rider2)
call("POST", "/riders/exam/submit", rider2,
     {"answers": {str(q["id"]): bank[q["id"]]["answer"] for q in qs}})

# city 是首次上线按定位解析出来的,这里直接落库模拟"已知城市"
async def _set_city(city):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import settings
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE users SET city = :c WHERE phone = :p"),
                {"c": city, "p": phone2})
    finally:
        await engine.dispose()


asyncio.run(_set_city("成都"))

set_cities("")
p2 = call("GET", "/riders/profile", rider2)
assert p2["health_cert_required"] is False, p2
assert p2["city"] == "成都", p2
assert call("POST", "/riders/online", rider2,
            {"is_online": True})["is_online"] is True
call("POST", "/riders/online", rider2, {"is_online": False})
print("✓ 城市不在清单里:不要健康证,正常上线")

# 中文逗号也要认 —— 后台是人在填
set_cities("杭州，成都")
p2 = call("GET", "/riders/profile", rider2)
assert p2["health_cert_required"] is True, \
    "本市要不要健康证得**提前**告知,等上线被拦才发现时人已经在路上了"
err = call("POST", "/riders/online", rider2, {"is_online": True},
           expect_error=True)
assert err["_error"] == 403 and "健康证" in err["detail"], err
assert "国家层面并不要求" in err["detail"], \
    "要说清楚这是本地规定而不是我们加的门槛"
print("✓ 城市在清单里:提前告知 + 上线卡住,并说明是地方规定")

set_cities("")
assert call("POST", "/riders/online", rider2,
            {"is_online": True})["is_online"] is True
call("POST", "/riders/online", rider2, {"is_online": False})
print("✓ 移出清单后恢复正常")

print("\n骑手入驻(实名当场核验 + 食安培训 + 健康证按城市)全部通过 🎉")
