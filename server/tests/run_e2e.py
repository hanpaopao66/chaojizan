"""全量 e2e 回归:按 tests/e2e_suites.txt 的顺序一个个跑,各记退出码和耗时,最后汇总。

    python -m tests.run_e2e              # 全部(make test 就是这个)
    python -m tests.run_e2e --shard 2/4  # 分 4 组的第 2 组(CI 里 4 组并行,各自一个干净库)

**跑完再汇总,不在第一个失败处停。** 从前 make test 是一长串 `&&`,第一个红了后面全不跑,
一次只看得到一个问题;现在一次看全,退出码仍然是「有一个红就是 1」。

分组按耗时均衡,不是按个数平均切:几个真转码、真等超时的套件一个顶几十个。
WEIGHTS 是照 CI 的环境在本地跑一遍量出来的秒数,没列的按 DEFAULT_WEIGHT 算 ——
只用来分组,量得不准也只是各组不太均,不影响对错。加了新的慢套件,跑一次
`python -m tests.run_e2e --timings` 把输出里超过 6 秒的抄进来。
组内保持清单里的先后顺序;清单里写成「套件: 依赖」的,和依赖捆在同一组。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES_FILE = HERE / "e2e_suites.txt"

#: 慢套件的实测秒数(2026-09-13,CI 同款环境分 4 组、每组一个干净库在本地并行跑:SMS_RESEND_SECONDS=3、
#: CALL_RING_SECONDS=5、CALL_DROP_GRACE_SECONDS=3)。串着跑时库里数据越积越多,有的套件会慢几倍,
#: 那种数不能拿来分组
WEIGHTS = {
    "e2e_media": 49, "e2e_bots": 43, "e2e_true_prep": 39, "e2e_group_cart_options": 36,
    "e2e_transparency": 34, "e2e_channels_flag": 33, "e2e_privacy_phone": 32, "e2e_chat_groups": 32,
    "e2e_pickup_handover": 29, "e2e_refund_bounds": 28, "e2e_weather_shutdown": 27, "e2e_grab_radius": 27,
    "e2e_wait_comp_audit": 27, "e2e_chat": 27, "e2e_authz_regression": 26, "e2e_auth_sms": 24,
    "e2e_screen": 23, "e2e_chat_private": 20, "e2e_calls": 15, "e2e_video_upload": 13, "e2e_video_feed": 12,
    "e2e_social_moderation": 11, "e2e_queue": 11, "e2e_chat_scheduled": 9, "e2e_risk": 8,
    "e2e_refund_order": 7, "e2e_account_delete": 7, "e2e_agent_scopes": 15,
    "e2e_badges": 8,
    "e2e_mcp_server": 20,
    # 音乐(#378):每首歌都要现场 ffmpeg 生成 + 转两档 AAC(loudnorm 要过一遍整首),
    # 所以比同规模的套件慢不少
    "e2e_music_studio": 70, "e2e_music_review": 95, "e2e_music_social": 45,
    "e2e_music_listen": 40,
}
DEFAULT_WEIGHT = 2.6


def load_deps() -> dict[str, list[str]]:
    """清单里每个套件 → 它要先跑的套件(「套件: 依赖1 依赖2」那种行;没写就是空)"""
    deps = {}
    for line in SUITES_FILE.read_text(encoding="utf-8").splitlines():
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        name, _, rest = body.partition(":")
        deps[name.strip()] = rest.split()
    return deps


def load_suites() -> list[str]:
    return list(load_deps())


def clusters(suites: list[str], deps: dict[str, list[str]]) -> list[list[str]]:
    """有依赖关系的套件并成一团(并查集),一团整个进同一组"""
    parent = {s: s for s in suites}

    def root(s):
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    for s in suites:
        for d in deps.get(s, []):
            parent[root(s)] = root(d)
    out = {}
    for s in suites:
        out.setdefault(root(s), []).append(s)
    return list(out.values())


def shard_of(suites: list[str], k: int, n: int, deps: dict[str, list[str]] | None = None) -> list[str]:
    """第 k 组(从 1 数)。有依赖的先并成一团;最重的团先分、每次分给当前最轻的一组(LPT),
    同样的输入永远同样的分法;组内按清单原来的先后顺序跑(依赖写在前面,所以先跑)"""
    if not 1 <= k <= n:
        raise ValueError(f"--shard 要写成 k/n,1 ≤ k ≤ n(现在是 {k}/{n})")
    if deps is None:
        deps = load_deps()
    order = {s: i for i, s in enumerate(suites)}
    weight = lambda c: sum(WEIGHTS.get(s, DEFAULT_WEIGHT) for s in c)  # noqa: E731
    load = [0.0] * n
    group = {}
    for c in sorted(clusters(suites, deps), key=lambda c: (-weight(c), order[c[0]])):
        g = min(range(n), key=lambda i: (load[i], i))
        for s in c:
            group[s] = g
        load[g] += weight(c)
    return [s for s in suites if group[s] == k - 1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shard", help="k/n:只跑分 n 组里的第 k 组")
    ap.add_argument("--timings", action="store_true", help="最后按耗时列出每个套件,抄 WEIGHTS 用")
    args = ap.parse_args()

    suites = load_suites()
    label = "全部"
    if args.shard:
        k, n = (int(x) for x in args.shard.split("/"))
        suites = shard_of(suites, k, n)
        label = f"第 {k}/{n} 组"
    est = sum(WEIGHTS.get(s, DEFAULT_WEIGHT) for s in suites)
    print(f"== e2e {label}:{len(suites)} 个套件,估计 {est / 60:.1f} 分钟", flush=True)

    failed, took = [], {}
    t_all = time.time()
    for i, s in enumerate(suites, 1):
        print(f"\n== [{i}/{len(suites)}] {s}", flush=True)
        t0 = time.time()
        code = subprocess.call([sys.executable, "-m", f"tests.{s}"], cwd=HERE.parent)
        took[s] = time.time() - t0
        if code != 0:
            failed.append((s, code))
            print(f"✗ {s} 退出码 {code}({took[s]:.0f} 秒)", flush=True)

    print(f"\n== e2e {label} 跑完:{len(suites) - len(failed)}/{len(suites)} 通过,"
          f"用时 {(time.time() - t_all) / 60:.1f} 分钟")
    if args.timings:
        for s, sec in sorted(took.items(), key=lambda x: -x[1]):
            if sec >= 6:
                print(f"  {sec:6.1f} 秒  {s}")
    for s, code in failed:
        print(f"✗ {s}(退出码 {code})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
