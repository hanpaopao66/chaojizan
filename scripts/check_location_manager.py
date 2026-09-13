#!/usr/bin/env python3
"""查「安卓上取位置绕过了系统 LocationManager」。

geolocator 在装了 Google Play 服务的安卓手机上默认走融合定位(FusedLocationProvider,
play-services-location)。那条路没列在隐私政策的第三方 SDK 表里 —— 所以三端取位置一律
强制走系统的 LocationManager(2026-09-13 定,见 docs/COMPLIANCE-40.md #15):

- 用户端:只许经 apps/user_app/lib/locate.dart 的 deviceCurrentPosition / deviceLastKnownPosition,
  别处直接调 Geolocator.getCurrentPosition / getLastKnownPosition / getPositionStream 算红;
- 骑手端等其余地方:写了 AndroidSettings(...) 就必须带 forceLocationManager: true;
  直接调 getLastKnownPosition 必须带 forceAndroidLocationManager: true。

漏一处不报错、测试也测不出来:国内手机大多没有 Google Play 服务,平时走的本来就是 LocationManager,
只有在装了 Google Play 服务的手机上才悄悄换了一条没公示的路。
确实不需要的地方在那一行写 `// location-manager: ok 原因`。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIRS = ["apps/user_app/lib", "apps/merchant_app/lib", "apps/rider_app/lib", "packages/shared/lib"]
HELPER = ROOT / "apps/user_app/lib/locate.dart"
OK_MARK = "location-manager: ok"

DIRECT = re.compile(r"\bGeolocator\.(getCurrentPosition|getLastKnownPosition|getPositionStream)\s*\(")
ANDROID_SETTINGS = re.compile(r"\bAndroidSettings\s*\(")


def call_args(text, start):
    """从左括号开始配对,返回括号里的原文(字符串里的括号不算)"""
    depth, i, quote = 0, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
        i += 1
    return text[start + 1:]


def main():
    bad = []
    for d in DIRS:
        for path in sorted((ROOT / d).rglob("*.dart")):
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            rel = path.relative_to(ROOT)

            def line_of(pos):
                return text.count("\n", 0, pos) + 1

            def ok(pos):
                return OK_MARK in lines[line_of(pos) - 1]

            in_user_app = str(rel).startswith("apps/user_app/")
            for m in DIRECT.finditer(text):
                if ok(m.start()) or path == HELPER:
                    continue
                if in_user_app:
                    bad.append(f"{rel}:{line_of(m.start())}  用户端取位置要经 locate.dart 的 "
                               f"deviceCurrentPosition / deviceLastKnownPosition,别直接调 Geolocator.{m.group(1)}")
                    continue
                args = call_args(text, m.end() - 1)
                if m.group(1) == "getLastKnownPosition" and "forceAndroidLocationManager: true" not in args:
                    bad.append(f"{rel}:{line_of(m.start())}  getLastKnownPosition 要带 forceAndroidLocationManager: true")
                if m.group(1) != "getLastKnownPosition" and "locationSettings:" not in args:
                    bad.append(f"{rel}:{line_of(m.start())}  Geolocator.{m.group(1)} 要传带 forceLocationManager 的 AndroidSettings")
            for m in ANDROID_SETTINGS.finditer(text):
                if ok(m.start()):
                    continue
                if "forceLocationManager: true" not in call_args(text, m.end() - 1):
                    bad.append(f"{rel}:{line_of(m.start())}  AndroidSettings 要带 forceLocationManager: true")
    if bad:
        print("✗ 安卓取位置绕过了系统 LocationManager(会走没公示的 Google 融合定位):")
        for b in bad:
            print("  " + b)
        sys.exit(1)


if __name__ == "__main__":
    main()
