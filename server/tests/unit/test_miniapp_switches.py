"""小程序急停闸的登记一处都不能漏(DEV-PROMPTS-39 #337)。

一个闸要在三处出现才算真的能用:管理接口认它(admin._KNOWN_FLAGS,不认就 404)、
后台开关页有它(不然只能 curl)、透明中心的治理时间线会公开它的每次变动(_PUBLIC_FLAGS)。
漏了哪一处都不报错 —— 只是出事那天发现闸拉不下来,或者拉了没人知道。
"""
from pathlib import Path

from app.routers import admin, transparency
from app.services.miniapp_platform import SWITCHES

ROOT = Path(__file__).resolve().parents[3]


def test_every_switch_is_registered_everywhere():
    flags_page = (ROOT / "admin-web/src/pages/FlagsPage.tsx").read_text()
    for key in SWITCHES:
        assert key in admin._KNOWN_FLAGS, f"{key} 不在 admin._KNOWN_FLAGS:管理接口会 404"
        assert key in transparency._PUBLIC_FLAGS, f"{key} 的变动不会进透明中心时间线"
        assert f"key: '{key}'" in flags_page, f"后台开关页没有 {key}"
