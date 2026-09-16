"""后台页面和管理接口共用 `/admin` 前缀(#312)。

## 这条守什么

`/admin/flags`、`/admin/merchants`、`/admin/riders` 这些路径
**既是后台的前端路由,也是接口路径** —— 一共 7 条真的会撞。
分开它们的不是路由顺序(谁在前谁就把另一个全吃掉),
而是「这次请求是不是浏览器在打开一个页面」。

所以这里锁三件事,每一条坏掉都是一种很难往"路由"上想的故障:

1. 浏览器打开 /admin/flags → **页面**(不是一段 JSON);
2. 后台自己 fetch /admin/flags → **JSON**(不是一坨 HTML,
   否则后台每个接口都会在解析时炸);
3. /admin/assets/*.js → **真文件**。它们不是导航请求,
   顺序写错就会被放行给接口然后 404 —— 表现是
   "后台打得开但一片空白",最难排查的一种。

在 server/ 目录下运行:python -m tests.e2e_admin_console
"""
from tests.miniapp_util import admin_token
from tests.util import call, request_raw


def main() -> None:
    # ---------- 1) 浏览器导航拿到页面 ----------
    for path in ("/admin", "/admin/flags", "/admin/merchants",
                 "/admin/riders", "/admin/order-flags"):
        st, ctype, body = request_raw(
            "GET", path,
            headers={"Sec-Fetch-Dest": "document", "Accept": "text/html"})
        assert st == 200, f"{path} 导航拿到 {st}"
        assert "text/html" in ctype, f"{path} 不是页面:{ctype}"
        assert "<div id=" in body or "<script" in body, f"{path} 不像 SPA 壳"
    print("✓ 浏览器打开 /admin 及会撞车的那几条,拿到的都是后台页面")

    # ---------- 2) fetch 拿到接口 ----------
    # 只挑**真的同时是接口**的那几条。/admin/riders 是纯前端路由,
    # 服务端没有对应的 GET —— 拿它断言 401 是在测一个不存在的东西
    for path in ("/admin/flags", "/admin/merchants", "/admin/order-flags"):
        st, ctype, _ = request_raw(
            "GET", path,
            headers={"Sec-Fetch-Dest": "empty", "Accept": "*/*"})
        assert "json" in ctype, (
            f"{path} 的 fetch 拿到了 {ctype} —— 后台每个接口都会在解析时炸")
        assert st in (401, 403), f"{path} 未鉴权却不是 401/403:{st}"
    print("✓ 后台 fetch 同样这几条路径,拿到的是 JSON(未登录 401)")

    # ---------- 3) 静态资源按真文件返回 ----------
    _, _, shell = request_raw(
        "GET", "/admin",
        headers={"Sec-Fetch-Dest": "document", "Accept": "text/html"})
    import re
    assets = re.findall(r'/admin/assets/[A-Za-z0-9._-]+\.(?:js|css)', shell)
    assert assets, f"页面里没有引任何构建产物:{shell[:200]}"
    for a in assets[:3]:
        st, ctype, _ = request_raw("GET", a)
        assert st == 200, f"{a} → {st} —— 后台会打得开但一片空白"
        assert "javascript" in ctype or "css" in ctype, ctype
    print(f"✓ 构建产物({len(assets)} 个)按真实文件返回")

    # ---------- 4) 老路径 301 到新路径 ----------
    for old, new in (("/admin-console", "/admin"),
                     ("/admin-console/flags", "/admin/flags")):
        st, _, _ = request_raw("GET", old, allow_redirects=False)
        assert st == 301, f"{old} 没有 301:{st}"
    print("✓ /admin-console 301 到 /admin,老书签不断")

    # ---------- 5) 旧的单文件审核页已经下线 ----------
    st, _, _ = request_raw("GET", "/admin.html")
    assert st == 404, f"旧后台还在:{st}"
    print("✓ 旧的单文件审核页已下线")

    # ---------- 6) 拨一个开关,别的开关不许在返回里消失 ----------
    # 后台那一页是 `setFlags(await setFlag(...))` —— 拿返回值**整个替换**它手里的
    # 开关表。所以 POST 必须回完整的一份。原来只回 `{改的那一个: 值}`,
    # 于是拨一个开关、页面上另外三十个当场全变成「关」:库里一个都没动、
    # 刷新就回来了,但看见的人不知道,他会挨个去「修」——
    # 而每一下都是真写入,还会进透明中心的公开时间线
    adm = admin_token()
    before = call("GET", "/admin/flags", adm)
    assert len(before) > 5, f"开关表太短,下面的断言没意义:{before}"
    others = {k: v for k, v in before.items() if k != "weather_shutdown"}

    was = before.get("weather_shutdown", "off")
    resp = call("POST", "/admin/flags/weather_shutdown", adm,
                {"value": "on" if was != "on" else "off", "reason": "e2e 回归"})
    missing = sorted(set(others) - set(resp))
    assert not missing, (
        f"拨一个开关之后,返回里少了 {len(missing)} 个开关:{missing[:6]}…\n"
        "后台那一页会拿这份整个替换,少掉的在页面上全显示成「关」")
    assert {k: resp[k] for k in others} == others, (
        "别的开关的值在返回里被改了 —— 页面上会显示成刚才那一下把它们也拨了")

    # **反证**:库里真的只动了那一个。不然"返回里都在"也可能是它
    # 把整张表一起写了一遍
    after = call("GET", "/admin/flags", adm)
    assert {k: v for k, v in after.items() if k != "weather_shutdown"} == others, \
        "别的开关在库里也被动了"
    assert after["weather_shutdown"] != was, "要改的那一个反倒没改成"
    call("POST", "/admin/flags/weather_shutdown", adm, {"value": was, "reason": "e2e 复原"})
    print("✓ 拨一个开关:返回里带着完整的一份,别的开关值不变、库里也只动了那一个")

    print("\ne2e_admin_console 全部通过 ✅")


if __name__ == "__main__":
    main()
