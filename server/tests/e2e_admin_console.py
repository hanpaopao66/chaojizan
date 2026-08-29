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

    print("\ne2e_admin_console 全部通过 ✅")


if __name__ == "__main__":
    main()
