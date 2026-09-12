"""小程序开放平台的不变量守卫(DEV-PROMPTS-39 §3):代码形状上的那一半。

I1(token 隔离)、I2(open_id 随机映射)在 e2e_miniapp_security,I3(不卖位置)在 test_miniapp_catalog,
I5(处罚有原因、换人复核)在 e2e_miniapp_review,I8 的「用户能看、导出、清空、注销级联」在
e2e_miniapp_storage。这里守的是:

- I4 审核看的就是上线的那一份:版本的对象只在上传时写一次,已存在就拒绝覆盖;版本相关的路由上
  没有改文件的方法(没有 PUT / PATCH / DELETE);
- I6 支付不进小程序、不接广告:SDK、宿主、服务端三处的方法 / 能力表里没有付款相关的名字,用户端没装广告 SDK;
- I7 敏感能力:定位、扫码、剪贴板、手机号还没开放 —— 不在可申请清单里,宿主和 SDK 也没有对应的方法;
- I8 开发者读不到用户的云存储:开发者后台和管理后台的接口里,碰云存储的只有模拟器,
  而且用的是开发者自己的账号(`c.user.id`),不是任何用户的。
"""
import re
from pathlib import Path

import pytest

from app.services import miniapp_publish as pub
from app.services import storage
from app.services.miniapp_package import PackageReport
from app.services.miniapp_platform import (BASIC_CAPABILITIES, FUTURE_CAPABILITIES,
                                           GAME_CAPABILITIES, REQUESTABLE_CAPABILITIES)

ROOT = Path(__file__).resolve().parents[3]
SERVER = ROOT / "server/app"


# ---- I4 ----

class _Bucket:
    def __init__(self, existing: set[str]):
        self.existing = existing
        self.puts: list[str] = []

    def exists(self, key: str, private: bool) -> bool:
        return key in self.existing

    def put(self, data: bytes, key: str, private: bool) -> None:
        self.puts.append(key)


def _report() -> PackageReport:
    rep = PackageReport(sha256="0" * 64, size=3)
    rep.blobs = {"index.html": b"<h1>", "app.js": b"1"}
    return rep


def test_version_objects_are_written_once(monkeypatch):
    fresh = _Bucket(set())
    monkeypatch.setattr(storage, "backend", lambda: fresh)
    pub._write_objects("sz0123456789abcdef", 7, _report(), b"zip")
    assert sorted(fresh.puts) == sorted([pub.object_key("sz0123456789abcdef", 7, "index.html"),
                                         pub.object_key("sz0123456789abcdef", 7, "app.js"),
                                         pub.package_key("sz0123456789abcdef", 7)])

    taken = _Bucket({pub.object_key("sz0123456789abcdef", 7, "app.js")})
    monkeypatch.setattr(storage, "backend", lambda: taken)
    with pytest.raises(storage.StorageError):
        pub._write_objects("sz0123456789abcdef", 7, _report(), b"zip")
    assert taken.puts == [], "有一个对象已存在就一个都不写 —— 不能一半新一半旧"


def _leaf_routes(routes):
    """所有叶子路由。新版 FastAPI 的 include_router 不再把路由摊平,而是挂一个
    `_IncludedRouter`,要钻进 original_router 才看得到 —— 只扫 app.routes 这一层的话,
    这条守卫什么都扫不到,永远是绿的(第一版就是这么空转的,弄坏一次才发现)。"""
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _leaf_routes(inner.routes)
        else:
            yield r


def test_no_route_rewrites_a_version():
    from app.main import app

    version_routes, bad = 0, []
    for route in _leaf_routes(app.routes):
        path = getattr(route, "path", "")
        if "{version_id}" not in path:
            continue
        version_routes += 1
        methods = set(getattr(route, "methods", None) or ())
        if methods & {"PUT", "PATCH", "DELETE"}:
            bad.append(f"{sorted(methods)} {path}")
    assert version_routes >= 8, f"只扫到 {version_routes} 条版本路由,扫描方式和 FastAPI 对不上了"
    assert not bad, "版本上传之后不许改:" + ";".join(bad)


# ---- I6 / I7:三处的方法表 ----

def _sdk_methods() -> set[str]:
    src = (ROOT / "packages/miniapp-sdk/src/index.ts").read_text()
    block = re.search(r"export const BRIDGE_METHODS = \[(.*?)\] as const", src, re.S).group(1)
    return set(re.findall(r"'([^']+)'", block))


def _host_methods() -> dict[str, str | None]:
    src = (ROOT / "apps/user_app/lib/miniapp/bridge.dart").read_text()
    block = re.search(r"const kMethodCapability = <String, String\?>\{(.*?)\};", src, re.S).group(1)
    return {m: (None if c == "null" else c.strip("'"))
            for m, c in re.findall(r"'([^']+)':\s*('[^']*'|null)", block)}


def _capabilities() -> set[str]:
    return {*BASIC_CAPABILITIES, *GAME_CAPABILITIES, *REQUESTABLE_CAPABILITIES}


def test_three_method_tables_agree():
    """SDK 能发的、宿主认的,是同一张表 —— 不一致的话后面几条扫的就不是真在跑的东西。"""
    assert _sdk_methods() == set(_host_methods()), "SDK 的 BRIDGE_METHODS 和宿主的 kMethodCapability 对不上"
    assert {c for c in _host_methods().values() if c} <= _capabilities()


PAY_WORDS = ("pay", "purchase", "wallet", "card", "password", "invoice", "billing", "iap",
             "recharge", "coin")


def test_no_payment_anywhere_in_the_bridge():
    names = _sdk_methods() | set(_host_methods()) | _capabilities() | set(FUTURE_CAPABILITIES)
    hits = sorted(n for n in names for w in PAY_WORDS if w in n.lower())
    assert not hits, f"桥里出现了付款相关的方法或能力:{hits}"


def test_no_ad_sdk_in_the_user_app():
    deps = (ROOT / "apps/user_app/pubspec.yaml").read_text()
    names = re.findall(r"^\s{2}([a-z0-9_]+):", deps, re.M)
    ad = [n for n in names if re.search(r"(^|_)ads?($|_)|admob|pangle|gdt|applovin|ironsource|mintegral", n)]
    assert not ad, f"用户端装了广告 SDK:{ad}"


SENSITIVE_METHODS = ("getLocation", "showScanQrPopup", "readTextFromClipboard", "requestContact")


def test_sensitive_capabilities_are_not_open_yet():
    assert not set(FUTURE_CAPABILITIES) & set(REQUESTABLE_CAPABILITIES), \
        "定位、扫码、剪贴板、手机号开放之前,必须先有逐次确认(I7)"
    assert not set(FUTURE_CAPABILITIES) & set(_host_methods().values())
    assert not set(SENSITIVE_METHODS) & (_sdk_methods() | set(_host_methods()))


# ---- I8 ----

def test_developer_and_admin_endpoints_cannot_read_user_storage():
    dev = (SERVER / "routers/dev_miniapps.py").read_text()
    admin = (SERVER / "routers/admin_miniapps.py").read_text()
    for name, src in (("dev_miniapps", dev), ("admin_miniapps", admin)):
        assert "MiniAppKV" not in src, f"{name} 直接碰了云存储表"
        for fn in ("get_items", "get_keys", "set_item", "remove_items", "usage", "export"):
            assert f"kv.{fn}(" not in src, f"{name} 调了 kv.{fn}"
    calls = re.findall(r"run_storage\(([^)]*)\)", dev)
    assert calls, "模拟器的云存储入口不见了?这条守卫要跟着改"
    for args in calls:
        user_arg = [a.strip() for a in args.split(",")][2]
        assert user_arg == "c.user.id", f"开发者后台的云存储只能是开发者自己的:run_storage({args})"
    assert "run_storage" not in admin
