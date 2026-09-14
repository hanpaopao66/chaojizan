"""全量 e2e 的清单(tests/e2e_suites.txt)和分组(tests/run_e2e.py)。

清单漏了一个套件不报错 —— 那个套件只是永远不会被跑,红了也没人知道;
分组漏了或重复了也一样。这几条守的就是这种「不报错的漏」。
"""
from pathlib import Path

from tests import run_e2e

TESTS = Path(run_e2e.__file__).resolve().parent
#: 要特殊环境、故意不进全量的(见 Makefile 的 test-special)
SPECIAL = {"e2e_eta_compensation", "e2e_privacy_phone_strict"}


def test_every_e2e_file_is_listed_or_special():
    files = {p.stem for p in TESTS.glob("e2e_*.py")}
    listed = set(run_e2e.load_suites())
    missing = files - listed - SPECIAL
    assert not missing, f"这些 e2e 没进 tests/e2e_suites.txt,永远不会被跑:{sorted(missing)}"
    ghost = listed - files
    assert not ghost, f"清单里写了但没有这个文件:{sorted(ghost)}"
    assert not (listed & SPECIAL), "特殊环境的套件不该进全量清单"


def test_no_duplicates():
    suites = run_e2e.load_suites()
    assert len(suites) == len(set(suites)), "清单里有重复的套件"


def test_shards_cover_everything_exactly_once():
    suites = run_e2e.load_suites()
    for n in (1, 2, 3, 4, 6):
        groups = [run_e2e.shard_of(suites, k, n) for k in range(1, n + 1)]
        flat = [s for g in groups for s in g]
        assert sorted(flat) == sorted(suites), f"分 {n} 组时有套件漏了或重复了"
        for g in groups:  # 组内保持清单里的先后顺序
            assert g == [s for s in suites if s in set(g)]


def test_shards_are_balanced():
    """分 4 组时最重的一组不超过平均的 1.25 倍(几个大套件分开,不挤在一组)"""
    suites = run_e2e.load_suites()
    w = lambda g: sum(run_e2e.WEIGHTS.get(s, run_e2e.DEFAULT_WEIGHT) for s in g)  # noqa: E731
    loads = [w(run_e2e.shard_of(suites, k, 4)) for k in range(1, 5)]
    assert max(loads) <= 1.25 * sum(loads) / 4, loads


def test_deps_are_listed_earlier():
    """「套件: 依赖」里的依赖必须是清单里的套件,而且写在它前面 —— 组内按清单顺序跑,
    写在后面的话它会先跑、找不到要的数据"""
    suites = run_e2e.load_suites()
    pos = {s: i for i, s in enumerate(suites)}
    for s, ds in run_e2e.load_deps().items():
        for d in ds:
            assert d in pos, f"{s} 依赖的 {d} 不在清单里"
            assert pos[d] < pos[s], f"{s} 依赖的 {d} 要写在它前面"


def test_deps_land_in_same_shard_before_dependent():
    suites = run_e2e.load_suites()
    deps = run_e2e.load_deps()
    for n in (2, 3, 4, 6):
        for k in range(1, n + 1):
            g = run_e2e.shard_of(suites, k, n)
            for s in g:
                for d in deps.get(s, []):
                    assert d in g and g.index(d) < g.index(s), (n, k, s, d)

