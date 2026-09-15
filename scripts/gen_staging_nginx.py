#!/usr/bin/env python3
"""从生产 nginx 配置生成预发环境的 nginx 配置(docs/STAGING.md)。

    python3 scripts/gen_staging_nginx.py deploy/nginx/conf.d/superz.conf <输出目录>

输出目录里是 `superz-staging.conf` 和门禁通过后的那张页面,由 scripts/deploy_staging.sh
传到预发机、挂成 nginx 的 conf.d。

## 为什么生成,而不是另写一份

预发的意义就是「和生产一样」。手抄一份 location,生产改了预发忘了改,预发上测过的东西
上了生产照样出事 —— 而且是最难查的那种,因为「预发明明是好的」。所以这里按 superz.conf 里的
三个 `# [staging]` 标记**原样照抄**:

  - 文件开头到 `http-end`:gzip、map、log_format 这些 http 级配置;
  - 主站 server 块里 `locations-begin` 到 `locations-end`:client_max_body_size 和全部 location。

## 预发自己加的只有三样

1. **证书**换成预发域名那张(/etc/nginx/certs/staging/,部署机签好拷过来,见 deploy/staging-cert.sh);
2. **门禁**。预发按开发配置跑(验证码直接回显、模拟支付),谁进来都能登录任何账号,所以外面必须再有
   一道门:没带通行 cookie 的请求一律 302 到 /__gate,在那里输一次密码(HTTP Basic),拿到 cookie,
   30 天内不用再输。
   不能整站直接上 Basic:网页版调接口时自己带 `Authorization: Bearer …`,浏览器就不会再补发 Basic
   的那个头,接口会全部 401。
   /__gate 里也不能用 `return` 跳回首页:`return` 在 rewrite 阶段执行,**早于** auth_basic 的
   access 阶段 —— 那样根本不会弹密码框,直接发 cookie,门禁形同虚设。所以通过校验之后给的是一张
   静态页(content 阶段,一定在校验之后),页面自己跳走;
3. **反代给 api 的 Host 带上端口**。预发在非标准端口(:8443)上,`$host` 不带端口,api 按请求
   拼出来的绝对地址(小程序托管、分享链接)会掉端口。生产在 443 上,`$host` 和 `$http_host` 一样。

门禁的密码文件和 cookie 值只在预发机上(deploy/staging-gate/,deploy_staging.sh init 生成),
不进仓库,也不经过这个脚本。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKS = ("http-end", "locations-begin", "locations-end")
MARK_RE = re.compile(r"^\s*#\s*\[staging\]\s*(" + "|".join(MARKS) + r")\b")

OUT_CONF = "superz-staging.conf"
OUT_GATE_PAGE = "staging-gate-ok.html"

GATE_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>超级赞预发环境</title>
<style>
  body { margin: 0; padding: 32px 20px; font: 15px/1.7 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         color: #1f2328; background: #f6f7f9; }
  main { max-width: 32rem; margin: 0 auto; }
  h1 { font-size: 20px; margin: 0 0 8px; }
  p { margin: 0 0 16px; color: #57606a; }
  ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
  a { display: block; padding: 12px 14px; border-radius: 8px; background: #fff; color: #0b57d0;
      text-decoration: none; border: 1px solid #e2e5e9; }
  a:focus-visible { outline: 2px solid #0b57d0; outline-offset: 2px; }
</style>
</head>
<body>
<main>
  <h1>已进入预发环境</h1>
  <p>这里跑的是还没上线的代码和演示数据,验证码直接显示、付款是模拟的。30 天内这台设备不用再输密码。</p>
  <ul>
    <li><a href="/web/">用户端网页版</a></li>
    <li><a href="/merchant">商家后台</a></li>
    <li><a href="/admin">平台后台</a></li>
    <li><a href="/dev">开发者后台</a></li>
    <li><a href="/">官网</a></li>
  </ul>
</main>
</body>
</html>
"""

SERVER_HEAD = """\
# ---------------------------------------------------------------------------
# 预发门禁(见 scripts/gen_staging_nginx.py 的说明)。cookie 值在 staging-gate/token.map,只在预发机上
map $cookie_sz_staging_gate $sz_staging_gate_ok {
    default 0;
    include /etc/nginx/staging-gate/token.map;
}

server {
    listen 443 ssl;
    server_name _;
    access_log /var/log/nginx/access.log superz_masked;

    ssl_certificate     /etc/nginx/certs/staging/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/staging/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # 跳转一律写相对地址。缺省是绝对地址,端口按 nginx 自己监听的 443 算、于是省略 ——
    # 对外是 :8443(frp 转进来的),一跳就跳到了 443 上的生产站。本地实测踩到过
    absolute_redirect off;

    # 没带通行 cookie 的一律去 /__gate(server 级的 if 只做 set / return,这是 nginx 里安全的写法)
    set $sz_staging_block 1;
    if ($sz_staging_gate_ok = 1) {
        set $sz_staging_block 0;
    }
    if ($uri = /__gate) {
        set $sz_staging_block 0;
    }
    if ($sz_staging_block = 1) {
        return 302 /__gate;
    }

    location = /__gate {
        auth_basic "chaojizan staging";
        auth_basic_user_file /etc/nginx/staging-gate/htpasswd;
        # Set-Cookie 那一行在预发机上(带 cookie 值)。add_header 不加 always:只在 200 时发,输错密码的 401 不发
        include /etc/nginx/staging-gate/set-cookie.conf;
        add_header Cache-Control "no-store" always;
        default_type text/html;
        # 不能用 return(见文件头):静态页在 content 阶段,一定排在密码校验之后
        alias /etc/nginx/conf.d/%(page)s;
    }

    # ---- 以下照抄生产 superz.conf 的 locations-begin … locations-end ----
""" % {"page": OUT_GATE_PAGE}


def split(src: str) -> tuple[str, str]:
    """按三个标记切出 http 级配置和主站 location 段。标记缺了、重了、顺序不对都直接失败。"""
    lines = src.splitlines(keepends=True)
    at: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = MARK_RE.match(line)
        if not m:
            continue
        if m.group(1) in at:
            raise ValueError(f"标记 [staging] {m.group(1)} 出现了不止一次")
        at[m.group(1)] = i
    missing = [k for k in MARKS if k not in at]
    if missing:
        raise ValueError("superz.conf 里缺标记:" + "、".join(f"[staging] {k}" for k in missing))
    if not at["http-end"] < at["locations-begin"] < at["locations-end"]:
        raise ValueError("三个 [staging] 标记的顺序应当是 http-end → locations-begin → locations-end")
    http = "".join(lines[:at["http-end"]])
    locations = "".join(lines[at["locations-begin"] + 1:at["locations-end"]])
    if re.search(r"^\s*server\s*\{", http, re.M):
        raise ValueError("[staging] http-end 要放在第一个 server 块之前")
    for bad in ("server_name", "ssl_certificate", "listen "):
        if re.search(rf"^\s*{bad}", locations, re.M):
            raise ValueError(f"locations 段里出现了 {bad.strip()}:标记放错了位置?")
    return http, locations


def render(src: str) -> str:
    http, locations = split(src)
    locations, n = re.subn(r"proxy_set_header(\s+)Host(\s+)\$host;",
                           r"proxy_set_header\1Host\2$http_host;", locations)
    if n == 0:
        raise ValueError("locations 段里没找到 `proxy_set_header Host $host;`:api 反代的写法变了,生成器要跟着改")
    return ("# 自动生成,别手改 —— scripts/gen_staging_nginx.py 从 deploy/nginx/conf.d/superz.conf 生成"
            "(预发环境,docs/STAGING.md)\n\n" + http + "\n" + SERVER_HEAD + locations + "}\n")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    src, out = Path(argv[1]), Path(argv[2])
    try:
        conf = render(src.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    (out / OUT_CONF).write_text(conf, encoding="utf-8")
    (out / OUT_GATE_PAGE).write_text(GATE_PAGE, encoding="utf-8")
    print(f"✓ {out / OUT_CONF}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
