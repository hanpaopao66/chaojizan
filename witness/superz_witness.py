#!/usr/bin/env python3
"""Super-Z 社区见证节点 —— 独立监督平台账本,一台旧电脑就能跑。

它做三件事:
  1. 拉取平台公开账本(匿名化流水,无任何个人信息),逐日复算哈希链;
  2. 校验三原则恒等式:商家佣金 ≤ 承诺上限、净额 = 应收 - 佣金、
     骑手配送费只进不冲、团购服务费 = 承诺费率(上限/费率内嵌在每日账本里,
     当前 5% / 2%;历史锚点按当天口径复算,降费率不影响历史校验);
  3. 把见过的锚点留存在本地 —— 平台若改写历史,你的节点立刻发现并公开示警。

运行(任选其一):
  python3 superz_witness.py                        # 默认连官方服务器
  docker run -d ghcr.io/super-z/witness            # 见 README
可选环境变量 / 参数:
  SUPERZ_API      平台地址(默认 https://chaojizan.cc)
  WITNESS_NAME    节点页上展示的名字(可留空)
  WITNESS_REGION  节点页上展示的地区(可留空)

零第三方依赖,只用 Python 标准库;源码不到 300 行,建议读一遍再运行——
见证的意义在于你不需要信任任何人,包括这个脚本的作者。
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

VERSION = "0.1.1"


def local_utc_offset() -> str:
    """本机 UTC 偏移(如 UTC+08:00)。仅用于 /nodes 世界地图粗定位,可用
    WITNESS_TZ 覆盖(IANA 名,如 Asia/Shanghai),设为空串则不上报。"""
    if "WITNESS_TZ" in os.environ:
        return os.environ["WITNESS_TZ"][:40]
    off = time.strftime("%z")  # 如 +0800;个别平台可能为空
    return f"UTC{off[:3]}:{off[3:]}" if len(off) == 5 else ""
HEARTBEAT_SECONDS = 300
MAX_DAYS_PER_CYCLE = 60      # 首次追赶历史时每轮最多校验的天数
GENESIS = "0" * 64


def canonical(obj) -> str:
    """与服务端 services/ledger.py 完全一致的规范化 JSON。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def http_json(method: str, url: str, body: dict | None = None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data, timeout=30) as resp:
        return json.loads(resp.read())


def verify_rows(payload: dict) -> list[str]:
    """三原则恒等式,逐行核。返回问题列表(空 = 通过)。"""
    problems = []
    rate_max = payload.get("commission_rate_max", 0.06)
    voucher_rate = payload.get("voucher_rate", 0.03)

    for r in payload.get("merchant_rows", []):
        food, fee, net = r["food"], r["commission"], r["net"]
        if net != food - fee:
            problems.append(f"商家行 {r['o']}: 净额 {net} != 应收 {food} - 佣金 {fee}")
        # 冲账行是入账行的镜像负数,金额取绝对值核比例(+1 分容忍取整)
        if abs(fee) > abs(food) * rate_max + 1:
            problems.append(f"商家行 {r['o']}: 佣金 {fee} 超过应收 {food} 的 {rate_max:.0%}")

    for r in payload.get("rider_rows", []):
        if r["kind"] != "earning" or r["amount"] < 0:
            problems.append(f"骑手行 {r['o']}: 配送费只进不冲的原则被打破 ({r['kind']}, {r['amount']})")

    for r in payload.get("voucher_rows", []):
        expect_fee = int(r["gross"] * voucher_rate)
        if r["fee"] != expect_fee or r["net"] != r["gross"] - r["fee"]:
            problems.append(f"团购行 {r['p']}: 服务费 {r['fee']} != {r['gross']}×{voucher_rate:.0%}")

    t = payload.get("totals", {})
    if t and t.get("rider_amount") != sum(r["amount"] for r in payload.get("rider_rows", [])):
        problems.append("骑手合计与逐行加总不一致")
    return problems


class Witness:
    def __init__(self, api: str, state_path: Path):
        self.api = api.rstrip("/")
        self.state_path = state_path
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        state = {"node_id": uuid.uuid4().hex,  # 本机自生成,不含任何身份信息
                 "seen": {}}                   # {day: chain_hash} 我见过的锚点
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state))
        return state

    def _save_state(self):
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False))

    def run_cycle(self) -> dict:
        """一轮完整见证:比对历史 → 校验新增 → 心跳上报。返回上报内容。"""
        seen: dict = self.state["seen"]
        anchors, after = [], ""
        while True:  # 服务端每页 400 天,翻页取全量
            page = http_json("GET", f"{self.api}/ledger/anchors?after={after}")
            anchors.extend(page)
            if len(page) < 400:
                break
            after = page[-1]["day"]

        # 第一道防线:我以前见过的锚点,现在必须一字不差 —— 变了就是改历史;
        # 老锚点整个消失同样是篡改
        current = {a["day"]: a["chain_hash"] for a in anchors}
        tampered = [f"锚点被改: {d}" for d, h in seen.items()
                    if d in current and current[d] != h]
        tampered += [f"锚点消失: {d}" for d in seen if d not in current]

        # 第二道防线:新增的日子逐日复算哈希链 + 三原则
        problems: list[str] = []
        prev_hash = GENESIS
        verified_day, verified_hash = "", ""
        fresh = 0
        for a in anchors:
            day = a["day"]
            if day in seen and not tampered:
                prev_hash = seen[day]
                verified_day, verified_hash = day, seen[day]
                continue
            detail = http_json("GET", f"{self.api}/ledger/days/{day}")
            payload_hash = sha256(canonical(detail["payload"]))
            chain_hash = sha256(prev_hash + payload_hash)
            if payload_hash != detail["payload_hash"] or chain_hash != a["chain_hash"]:
                problems.append(f"{day}: 哈希链复算不一致")
                break
            problems.extend(f"{day}: {p}" for p in verify_rows(detail["payload"]))
            seen[day] = chain_hash
            prev_hash = chain_hash
            verified_day, verified_hash = day, chain_hash
            fresh += 1
            if len(problems) > 20 or fresh >= MAX_DAYS_PER_CYCLE:
                break

        ok = not tampered and not problems
        self._save_state()

        message = "; ".join([*map(str, tampered), *problems])[:200]
        report = {
            "node_id": self.state["node_id"],
            "name": os.environ.get("WITNESS_NAME", "")[:30],
            "region": os.environ.get("WITNESS_REGION", "")[:30],
            "tz": local_utc_offset(),
            "version": VERSION,
            "verified_day": verified_day,
            "chain_hash": verified_hash,
            "ok": ok,
            "message": message,
        }
        try:
            http_json("POST", f"{self.api}/nodes/heartbeat", report)
        except urllib.error.URLError as exc:
            print(f"[warn] 心跳上报失败(不影响本地见证): {exc}", file=sys.stderr)
        status = "✓ 账本可信" if ok else f"✗ 发现问题: {message}"
        print(f"[{time.strftime('%H:%M:%S')}] 校验至 {verified_day or '(暂无锚点)'} {status}")
        return report


def main():
    parser = argparse.ArgumentParser(description="Super-Z 社区见证节点")
    parser.add_argument("--api", default=os.environ.get(
        "SUPERZ_API", "https://chaojizan.cc"))
    parser.add_argument("--state", default=os.environ.get(
        "WITNESS_STATE", str(Path.home() / ".superz-witness.json")))
    parser.add_argument("--once", action="store_true",
                        help="只跑一轮(测试/巡检用),默认常驻每 5 分钟一轮")
    args = parser.parse_args()

    witness = Witness(args.api, Path(args.state))
    print(f"Super-Z 见证节点 v{VERSION} | 平台: {args.api}")
    print(f"节点 ID: {witness.state['node_id'][:12]}…(本机生成,只用于去重计数)")
    while True:
        try:
            report = witness.run_cycle()
            if args.once:
                sys.exit(0 if report["ok"] else 1)
        except urllib.error.HTTPError as exc:
            hint = ("平台还未开通公开账本(服务端待更新),或 --api 地址不对"
                    if exc.code == 404 else str(exc))
            print(f"[warn] 本轮失败,{HEARTBEAT_SECONDS}s 后重试: {hint}",
                  file=sys.stderr)
            if args.once:
                sys.exit(2)
        except Exception as exc:
            print(f"[warn] 本轮失败,{HEARTBEAT_SECONDS}s 后重试: {exc}",
                  file=sys.stderr)
            if args.once:
                sys.exit(2)
        time.sleep(HEARTBEAT_SECONDS)


if __name__ == "__main__":
    main()
