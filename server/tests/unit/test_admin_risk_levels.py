"""后台风控页「限制 / 冻结 / 解除」三个按钮发的值,必须正好是服务端 set_user_risk_level 认的值。

2026-09-14 发现:页面写的是 'limited',服务端只认 'limit'(services/enforcement.LEVEL_LIMIT),
「限制」按钮一按就 422。前端 tsc 是绿的、服务端 e2e 也是绿的 —— 两边各测各的,谁也没对着谁查。
这里直接读两边的源码比对。
"""
import re
from pathlib import Path

from app.services import enforcement

ROOT = Path(__file__).resolve().parents[3]


def _page_levels() -> set[str]:
    src = (ROOT / "admin-web/src/pages/RiskPage.tsx").read_text(encoding="utf-8")
    start = src.index("const LEVELS")
    block = src[start:src.index("\n]", start)]
    return set(re.findall(r"value:\s*'([^']*)'", block))


def _server_levels() -> set[str]:
    src = (ROOT / "server/app/routers/admin.py").read_text(encoding="utf-8")
    fn = src[src.index("async def set_user_risk_level"):]
    m = re.search(r"if level not in \(([^)]*)\):", fn)
    assert m, "set_user_risk_level 里没找到 level 的取值检查,这条测试要跟着改"
    return set(re.findall(r"\"([^\"]*)\"", m.group(1)))


def test_risk_page_sends_what_server_accepts():
    assert _page_levels() == _server_levels()


def test_server_levels_are_the_enforcement_levels():
    assert _server_levels() == {enforcement.LEVEL_NONE, enforcement.LEVEL_LIMIT, enforcement.LEVEL_FROZEN}
