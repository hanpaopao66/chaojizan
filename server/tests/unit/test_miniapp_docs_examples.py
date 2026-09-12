"""文档里的 Python 验签示例(docs/miniapp/examples/verify.py)拿测试向量跑一遍(#321、#333)。

文档示例要么有测试跑过、要么标「未验证」—— 这份是跑过的那一类。
server.md 里贴的代码和 verify.py 一字不差,由 scripts/check_sdk_docs.mjs 对照。
"""
import importlib.util
from pathlib import Path

from tests.unit.test_mini_app_v2 import AUTH_DATE, PUBLIC_KEY, SECRET, VECTOR

SPEC = importlib.util.spec_from_file_location(
    "doc_verify", Path(__file__).resolve().parents[3] / "docs/miniapp/examples/verify.py")
doc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(doc)
APP = "sz0123456789abcdef"


def test_hash_and_signature_pass_on_vector():
    assert doc.verify_hash(VECTOR, APP, SECRET, now=AUTH_DATE + 5)
    assert doc.verify_signature(VECTOR, APP, PUBLIC_KEY, now=AUTH_DATE + 5)


def test_tamper_expiry_and_app_id_all_fail():
    bad = VECTOR.replace("note42", "note43")
    assert not doc.verify_hash(bad, APP, SECRET, now=AUTH_DATE + 5)
    assert not doc.verify_signature(bad, APP, PUBLIC_KEY, now=AUTH_DATE + 5)
    assert not doc.verify_hash(VECTOR, APP, SECRET, now=AUTH_DATE + 601), "过期"
    assert not doc.verify_signature(VECTOR, "sz0000000000000000", PUBLIC_KEY, now=AUTH_DATE + 5), "app_id 不符"
    assert not doc.verify_hash(VECTOR + "&user=x", APP, SECRET, now=AUTH_DATE + 5), "字段重复"
