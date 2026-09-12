"""消息 e2e 的公共件(DEV-PROMPTS-40):开号、实时连接、常用调用。

跑法同其它 e2e:先起服务,再 `SUPERZ_API=http://127.0.0.1:8013 python -m tests.e2e_chat_xxx`。
"""
import json
import queue
import random
import threading
import time

from tests.miniapp_util import customer, sql
from tests.util import BASE, call

WS_BASE = BASE.replace("https://", "wss://").replace("http://", "ws://")


class Person:
    def __init__(self, token: str, phone: str):
        self.token = token
        self.phone = phone
        me = call("GET", "/social/v1/me", token)
        self.id = me["id"]
        self.name = me["name"]

    def get(self, path, **kw):
        return call("GET", path, self.token, **kw)

    def post(self, path, body=None, **kw):
        return call("POST", path, self.token, body if body is not None else {}, **kw)

    def patch(self, path, body=None, **kw):
        return call("PATCH", path, self.token, body or {}, **kw)

    def put(self, path, body=None, **kw):
        return call("PUT", path, self.token, body or {}, **kw)

    def delete(self, path, **kw):
        return call("DELETE", path, self.token, **kw)

    def private_with(self, other: "Person") -> dict:
        return self.post("/chat/v1/chats/private", {"user_id": other.id})

    def send(self, chat_id: int, text: str = "", *, expect_error: bool = False,
             **extra) -> dict:
        body = {"random_id": str(random.getrandbits(62)), "kind": extra.pop("kind", "text"),
                "text": text, **extra}
        return self.post(f"/chat/v1/chats/{chat_id}/messages", body, expect_error=expect_error)


def person(prefix: str = "139") -> Person:
    token, phone = customer(prefix)
    return Person(token, phone)


def set_username(p: Person, base: str) -> str:
    name = f"{base}{random.randint(10000, 99999)}"
    p.put("/social/v1/me/username", {"username": name})
    return name


class WS:
    """/ws/v2 的同步测试客户端:后台线程收帧进队列,wait_for 按条件等。"""

    def __init__(self, token: str | None, *, auth: bool = True, foreground: bool = True):
        from websockets.sync.client import connect

        self.frames: "queue.Queue[dict]" = queue.Queue()
        self.seen: list[dict] = []
        self.closed_code = None
        self.conn = connect(f"{WS_BASE}/ws/v2", open_timeout=5)
        if auth:
            self.conn.send(json.dumps({"t": "auth", "token": token, "device": "e2e",
                                       "foreground": foreground}))
        self._t = threading.Thread(target=self._reader, daemon=True)
        self._t.start()

    def _reader(self):
        try:
            for raw in self.conn:
                try:
                    self.frames.put(json.loads(raw))
                except ValueError:
                    pass
        except Exception:
            pass
        finally:
            try:
                self.closed_code = self.conn.close_code
            except Exception:
                pass

    def send(self, frame: dict):
        self.conn.send(json.dumps(frame))

    def wait_for(self, pred, timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        for f in self.seen:
            if pred(f):
                self.seen.remove(f)
                return f
        while time.time() < deadline:
            try:
                f = self.frames.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            if pred(f):
                return f
            self.seen.append(f)
        raise AssertionError(f"{timeout}s 内没等到期望的帧;收到过:{[x.get('type') or x.get('t') for x in self.seen][-20:]}")

    def drain(self, secs: float = 0.3) -> list[dict]:
        out = []
        deadline = time.time() + secs
        while time.time() < deadline:
            try:
                out.append(self.frames.get(timeout=0.05))
            except queue.Empty:
                pass
        self.seen.extend(out)
        return out

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def ev(type_: str, chat_id: int | None = None):
    return lambda f: f.get("t") == "ev" and f.get("type") == type_ and (
        chat_id is None or f.get("chat_id") == chat_id)


def uev(type_: str):
    return lambda f: f.get("t") == "uev" and f.get("type") == type_


__all__ = ["Person", "person", "set_username", "WS", "ev", "uev", "sql", "call"]
