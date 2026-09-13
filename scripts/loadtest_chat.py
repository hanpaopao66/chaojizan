"""消息压测(DEV-PROMPTS-40 #372):同时在线 N 条 /ws/v2 连接 + 一股持续的发消息流量,旁路探针量延迟。

**为什么这样测**(见仓库的压测经验:压测端自己会先堵、会说谎):

- 压测端开**多个进程**,每个进程只管一批连接 —— 单进程 asyncio 开到几百并发时,量到的是压测端自己的排队;
- 延迟**不从压测流量里算**,由一个独立进程的旁路探针串行地打:发一条消息(p95 目标 < 150ms)、
  拉会话列表(< 200ms)、拉视频推荐(< 200ms),以及「发出去 → 对方另一条连接收到」的投递延迟;
- 报数字的同时报背景:实际连上多少条、失败多少、每秒真实发出多少条、库里多少会话 / 消息 / 视频。

用法(对着开发或预发实例;账号靠开发环境的短信验证码自动注册,生产环境用 --tokens 传现成的):

    cd server && ../server/.venv/bin/python ../scripts/loadtest_chat.py \\
        --api http://127.0.0.1:8031 --conns 2000 --accounts 200 --rate 20 --duration 60

压 2000 条连接时两边的文件描述符都要够:起服务和跑脚本前 `ulimit -n 8192`。
"""
import argparse
import asyncio
import json
import multiprocessing as mp
import os
import random
import statistics
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))


# ---------------------------------------------------------------- HTTP(同步,准备阶段和探针用)

def http(api: str, method: str, path: str, token: str | None = None, body=None, timeout=15):
    req = urllib.request.Request(api + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def make_accounts(api: str, n: int) -> list[str]:
    """开发环境:短信验证码直接回在响应里(dev_code),注册 n 个新号。"""
    os.environ["SUPERZ_API"] = api
    from tests.miniapp_util import customer
    out = []
    for i in range(n):
        token, _ = customer("137")
        out.append(token)
        if (i + 1) % 50 == 0:
            print(f"  已注册 {i + 1} 个账号", flush=True)
    return out


def pair_chats(api: str, tokens: list[str]) -> list[tuple[str, int]]:
    """两两建私聊:(发的人的 token, 会话 id)。"""
    pairs = []
    for i in range(0, len(tokens) - 1, 2):
        me_b = http(api, "GET", "/social/v1/me", tokens[i + 1])
        chat = http(api, "POST", "/chat/v1/chats/private", tokens[i], {"user_id": me_b["id"]})
        pairs.append((tokens[i], chat["id"]))
        pairs.append((tokens[i + 1], chat["id"]))
    return pairs


# ---------------------------------------------------------------- 连接进程

async def _hold(api: str, tokens: list[str], seconds: float, q) -> None:
    from websockets.asyncio.client import connect

    ws_base = api.replace("https://", "wss://").replace("http://", "ws://")
    frames = 0
    ok = 0
    errors: list[str] = []

    async def one(token: str):
        nonlocal frames, ok
        try:
            async with connect(f"{ws_base}/ws/v2", open_timeout=20, ping_interval=None,
                               max_queue=None) as ws:
                await ws.send(json.dumps({"t": "auth", "token": token, "device": "load",
                                          "foreground": True}))
                ok += 1
                end = time.monotonic() + seconds
                next_ping = time.monotonic() + 25
                while time.monotonic() < end:
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=min(5, max(0.1, end - time.monotonic())))
                        frames += 1
                    except asyncio.TimeoutError:
                        pass
                    if time.monotonic() >= next_ping:
                        await ws.send(json.dumps({"t": "ping"}))
                        next_ping += 25
        except Exception as e:  # 连不上、被断:记下来,不影响别的连接
            errors.append(type(e).__name__)

    tasks = []
    for t in tokens:
        tasks.append(asyncio.create_task(one(t)))
        await asyncio.sleep(0.005)          # 别在同一毫秒里全涌过去(那是在压 accept 队列,不是在压服务)
    await asyncio.sleep(3)
    q.put(("connected", ok))
    await asyncio.gather(*tasks)
    q.put(("conn_done", {"frames": frames, "errors": errors}))


def conn_worker(api: str, tokens: list[str], seconds: float, q) -> None:
    asyncio.run(_hold(api, tokens, seconds, q))


# ---------------------------------------------------------------- 发消息进程

def sender_worker(api: str, pairs: list[tuple[str, int]], rate: float, seconds: float, q) -> None:
    """按固定速率发(开环):每隔 1/rate 秒发一条,不等上一条回来 —— 用线程池,免得被慢请求拖住节奏。"""
    from concurrent.futures import ThreadPoolExecutor

    sent = errors = 0

    def one(token: str, chat_id: int) -> bool:
        try:
            http(api, "POST", f"/chat/v1/chats/{chat_id}/messages", token,
                 {"random_id": str(random.getrandbits(62)), "kind": "text", "text": "压测消息"})
            return True
        except Exception:
            return False

    end = time.monotonic() + seconds
    interval = 1.0 / rate
    futs = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        t = time.monotonic()
        while t < end:
            token, chat_id = random.choice(pairs)
            futs.append(pool.submit(one, token, chat_id))
            t += interval
            time.sleep(max(0.0, t - time.monotonic()))
        for f in futs:
            if f.result():
                sent += 1
            else:
                errors += 1
    q.put(("sender", {"sent": sent, "errors": errors}))


# ---------------------------------------------------------------- 旁路探针

def probe_worker(api: str, a: str, b: str, chat_id: int, seconds: float, q) -> None:
    """一个进程、串行、自己的账号:量的是「一个普通用户这时候的体验」,不掺压测端的排队。"""
    from websockets.sync.client import connect

    ws_base = api.replace("https://", "wss://").replace("http://", "ws://")
    lat = {"send": [], "dialogs": [], "feed": [], "deliver": []}
    ws = connect(f"{ws_base}/ws/v2", open_timeout=20)
    ws.send(json.dumps({"t": "auth", "token": b, "device": "probe", "foreground": True}))
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        rid = str(random.getrandbits(62))
        t0 = time.perf_counter()
        try:
            http(api, "POST", f"/chat/v1/chats/{chat_id}/messages", a,
                 {"random_id": rid, "kind": "text", "text": "探针"})
        except Exception as e:
            lat.setdefault("fail", []).append(type(e).__name__)
            time.sleep(1.1)
            continue
        lat["send"].append((time.perf_counter() - t0) * 1000)
        # 投递:B 的连接上等到这条 msg 事件
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline:
            try:
                f = json.loads(ws.recv(timeout=max(0.05, deadline - time.perf_counter())))
            except TimeoutError:
                break
            if f.get("t") == "ev" and f.get("type") == "msg" and str((f.get("data") or {}).get("random_id")) == rid:
                lat["deliver"].append((time.perf_counter() - t0) * 1000)
                break
        for key, path, token in (("dialogs", "/chat/v1/dialogs", a), ("feed", "/video/v1/feed/recommend?page=0", a)):
            t0 = time.perf_counter()
            try:
                http(api, "GET", path, token)
                lat[key].append((time.perf_counter() - t0) * 1000)
            except Exception:
                pass
        # 一秒一轮:发消息的限流是每人每分钟 60 条(§5.7),探针自己别撞上
        time.sleep(1.1)
    ws.close()
    q.put(("probe", lat))


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("SUPERZ_API", "http://127.0.0.1:8013"))
    ap.add_argument("--conns", type=int, default=2000, help="同时在线的 /ws/v2 连接数")
    ap.add_argument("--accounts", type=int, default=200, help="账号数(连接平均摊到这些账号上,一号多设备)")
    ap.add_argument("--rate", type=float, default=20, help="背景流量:每秒发几条消息")
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--procs", type=int, default=8, help="连接进程数")
    ap.add_argument("--tokens", help="现成的 token 列表(JSON 文件);不给就在开发环境自动注册")
    args = ap.parse_args()

    print(f"== 准备:{args.accounts} 个账号 ==", flush=True)
    tokens = json.load(open(args.tokens)) if args.tokens else make_accounts(args.api, args.accounts + 2)
    probe_a, probe_b, tokens = tokens[0], tokens[1], tokens[2:]
    pairs = pair_chats(args.api, tokens)
    me_b = http(args.api, "GET", "/social/v1/me", probe_b)
    probe_chat = http(args.api, "POST", "/chat/v1/chats/private", probe_a, {"user_id": me_b["id"]})["id"]

    conn_tokens = [tokens[i % len(tokens)] for i in range(args.conns)]
    chunks = [conn_tokens[i::args.procs] for i in range(args.procs)]
    q = mp.Queue()
    hold = args.duration + 30
    print(f"== 起 {args.conns} 条连接({args.procs} 个进程),保持 {hold:.0f}s ==", flush=True)
    procs = [mp.Process(target=conn_worker, args=(args.api, c, hold, q)) for c in chunks]
    for p in procs:
        p.start()
    connected = 0
    for _ in procs:            # 每个连接进程开完一批先报一次「连上几条」
        kind, n = q.get()
        assert kind == "connected", kind
        connected += n
    print(f"   连上 {connected} 条,开始发消息 {args.rate}/s 并启动探针", flush=True)
    sender = mp.Process(target=sender_worker, args=(args.api, pairs, args.rate, args.duration, q))
    probe = mp.Process(target=probe_worker, args=(args.api, probe_a, probe_b, probe_chat, args.duration, q))
    sender.start()
    probe.start()
    got: dict = {}
    frames, errs = 0, []
    for _ in range(len(procs) + 2):
        kind, v = q.get()
        if kind == "conn_done":
            frames += v["frames"]
            errs += v["errors"]
        else:
            got[kind] = v
    for p in (*procs, sender, probe):
        p.join()
    probe_out = got.get("probe", {})
    snd = got.get("sender", {"sent": 0, "errors": 0})

    print("\n== 结果 ==")
    print(f"连接:目标 {args.conns},连上 {connected},失败 / 中途断开 {len(errs)}"
          + (f"({', '.join(sorted(set(errs)))})" if errs else ""))
    print(f"背景流量:{snd['sent']} 条成功 / {snd['errors']} 条失败,"
          f"平均 {snd['sent'] / args.duration:.1f} 条/秒;连接进程共收到 {frames} 帧")
    targets = {"send": 150, "dialogs": 200, "feed": 200, "deliver": None}
    for key, name in (("send", "发消息"), ("deliver", "发出 → 对方收到"), ("dialogs", "会话列表"), ("feed", "视频推荐")):
        xs = probe_out.get(key, [])
        p50, p95, p99 = pct(xs, .5), pct(xs, .95), pct(xs, .99)
        goal = targets[key]
        verdict = "" if goal is None else ("  达标" if p95 < goal else f"  **超标**(目标 p95 < {goal}ms)")
        print(f"{name:10s} n={len(xs):4d}  p50 {p50:7.1f}ms  p95 {p95:7.1f}ms  p99 {p99:7.1f}ms{verdict}")
    if probe_out.get("send"):
        print(f"(探针样本均值:发消息 {statistics.mean(probe_out['send']):.1f}ms)")
    if probe_out.get("fail"):
        print(f"探针失败 {len(probe_out['fail'])} 次:{sorted(set(probe_out['fail']))}")


if __name__ == "__main__":
    main()
