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

VERSION = "0.1.2"


def local_utc_offset() -> str:
    """本机 UTC 偏移(如 UTC+08:00)。仅用于 /nodes 世界地图粗定位,可用
    WITNESS_TZ 覆盖(IANA 名,如 Asia/Shanghai),设为空串则不上报。"""
    if "WITNESS_TZ" in os.environ:
        return os.environ["WITNESS_TZ"][:40]
    off = time.strftime("%z")  # 如 +0800;个别平台可能为空
    return f"UTC{off[:3]}:{off[3:]}" if len(off) == 5 else ""
HEARTBEAT_SECONDS = 300
#: 常驻模式下每轮最多校验的天数 —— 纯粹是首次冷启动时的礼貌上限:
#: 三年的链就是一千多次串行请求,不该在启动那一瞬间全打给服务器。
#:
#: **它只是断点,不是终点。** 校验过的每一天都落在本地 state 的 `seen` 里,
#: 下一轮直接跳过已见的日子接着往下走,五分钟一轮,追上只是时间问题。
#: 所以常驻模式永远追得上链尾,把这个数调大调小都只影响追赶速度。
#:
#: **但 `--once` 不能用它。** 一次性巡检只跑一轮,套上这个上限就成了
#: "验了前 60 天、剩下的没看过、然后打印账本可信" —— 见证节点是拿来
#: 证伪的,一句没验到链尾的"可信"比不验更糟。所以 `--once` 传 max_days=None,
#: 语义是"验到追上链尾为止"(见 run_cycle 的 max_days 参数)。
MAX_DAYS_PER_CYCLE = 60
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

    stay_rate = payload.get("stay_rate", 0.05)
    for r in payload.get("stay_rows", []):
        gross, fee, net = r["gross"], r["fee"], r["net"]
        if r.get("kind") == "settle":
            # 离店结算:净额恒等 + 佣金不超 5%(+1 分容忍取整)
            if net != gross - fee:
                problems.append(f"住宿行 {r['s']}: 净额 {net} != 房费 {gross} - 佣金 {fee}")
            if fee > gross * stay_rate + 1:
                problems.append(f"住宿行 {r['s']}: 佣金 {fee} 超过房费 {gross} 的 {stay_rate:.0%}")
        elif r.get("kind") == "penalty":
            # 到店无房违约金:商家负行赔给用户,平台分文不取;赔付不超房费
            if fee != 0 or not (-gross <= net < 0):
                problems.append(f"住宿行 {r['s']}: 违约金行越界(fee={fee}, net={net})")
        else:
            # 取消扣款/未入住:平台分文不取,商家所得不超过房费
            if fee != 0:
                problems.append(f"住宿行 {r['s']}: 取消/未入住不应产生佣金({fee})")
            if not (0 <= net <= gross):
                problems.append(f"住宿行 {r['s']}: 扣款 {net} 超出房费 {gross}")

    t = payload.get("totals", {})
    if t and t.get("rider_amount") != sum(r["amount"] for r in payload.get("rider_rows", [])):
        problems.append("骑手合计与逐行加总不一致")
    if t and "stay_fee" in t and t.get("stay_fee") != sum(
            r["fee"] for r in payload.get("stay_rows", [])):
        problems.append("住宿服务费合计与逐行加总不一致")
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

    def run_cycle(self, max_days: int | None = MAX_DAYS_PER_CYCLE) -> dict:
        """一轮完整见证:比对历史 → 校验新增 → 心跳上报。

        `max_days` 是本轮最多校验多少个**新**日子,None = 不限(验到链尾)。
        没验完的日子不会丢:已验的都记在 `seen` 里,下一轮从断点接着走。
        返回上报内容,外加一个 `caught_up`(是否已经验到链尾,不上报给服务端)。
        """
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
            if len(problems) > 20 or (max_days is not None and fresh >= max_days):
                break

        # 还差几天追上链尾。判据是"锚点里还有没进过 seen 的日子",
        # 而不是"循环有没有 break" —— 正好在最后一天撞上限也算追上了
        behind = sum(1 for a in anchors if a["day"] not in seen)
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
        # 没追上链尾就别说"账本可信" —— 那句话的范围只到 verified_day 为止
        if not ok:
            status = f"✗ 发现问题: {message}"
        elif behind:
            status = f"✓ 已验部分无异常,还差 {behind} 天追上链尾(下一轮接着验)"
        else:
            status = "✓ 账本可信(已验到链尾)"
        print(f"[{time.strftime('%H:%M:%S')}] 校验至 {verified_day or '(暂无锚点)'} {status}")
        return {**report, "caught_up": not behind}


def main():
    parser = argparse.ArgumentParser(description="Super-Z 社区见证节点")
    parser.add_argument("--api", default=os.environ.get(
        "SUPERZ_API", "https://chaojizan.cc"))
    parser.add_argument("--state", default=os.environ.get(
        "WITNESS_STATE", str(Path.home() / ".superz-witness.json")))
    parser.add_argument("--once", action="store_true",
                        help="一次性巡检:一口气验到链尾再退出(测试/CI/cron 用),"
                             "默认常驻每 5 分钟一轮、每轮最多补 "
                             f"{MAX_DAYS_PER_CYCLE} 天")
    args = parser.parse_args()

    witness = Witness(args.api, Path(args.state))
    print(f"Super-Z 见证节点 v{VERSION} | 平台: {args.api}")
    print(f"节点 ID: {witness.state['node_id'][:12]}…(本机生成,只用于去重计数)")
    while True:
        try:
            # --once 不设每轮上限:巡检退出码代表的是"整条链验过了",
            # 卡在 60 天上限的话,链一超过 60 天,退出码就永远只反映前 60 天
            report = witness.run_cycle(None if args.once else MAX_DAYS_PER_CYCLE)
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
