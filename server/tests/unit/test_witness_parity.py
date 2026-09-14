"""四个见证实现核账口径一致(docs/LEDGER-SPEC.md §6、§9)。

第一方见证有四个:witness/superz_witness.py(Python)、witness/go/main.go(Go 绿色版)、
server/static/nodes.html(网页版)、packages/shared/lib/src/witness_service.dart(App 内)。
原来只有 Python 版认得 2026-09 起的新字段(判责行、保障金池、申诉改判退款、合计),另外三个
不认 —— 平台在那几栏里造假,四个节点里三个看不见;App 版还把合法的骑手补偿行
(adjustment)当成违规。

现在四个跑同一份用例 witness/testdata/verify_rows_cases.json:
- Python 版在这里跑;
- Go 版:witness/go/main_test.go(make unit 里 go test);
- 网页版:scripts/test_witness_web.mjs(make unit 里 node 跑,原样截 nodes.html 那一段);
- App 版:packages/shared/test/witness_verify_test.dart(make analyze / CI 的 dart 单测)。
这里另守两件事:服务端导出的每一种行、每一项要核的合计,四个实现都认识;那三份测试都还在、
都接在 make / CI 上(测试文件在、没人跑,等于没有)。
"""
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "witness"))
import superz_witness as w  # noqa: E402

CASES_PATH = REPO / "witness/testdata/verify_rows_cases.json"
DOC = json.loads(CASES_PATH.read_text(encoding="utf-8"))
IMPLS = {
    "Python": REPO / "witness/superz_witness.py",
    "Go": REPO / "witness/go/main.go",
    "网页": REPO / "server/static/nodes.html",
    "App": REPO / "packages/shared/lib/src/witness_service.dart",
}
#: 规格 §6.5 里见证要核的合计(骑手、住宿服务费是规范性的,其余是 2026-09 起四个实现都核的)
CHECKED_TOTALS = ("rider_amount", "stay_fee", "rider_fault", "merchant_fault",
                  "appeal_refund", "platform_correction")


def _tags(problems):
    """问题的种类:问题文本第一个空格前的那个词(合计类的问题整句没有空格,就是整句)"""
    return sorted(p.split(" ", 1)[0] for p in problems)


@pytest.mark.parametrize("case", DOC["cases"], ids=[c["name"] for c in DOC["cases"]])
def test_Python见证跑共用用例(case):
    problems = w.verify_rows(case["payload"])
    assert _tags(problems) == sorted(case["expect"]), problems


@pytest.mark.parametrize("vec", DOC["hash_vectors"], ids=[v["name"] for v in DOC["hash_vectors"]])
def test_哈希向量(vec):
    canon = w.canonical(vec["payload"])
    assert canon == vec["canonical"]
    assert w.sha256(canon) == vec["payload_hash"]
    assert w.sha256(vec["prev"] + vec["payload_hash"]) == vec["chain_hash"]


def _clean():
    return next(c for c in DOC["cases"] if c["name"].startswith("干净的一天"))["payload"]


def test_平台纠错_服务端和见证同一个式子():
    from app.services import ledger
    p = _clean()
    server = ledger.platform_correction(p["merchant_rows"], p["merchant_fault_rows"],
                                        p["rider_fault_rows"], p["appeal_refund_rows"])
    assert server == w.platform_correction(p) == p["totals"]["platform_correction"]


def _payload_keys():
    """服务端 ledger.build_day_payload 导出的行数组、合计各项(按源码读)"""
    from app.services import ledger
    src = inspect.getsource(ledger.build_day_payload)
    rows = set(re.findall(r'"(\w+_rows)":', src))
    totals_src = src.split('"totals": {', 1)[1]
    totals = set(re.findall(r'"(\w+)":', totals_src))
    return rows, totals


def test_干净的一天覆盖服务端导出的每一种行和每一项合计():
    rows, totals = _payload_keys()
    assert len(rows) >= 7 and len(totals) >= 13, (rows, totals)
    p = _clean()
    assert rows <= set(p), f"共用用例「干净的一天」缺了服务端导出的行:{rows - set(p)}"
    assert p["rider_fund"]["rows"], "保障金池的支出/回池行也要有"
    assert totals <= set(p["totals"]), f"缺了合计:{totals - set(p['totals'])}"
    assert set(CHECKED_TOTALS) <= totals


@pytest.mark.parametrize("impl", IMPLS)
def test_四个实现都认识每一种行和每一项要核的合计(impl):
    src = IMPLS[impl].read_text(encoding="utf-8")
    rows, _ = _payload_keys()
    # 按整词找:rider_fault 是 rider_fault_rows 的前缀,不按整词的话合计没核也会被当成认识
    missing = [k for k in (*sorted(rows), *CHECKED_TOTALS)
               if not re.search(rf"(?<!\w){k}(?!\w)", src)]
    assert not missing, f"{impl} 见证不认识:{missing}"


def test_另外三个实现的测试都在_都接在make和CI上():
    name = CASES_PATH.name
    go_test = REPO / "witness/go/main_test.go"
    web_test = REPO / "scripts/test_witness_web.mjs"
    dart_test = REPO / "packages/shared/test/witness_verify_test.dart"
    for t in (go_test, web_test, dart_test):
        assert name in t.read_text(encoding="utf-8"), f"{t.relative_to(REPO)} 没跑共用用例"
    assert "witness-verify:start" in IMPLS["网页"].read_text(encoding="utf-8")
    make = (REPO / "Makefile").read_text(encoding="utf-8")
    unit = make.split("\nunit:", 1)[1].split("\n\n", 1)[0]
    assert "cd witness/go && go test" in unit, "make unit 里没跑 Go 见证的测试"
    assert "node scripts/test_witness_web.mjs" in unit, "make unit 里没跑网页见证的测试"
    ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    unit_job = ci.split("\n  unit:\n", 1)[1].split("\n  flutter:\n", 1)[0]
    assert "actions/setup-go" in unit_job and "make unit" in unit_job, \
        "CI 的单测 job 没装 Go(make unit 要跑 go test)"
    # Dart 那份:packages/shared 的单测在 make analyze 和 CI「dart 单测」里本来就全跑
    assert "packages/shared" in make.split("\nanalyze:", 1)[1].split("\nunit:", 1)[0]
