"""上传隐私边界(#124/#125)。

这条守的是一件在改造前**实测会失守**的事:

    匿名 GET /uploads/01160d64....png → 200

菜品图和骑手身份证曾经落在同一个目录、同一套无鉴权公开 URL 上。
UUID4 不可枚举所以扫不到,但 URL 一旦泄露(截图/日志/Referer/转发)
就是永久可访问且无法撤销 —— 对证件照这个级别不够,
也和给骑手的隐私政策("只收提供服务所必需的最少信息")对不上。

所以这里的断言不是"功能能用",是**该看不到的人真的看不到**。
"""
import asyncio
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import ADMIN, CUSTOMER, MERCHANT, RIDER, BASE, call, login  # noqa: E402

# 一小段合法 JPEG 头,够服务端认扩展名
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 256


def upload(token: str, purpose: str | None, name: str = "t.jpg",
           content: bytes | None = None):
    """multipart 上传。purpose=None 模拟老客户端(不带这个字段)。

    content 用来传**非图片内容**:格式判定必须看魔数,不能看文件名。
    """
    boundary = "----superz-e2e"
    parts = []
    if purpose is not None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"'
            f'\r\n\r\n{purpose}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file";'
        f' filename="{name}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
        + (JPEG if content is None else content) + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(BASE + "/upload", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            import json
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None


def fetch(path: str, token: str | None = None) -> int:
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main() -> None:
    r_token = login(RIDER)
    c_token = login(CUSTOMER)
    m_token = login(MERCHANT)
    a_token = login(ADMIN)

    # --- purpose 必填,且不给默认值 ---
    code, _ = upload(r_token, None)
    assert code == 422, f"不带 purpose 竟然被接受了({code})"
    print("✓ 不带 purpose 的上传被拒(422)——不给默认值是有意的")

    code, _ = upload(r_token, "whatever")
    assert code == 422, code
    print("✓ 未知 purpose 被拒(422)")

    # --- 公开类:匿名可取 ---
    code, pub = upload(m_token, "dish")
    assert code == 200, code
    assert pub["url"].startswith("/img/"), pub
    assert pub["private"] is False, pub
    assert fetch(pub["url"]) == 200, "公开图匿名取不到"
    print(f"✓ 菜品图 → {pub['url']},匿名可取")

    # --- 私密类:身份证 ---
    code, priv = upload(r_token, "id_card")
    assert code == 200, code
    assert priv["url"].startswith("/files/"), priv
    assert priv["private"] is True, priv
    print(f"✓ 身份证 → {priv['url']}")

    assert fetch(priv["url"]) == 401, "身份证匿名可取 —— 这正是要修的洞"
    print("✓ 匿名取身份证:401")

    assert fetch(priv["url"], c_token) == 403, "别的用户能取到别人的身份证"
    print("✓ 他人取身份证:403(不是 404 —— 权限不足就说权限不足)")

    assert fetch(priv["url"], a_token) == 200, "管理员取不到,没法审核"
    print("✓ 管理员取身份证:200(审核要看)")

    # 本人:key 里编着上传者(u{id}-),**未绑定档案时上传者本人就能取** ——
    # 入驻/认证表单在「上传成功」到「提交落库」之间文件不被任何行引用,
    # 只按归属判权会让上传者自己都看不了刚传的证照(缩略图破图、OCR 失效)。
    # 归属判权仍在:其他人在绑定前后都取不到(下方继续断言)
    assert fetch(priv["url"], r_token) == 200, "上传者本人应可读自己刚传的文件"
    print("✓ 上传后未绑定档案:上传者本人可读(表单回显),他人仍取不到")

    # 直连库绑定:演示骑手已过审,/riders/profile 会 409(已认证不让改),
    # 而这条用例要验的是判权不是那条状态机
    def bind(url: str) -> None:
        # 每次现开一个引擎再销毁:asyncio.run 每调一次就换一个事件循环,
        # 复用 app.db 的全局引擎会撞上"连接属于另一个 loop"
        async def _run() -> None:
            from sqlalchemy import text as sql
            from sqlalchemy.ext.asyncio import create_async_engine
            from app.config import settings
            engine = create_async_engine(settings.database_url)
            try:
                async with engine.begin() as conn:
                    await conn.execute(sql(
                        "UPDATE rider_profiles SET id_card_photo_url = :u "
                        "WHERE rider_id = ("
                        "  SELECT id FROM users WHERE phone = :p)"),
                        {"u": url, "p": RIDER})
            finally:
                await engine.dispose()

        asyncio.run(_run())

    original = call("GET", "/riders/profile", token=r_token).get(
        "id_card_photo_url", "")
    bind(priv["url"])
    assert fetch(priv["url"], r_token) == 200, "绑定到自己档案后本人仍取不到"
    print("✓ 绑定到本人档案后:本人 200")

    # 换个人再确认一次:归属变了,别人仍然取不到
    assert fetch(priv["url"], c_token) == 403
    assert fetch(priv["url"], m_token) == 403
    print("✓ 绑定后其他角色(顾客/商家)依旧 403")

    # --- 私密文件绝不能被缓存 ---
    req = urllib.request.Request(BASE + priv["url"])
    req.add_header("Authorization", f"Bearer {a_token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        cc = r.headers.get("Cache-Control", "")
    assert "no-store" in cc, f"私密文件的 Cache-Control 是 {cc!r}"
    print(f"✓ 私密文件 Cache-Control: {cc}(缓存过一次,撤权就形同虚设)")

    # --- 老 URL 兼容:公开的照旧,私密的要鉴权 ---
    from app.services import storage
    legacy_name = "e2e_legacy_idcard.jpg"
    storage.backend().put(JPEG, f"legacy/{legacy_name}", private=True)
    bind(f"/uploads/{legacy_name}")
    assert fetch(f"/uploads/{legacy_name}") == 401, \
        "迁移进私密存储的老 URL 仍能匿名访问 —— 迁移等于白做"
    assert fetch(f"/uploads/{legacy_name}", c_token) == 403
    assert fetch(f"/uploads/{legacy_name}", r_token) == 200
    print("✓ 老 URL(/uploads/…)命中私密存储时同样要鉴权:"
          "匿名 401 / 他人 403 / 本人 200")

    bind(original)   # 还原,不给别的用例留脏数据

    # ---------- 格式判定看魔数,不看文件名 ----------
    #
    # 老写法是"魔数认不出 → 回退到文件名后缀"。而文件名是攻击者可控的,
    # 白名单那三种(jpg/png/webp)加 heic 全都嗅得出来 ——
    # 这条回退**只可能放进非图片**:内容是 HTML 的 evil.jpg 就这么进公开桶。
    for label, blob in (
        ("HTML", b"<html><script>alert(1)</script></html>" + b"x" * 300),
        ("SVG", b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>"),
        ("ZIP", b"PK\x03\x04" + b"\x00" * 300),
    ):
        code, _ = upload(m_token, "dish", name="evil.jpg", content=blob)
        assert code == 422, (
            f"内容是 {label} 但叫 evil.jpg 的文件被收下了(HTTP {code})——"
            f"格式判定又回退到文件名了")
    print("✓ 内容不是图片就拒绝,叫什么名字都没用(HTML / SVG / ZIP 各试一次)")

    # 真图片照常收(别把上面那条改成"一律拒绝")
    code, _ = upload(m_token, "dish")
    assert code == 200, f"真 JPEG 反而被拒了:{code}"
    print("✓ 真图片照常收")

    print(f"\n全部通过:上传隐私边界({storage.backend().name} 后端)")


if __name__ == "__main__":
    main()
