"""公开账本 + 见证节点验证:哈希链复算 / 心跳注册 / 篡改示警 / 真跑见证脚本。

在 server/ 目录下运行:python -m tests.e2e_p4_witness
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from tests.util import BASE, call

GENESIS = "0" * 64


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---- 哈希链:独立复算每个锚点(与见证节点同一套算法) ----
anchors = call("GET", "/ledger/anchors")
prev = GENESIS
for a in anchors:
    detail = call("GET", f"/ledger/days/{a['day']}")
    payload_hash = sha256(canonical(detail["payload"]))
    assert payload_hash == a["payload_hash"], f"{a['day']} payload 哈希不符"
    chain = sha256(prev + payload_hash)
    assert chain == a["chain_hash"], f"{a['day']} 链哈希不符"
    prev = chain
print(f"✓ 哈希链独立复算通过({len(anchors)} 个锚点,从创世块连续到昨天)")

# ---- 隐私:公开账本不含任何个人信息字段 ----
def all_keys(obj, acc):
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            all_keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            all_keys(v, acc)
    return acc


if anchors:
    payload = call("GET", f"/ledger/days/{anchors[-1]['day']}")["payload"]
    keys = all_keys(payload, set())
    for banned in ("phone", "address", "name", "customer_id", "merchant_id",
                   "rider_id", "lat", "lng", "order_no", "purchase_no"):
        assert banned not in keys, f"公开账本泄露字段:{banned}"
    for row in payload["merchant_rows"]:
        assert row["net"] == row["food"] - row["commission"]
    print("✓ 账本匿名化(无个人信息/身份字段),商家净额恒等式逐行成立")

# ---- 心跳注册与去重 ----
node_id = uuid.uuid4().hex
my_name = f"e2e测试节点-{node_id[:6]}"
r = call("POST", "/nodes/heartbeat", body={
    "node_id": node_id, "name": my_name, "region": "测试环境",
    "version": "0.0.0", "ok": True})
assert r["registered"] and not r["divergent"]
call("POST", "/nodes/heartbeat", body={
    "node_id": node_id, "name": my_name, "region": "测试环境",
    "version": "0.0.0", "ok": True})
s = call("GET", "/nodes/summary")
mine = [n for n in s["nodes"] if n["name"] == my_name]
assert len(mine) == 1 and mine[0]["heartbeats"] >= 2 and mine[0]["online"]
assert s["online"] >= 1
print("✓ 心跳即注册,重复心跳按 node_id 去重计数")

err = call("POST", "/nodes/heartbeat", body={
    "node_id": "短", "ok": True}, expect_error=True)
assert err["_error"] == 422
print("✓ 非法 node_id 被拒")

# ---- 篡改示警:节点报告与平台记录不一致 → divergent 公开可见 ----
if anchors:
    latest = anchors[-1]
    r = call("POST", "/nodes/heartbeat", body={
        "node_id": node_id, "name": my_name, "region": "测试环境",
        "verified_day": latest["day"], "chain_hash": "f" * 64, "ok": True})
    assert r["divergent"], "链哈希不符必须标记 divergent"
    s = call("GET", "/nodes/summary")
    assert s["divergent"] >= 1
    # 恢复:上报正确哈希后示警解除(不给后续测试和演示留红灯)
    r = call("POST", "/nodes/heartbeat", body={
        "node_id": node_id, "name": my_name, "region": "测试环境",
        "verified_day": latest["day"], "chain_hash": latest["chain_hash"],
        "ok": True})
    assert not r["divergent"]
    print("✓ 篡改示警:节点报告不一致 → 公开标记;复核一致后解除")

# ---- 真跑一遍见证节点脚本(--once):校验全链 + 心跳上报 ----
script = Path(__file__).resolve().parent.parent.parent / "witness" / "superz_witness.py"
with tempfile.TemporaryDirectory() as tmp:
    proc = subprocess.run(
        [sys.executable, str(script), "--api", BASE, "--once",
         "--state", f"{tmp}/state.json"],
        capture_output=True, text=True, timeout=120,
        env={"WITNESS_NAME": f"e2e见证脚本-{node_id[:6]}", "WITNESS_REGION": "CI",
             "PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0, f"见证脚本判定账本不可信:\n{proc.stdout}{proc.stderr}"
    assert "✓ 账本可信" in proc.stdout
    state = json.loads(Path(f"{tmp}/state.json").read_text())
    assert len(state["seen"]) == len(anchors), "见证脚本应留存全部锚点"
print("✓ 见证脚本全链校验通过并留存锚点(与社区节点运行方式完全一致)")

time.sleep(0.3)
s = call("GET", "/nodes/summary")
assert any(n["name"] == f"e2e见证脚本-{node_id[:6]}" for n in s["nodes"])
print("✓ 见证脚本心跳已出现在 /nodes 节点列表")

# ---- 公开运营总览(大屏/官网/App 账目透明页共用) ----
ov = call("GET", "/stats/overview")
assert ov["today"]["orders"] >= 0 and ov["principles"]["commission_rate"] == 0.05
assert len(ov["trend"]) == min(30, len(anchors))
if anchors:
    assert ov["chain"]["latest_hash"] == anchors[-1]["chain_hash"]
    # 趋势数字与账本锚点 totals 同源(抽查最后一天)
    day_payload = call("GET", f"/ledger/days/{ov['trend'][-1]['day']}")["payload"]
    assert ov["trend"][-1]["rider_amount"] == day_payload["totals"]["rider_amount"]
print("✓ /stats/overview 与公开账本同源(大屏与官网的数据面)")

print("\n全部通过:公开账本哈希链 + 社区见证节点 ✓")
