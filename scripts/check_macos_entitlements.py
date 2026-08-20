#!/usr/bin/env python3
"""macOS 的沙箱权限声明检查。

## 为什么需要它

`flutter create` 生成的 `Release.entitlements` 模板里**只有 app-sandbox**,
没有 `com.apple.security.network.client`。沙箱开着又不给出网权限,
release 版 macOS App 一个网络请求都发不出去。

而这个错**最难发现**:

- debug 版是好的(模板给了 `network.server` 供热重载),本地调试全正常;
- 表现是"所有接口超时",不是权限错 —— 看日志会以为是后端挂了;
- 平台目录一旦被 `flutter create` 重新生成,这条就又没了。

2026-08-19 那次实证过:补上之后 release 包在沙箱里真的发出了请求
(后端日志收到 `GET /splash?app=rider` 200)。这个脚本盯住它别再掉。

    python3 scripts/check_macos_entitlements.py
"""
import pathlib
import plistlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APPS = ["user_app", "merchant_app", "rider_app"]

#: 每一档都必须有,而且必须是 true。
#:
#: - app-sandbox:上架 Mac App Store 的硬要求,不能关;
#: - network.client:**出网**。少了它 release 版一个请求都发不出去。
REQUIRED = {
    "Release": ["com.apple.security.app-sandbox",
                "com.apple.security.network.client"],
    # debug 还要 network.server:热重载要监听端口
    "DebugProfile": ["com.apple.security.app-sandbox",
                     "com.apple.security.network.client",
                     "com.apple.security.network.server"],
}


def main() -> int:
    bad = []
    for app in APPS:
        for name, keys in REQUIRED.items():
            p = ROOT / f"apps/{app}/macos/Runner/{name}.entitlements"
            if not p.exists():
                bad.append(f"{app}/{name}.entitlements 不存在 —— "
                           "平台目录是不是被 gitignore 挡掉了?")
                continue
            data = plistlib.loads(p.read_bytes())
            for k in keys:
                if data.get(k) is not True:
                    bad.append(f"{app}/{name}:缺 {k}")
            print(f"  {'✓' if all(data.get(k) is True for k in keys) else '✗'} "
                  f"{app}/{name}")

    if bad:
        print("\n✗ macOS 权限声明不全:")
        for b in bad:
            print("   ", b)
        print("\n   少了 network.client 的表现是**所有接口超时**,不是权限错 ——")
        print("   而且 debug 版一切正常,只有 release 包会炸。")
        return 1
    print("\n✓ macOS 权限声明齐全")
    return 0


if __name__ == "__main__":
    sys.exit(main())
