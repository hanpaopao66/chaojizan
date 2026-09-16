"""论坛 e2e 的公共件(DEV-PROMPTS-41 #380):开号、发帖、上传配图、把帖子的时间往前挪。

测试素材全部现场生成(Pillow 画图),不带任何二进制文件进仓库。跑法同其它 e2e:

    . "$(bash scripts/e2e_iso.sh env 2)" && cd server && python -m tests.e2e_forum_posts
"""
import io
import uuid

from tests.chat_util import Person, person, sql
from tests.util import BASE, call
from tests.video_util import admin2_token, admin_token, clear_rate_limits, raw, set_flag


def png_bytes(w: int = 320, h: int = 240, color=(30, 120, 200)) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def upload_forum_image(p: Person, color=(30, 120, 200)) -> str:
    """公开图片用途 forum,走现有的 POST /uploads。返回 `/img/forum/u<我>-….png`。"""
    boundary = uuid.uuid4().hex
    data = png_bytes(color=color)
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nforum\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"a.png\"\r\nContent-Type: image/png\r\n\r\n",
    ]
    body = parts[0].encode() + parts[1].encode() + data + f"\r\n--{boundary}--\r\n".encode()
    status, _headers, raw_body = raw(p.token, "/upload", method="POST", data=body,
                                     headers={"Content-Type":
                                              f"multipart/form-data; boundary={boundary}"})
    assert status == 200, (status, raw_body[:200])
    import json
    return json.loads(raw_body)["url"]


def post(p: Person, text: str = "", *, expect_error: bool = False, **body) -> dict:
    """发帖。

    每次先清掉自家限流:发帖是每 10 秒 1 条(§5.10),用例里不该真等 —— 也不该让
    `expect_error` 的调用拿回一个 429,那会表现成「我等的是 422,来的是 429」。
    真正测限流的用例自己直接调 `p.post`,别走这里。
    """
    clear_rate_limits("forum_post", p.id)
    clear_rate_limits("forum_post_h", p.id)
    return p.post("/forum/v1/posts", {"text": text, **body}, expect_error=expect_error)


def act(p: Person, method: str, path: str, body: dict | None = None, **kw):
    """赞 / 转发 / 书签 / 投票:每人每秒 5 次(§5.10)。

    用例里一段连着点十几下,固定窗口一秒放 5 个,第 6 个就 429 —— 而 call() 撞上 429 会等
    窗口翻转(半分钟起)。每次先把桶清了:这里测的不是限流。
    """
    clear_rate_limits("forum_act", p.id)
    if method == "POST":
        return p.post(path, body, **kw)
    return p.delete(path, **kw)


def age_post(pid: str, hours: float) -> None:
    """把帖子的发帖时间往前挪(测时间衰减、72 小时窗口、编辑窗口用)。"""
    sql("UPDATE forum_posts SET created_at = now() - make_interval(secs => :s) WHERE pid = :p",
        {"s": hours * 3600, "p": pid})


def age_poll(pid: str, minutes: float) -> None:
    """把投票的结束时间挪到过去(测投票结束)。"""
    sql("UPDATE forum_polls SET ends_at = now() - make_interval(secs => :s) "
        "WHERE post_id = (SELECT id FROM forum_posts WHERE pid = :p)",
        {"s": minutes * 60, "p": pid})


def timeline_pids(out: dict) -> list[str]:
    return [it["post"]["pid"] for it in out["items"]]


__all__ = ["Person", "person", "sql", "call", "BASE", "admin_token", "admin2_token",
           "clear_rate_limits", "set_flag", "png_bytes", "upload_forum_image", "post", "act",
           "age_post", "age_poll", "timeline_pids"]
