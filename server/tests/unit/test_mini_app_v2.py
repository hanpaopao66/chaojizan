"""小程序身份协议 v2 的测试向量与守卫(#321)。

**这一组数写死在这里,也原样写进 docs/miniapp/server.md。** 第三方照文档实现验签,
拿这组向量自测;这边改了算法,向量就对不上 —— 这就是「协议一旦有第三方接入就改不动」
的执行方式。改之前先想清楚所有已经接入的验签方怎么办。
"""
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services import mini_app_v2 as v2

SEED = bytes(range(32))
KEY = Ed25519PrivateKey.from_private_bytes(SEED)
SECRET = "SuperZTestVectorAppSecret0123456789abcdefgh"
PUBLIC_KEY = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"
AUTH_DATE = 1790000000
VECTOR = (
    "app_id=sz0123456789abcdef&auth_date=1790000000&launch_id=AAAAAAAAAAAAAAAAAAAAAA"
    "&sig_kid=56475aa7&start_param=note42"
    "&user=%7B%22language_code%22%3A%22zh-CN%22%2C%22open_id%22%3A%22o_testvectoropenid000000000%22%7D"
    "&hash=797f9baf84dafc57c34179e83285670329947fc09314d2093bec14d1a975515a"
    "&signature=Yd_TNpAvseblIJL5TPzdFhcduSLDXZJnqYovzx8nFNNH3UGqHp-sxmmJRiK6wvdS57vdAo7hEdGmzE621rQICQ"
)
DCS = (
    "app_id=sz0123456789abcdef\n"
    "auth_date=1790000000\n"
    "launch_id=AAAAAAAAAAAAAAAAAAAAAA\n"
    "sig_kid=56475aa7\n"
    "start_param=note42\n"
    'user={"language_code":"zh-CN","open_id":"o_testvectoropenid000000000"}'
)


def _build(**kw):
    args = dict(app_id="sz0123456789abcdef", app_secret=SECRET,
                user={"open_id": "o_testvectoropenid000000000", "language_code": "zh-CN"},
                start_param="note42", auth_date=AUTH_DATE,
                launch_id="AAAAAAAAAAAAAAAAAAAAAA", key=KEY)
    args.update(kw)
    return v2.build_init_data(**args)


def test_vector_is_byte_exact():
    assert _build() == VECTOR


def test_data_check_string_rule():
    assert v2.data_check_string(v2.parse_init_data(VECTOR)) == DCS


def test_public_key_and_kid():
    assert v2._b64url(v2.public_key_raw(KEY)) == PUBLIC_KEY
    assert v2.key_id(v2.public_key_raw(KEY)) == "56475aa7"


def test_both_verifications_pass():
    assert v2.verify_hash(VECTOR, SECRET, now=AUTH_DATE + 5)
    assert v2.verify_signature(VECTOR, PUBLIC_KEY, now=AUTH_DATE + 5)


def test_tamper_any_field_fails_both_ways():
    fields = v2.parse_init_data(VECTOR)
    for k in ("app_id", "auth_date", "launch_id", "sig_kid", "start_param", "user"):
        bad = dict(fields)
        bad[k] = bad[k] + "x" if k != "auth_date" else str(int(bad[k]) + 1)
        from urllib.parse import quote, urlencode
        s = urlencode(list(bad.items()), quote_via=quote)
        assert not v2.verify_hash(s, SECRET, now=AUTH_DATE), k
        assert not v2.verify_signature(s, PUBLIC_KEY, now=AUTH_DATE), k


def test_wrong_secret_fails():
    assert not v2.verify_hash(VECTOR, SECRET + "x", now=AUTH_DATE)


def test_expired_and_future_fail():
    assert not v2.verify_hash(VECTOR, SECRET, now=AUTH_DATE + v2.MAX_AGE_SECONDS + 1)
    assert not v2.verify_signature(VECTOR, PUBLIC_KEY, now=AUTH_DATE - v2.MAX_AGE_SECONDS - 1)
    assert v2.verify_hash(VECTOR, SECRET, now=AUTH_DATE + v2.MAX_AGE_SECONDS)


def test_app_id_binding():
    assert v2.verify_hash(VECTOR, SECRET, now=AUTH_DATE, expect_app_id="sz0123456789abcdef")
    assert not v2.verify_hash(VECTOR, SECRET, now=AUTH_DATE, expect_app_id="szffffffffffffffff")
    assert not v2.verify_signature(VECTOR, PUBLIC_KEY, now=AUTH_DATE,
                                   expect_app_id="szffffffffffffffff")


def test_missing_or_duplicate_fields_fail():
    no_hash = VECTOR.split("&hash=")[0]
    assert not v2.verify_hash(no_hash, SECRET, now=AUTH_DATE)
    assert not v2.verify_signature(no_hash, PUBLIC_KEY, now=AUTH_DATE)
    dup = VECTOR + "&user=%7B%7D"
    assert not v2.verify_hash(dup, SECRET, now=AUTH_DATE)
    assert not v2.verify_signature(dup, PUBLIC_KEY, now=AUTH_DATE)


def test_signature_does_not_need_secret_and_survives_rotation():
    """换 AppSecret 之后,用新密钥签的包旧密钥验不过;但平台签名跟 AppSecret 无关。"""
    rotated = _build(app_secret="another-secret-after-rotation")
    assert not v2.verify_hash(rotated, SECRET, now=AUTH_DATE)
    assert v2.verify_hash(rotated, "another-secret-after-rotation", now=AUTH_DATE)
    assert v2.verify_signature(rotated, PUBLIC_KEY, now=AUTH_DATE)


def test_identifier_formats():
    assert re.fullmatch(r"sz[0-9a-f]{16}", v2.new_appid())
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", v2.new_app_secret())
    ids = {v2.new_open_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(re.fullmatch(r"o_[a-z2-7]{26}", i) for i in ids)


def test_env_field_is_signed():
    sim = _build(env="sim")
    assert "env=sim" in sim
    assert v2.verify_signature(sim, PUBLIC_KEY, now=AUTH_DATE)
    assert not v2.verify_signature(sim.replace("env=sim", "env=prod"), PUBLIC_KEY, now=AUTH_DATE)
