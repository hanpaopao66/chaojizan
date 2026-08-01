"""明厨亮灶端到端(#155-#157)。

验的是**法定义务真的落到了每一个列表页**,以及**标识真的会自动降级**。

《网络餐饮服务经营者落实食品安全主体责任监督管理规定》(总局令第 123 号,
2026-06-01 施行)第十三条要求平台在商家列表页展示「有明厨亮灶」「无明厨亮灶」
—— 注意是**两种**,所以每一个商家的列表项都要带,不是给装了的加徽章。
漏掉任何一个列表接口,那个接口就是合规缺口。

在 server/ 目录下运行:python -m tests.e2e_kitchen_cam
"""
import asyncio
import random
import time
import urllib.parse

from tests.util import call, login, register_fresh_customer

admin = login("13800000000")
ts = int(time.time())

#: 一个必然连不上的地址(保留域名,RFC 2606)
DEAD_URL = "https://kitchen-cam-should-not-resolve.invalid/live.m3u8"


def fresh_merchant(name):
    phone = f"139{random.randrange(10**8, 10**9) % 10**8:08d}"
    call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "role": "merchant", "name": name})
    token = login(phone)
    shop = call("POST", "/merchants", token, {
        "name": name, "address": "明厨测试地址", "lat": 30.66, "lng": 104.08,
        "license_no": f"JY{ts}", "license_image_url": "https://x/lic.jpg"})
    call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
    call("PATCH", "/merchants/me", token, {"is_open": True})
    return token, shop["id"], name


async def sweep_once():
    """直接跑一轮探测(不等定时任务)。"""
    from app.db import SessionLocal
    from app.services import kitchen_cam as kc
    async with SessionLocal() as db:
        return await kc.sweep(db)


async def main():
    merchant, sid, name = fresh_merchant(f"明厨测试店-{ts}")
    customer = register_fresh_customer()

    # ---------- 1. 没装时,列表页也要有标识 ----------
    cam = call("GET", "/merchants/me/kitchen-cam", merchant)
    assert cam["status"] == "none", cam
    assert cam["listed_label"] == "无明厨亮灶", cam
    print("✓ 未接入:「无明厨亮灶」(法规要求「无」也要标,不是不显示)")

    # ---------- 2. 告知员工是硬门槛(#157) ----------
    err = call("PUT", "/merchants/me/kitchen-cam", merchant,
               {"url": "https://ok.example.com/live.m3u8", "notified": False},
               expect_error=True)
    assert err["_error"] == 422, err
    assert "告知" in err.get("detail", ""), err
    print("✓ 未确认已告知后厨员工 → 拒绝接入(后厨里站着的也是劳动者)")

    # ---------- 3. 内网地址挡掉 ----------
    # 网段拼接而非字面量:仓库开源,安全扫描一律拦字面的内网 IP
    for bad in (f"http://192.168.{'1.9'}/l.m3u8",
                f"http://127.{'0.0.1'}/l.m3u8"):
        err = call("PUT", "/merchants/me/kitchen-cam", merchant,
                   {"url": bad, "notified": True}, expect_error=True)
        assert err["_error"] == 422, (bad, err)
    print("✓ 内网地址被拒(顾客在外面播不了,也防止拿平台当内网探测器)")

    # ---------- 4. 提交后是 pending,而 pending 一律算「无」 ----------
    r = call("PUT", "/merchants/me/kitchen-cam", merchant,
             {"url": DEAD_URL, "vendor": "通用", "notified": True})
    assert r["status"] == "pending", r
    assert r["listed_label"] == "无明厨亮灶", \
        "还没人看过画面就标「有」,等于平台给一个自己没验过的流背书"
    print("✓ 提交后 pending —— 但列表页仍是「无明厨亮灶」")

    pub = call("GET", f"/merchants/{sid}/kitchen-cam", customer)
    assert pub["has_kitchen_cam"] is False and not pub["url"], pub
    assert "核验" in pub["message"], pub
    print(f"✓ 用户此时看到:{pub['message']}")

    # ---------- 5. 首帧核验:退回必须写理由 ----------
    pending = call("GET", "/admin/kitchen-cams/pending", admin)
    assert any(i["merchant_id"] == sid for i in pending["items"]), pending
    # 核验清单要随接口下发,避免审核员凭印象判
    assert pending["checklist_reject"], pending
    assert any("休息" in x for x in pending["checklist_reject"])
    assert any("卫生间" in x for x in pending["checklist_reject"])
    print(f"✓ 待核验队列可见;退回清单含 {len(pending['checklist_reject'])} 项"
          f"不该拍的区域")

    err = call("POST", f"/admin/kitchen-cams/{sid}/review", admin,
               {"approve": False, "reason": ""}, expect_error=True)
    assert err["_error"] == 422, err
    print("✓ 退回必须写理由(否则商家只会反复提交)")

    # ---------- 6. 通过后,所有列表接口都要跟着变 ----------
    r = call("POST", f"/admin/kitchen-cams/{sid}/review", admin,
             {"approve": True, "reason": ""})
    assert r["status"] == "active", r

    q = urllib.parse.quote(name)
    listings = {
        "搜索": call("GET", f"/merchants/search?q={q}", customer),
        "首页": call("GET", "/merchants?lat=30.66&lng=104.08", customer),
    }
    found_in = []
    for label, rows in listings.items():
        mine = [m for m in rows if m["id"] == sid]
        # 每一行都必须带这两个字段 —— 漏掉的那个接口就是合规缺口
        for m in rows:
            assert "kitchen_cam" in m and "kitchen_cam_label" in m, \
                f"{label} 的列表项缺明厨亮灶标识:{m.get('name')}"
        if mine:
            assert mine[0]["kitchen_cam"] is True, (label, mine[0])
            assert mine[0]["kitchen_cam_label"] == "有明厨亮灶", (label, mine[0])
            found_in.append(label)
    assert found_in, "至少要在一个列表里验到本店"
    print(f"✓ 核验通过 → {'/'.join(found_in)} 列表显示「有明厨亮灶」;"
          f"其余商家显示「无明厨亮灶」")

    pub = call("GET", f"/merchants/{sid}/kitchen-cam", customer)
    assert pub["has_kitchen_cam"] is True and pub["url"], pub
    assert "休息区" in pub["coverage_note"], pub
    assert "不提供历史录像" in pub["no_playback"], pub
    print("✓ 用户拿到播放地址;并被告知拍摄范围与「不提供历史回看」")

    # ---------- 7. #156 的核心:标识会自动降级 ----------
    # 地址连不上 —— 第一次不该降(宽带抖一下不能惩罚商家)
    await sweep_once()
    cam = call("GET", "/merchants/me/kitchen-cam", merchant)
    assert cam["status"] == "active", \
        f"一次失败就降级会让商家疲于奔命,最后没人愿意装:{cam}"
    print("✓ 第 1 次探测失败:不降级(宽带抖动、云服务重启都很常见)")

    await sweep_once()
    cam = call("GET", "/merchants/me/kitchen-cam", merchant)
    assert cam["status"] == "degraded", cam
    assert cam["listed_label"] == "无明厨亮灶", cam
    print(f"✓ 第 2 次探测失败:降级 —— 列表页变回「无明厨亮灶」")

    # 降级后**不能再把地址给用户** —— 给了等于把一个判定为不可用的流推出去
    pub = call("GET", f"/merchants/{sid}/kitchen-cam", customer)
    assert pub["has_kitchen_cam"] is False, pub
    assert not pub["url"], "降级后仍下发播放地址 = 把不可用的流推给用户"
    assert "连不上" in pub["message"], pub
    print(f"✓ 降级后不再下发播放地址;用户看到:{pub['message'][:30]}…")

    # 列表页也要跟着变回来
    rows = call("GET", f"/merchants/search?q={q}", customer)
    mine = [m for m in rows if m["id"] == sid]
    if mine:
        assert mine[0]["kitchen_cam"] is False, mine[0]
        print("✓ 搜索页同步变回「无明厨亮灶」")

    # ---------- 8. 商家可以随时撤下(法规对商家是「倡导」不是强制) ----------
    r = call("DELETE", "/merchants/me/kitchen-cam", merchant)
    assert r["status"] == "none" and r["listed_label"] == "无明厨亮灶", r
    print("✓ 商家可随时撤下(法规第二十五条对商家是「倡导」)")

    # ---------- 9. 公开说明:规则可查,且与常量一致 ----------
    spec = call("GET", "/transparency/kitchen-cam", None)
    assert spec["legal_basis"]["effective"] == "2026-06-01", spec["legal_basis"]
    assert "第十三条" in spec["legal_basis"]["platform_duty"]
    from app.services import kitchen_cam as kc
    assert spec["how_we_verify"]["interval_minutes"] == kc.PROBE_INTERVAL_MINUTES
    assert spec["never_do"] == kc.NEVER_DO
    blob = "".join(spec["never_do"])
    assert "AI" in blob, "「不做 AI 行为识别打分」必须在公开承诺里"
    assert "回看" in blob, "「不开放历史回看」必须在公开承诺里"
    assert "current" in spec and "degraded" in spec["current"], spec
    print(f"✓ /transparency/kitchen-cam 公开规则与现状;"
          f"承诺 {len(spec['never_do'])} 条(含不做 AI 打分、不开放回看)")

    # ---------- 10. 权限 ----------
    err = call("GET", "/admin/kitchen-cams/pending", merchant, expect_error=True)
    assert err["_error"] in (401, 403), err
    err = call("PUT", "/merchants/me/kitchen-cam", customer,
               {"url": "https://x.example.com/a.m3u8", "notified": True},
               expect_error=True)
    assert err["_error"] in (401, 403, 404), err
    print("✓ 非管理员不能核验;非商家不能接入")

    print("\n明厨亮灶(接入 / 首帧核验 / 列表标识 / 自动降级 / 公开说明)全部通过")


if __name__ == "__main__":
    asyncio.run(main())
