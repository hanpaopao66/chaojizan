"""可下发文案的登记表(services/copy_registry.py)和客户端 Dart 源码对得上。

防的是这几种「后台改了没反应」:
- 客户端读了一个 key、登记表里没有 → 后台根本改不了它;
- 登记表里有、客户端没人读 → 后台改了没反应(以为改了);
- 默认值两边不一样 → 后台页上写的「默认」和用户实际看到的不是一句话;
- 登记成「能藏」、客户端却没判 shown → 后台藏了,用户那边照样显示。
"""
import re
from pathlib import Path

from app.services.copy_registry import COPY_KEYS

REPO = Path(__file__).resolve().parents[3]
DART_DIRS = [REPO / "apps" / app / "lib" for app in ("user_app", "merchant_app", "rider_app")] + \
            [REPO / "packages" / "shared" / "lib"]

_LIT = r"'(?:[^'\\]|\\.)*'"
_TEXT_RE = re.compile(r"RemoteCopy\.text\(\s*'([a-z0-9_.]+)'\s*,\s*((?:" + _LIT + r"\s*)+)\)")
_SHOWN_RE = re.compile(r"RemoteCopy\.shown\(\s*'([a-z0-9_.]+)'\s*\)")
_CHANNEL_RE = re.compile(r"key:\s*'([a-z]+)',\s*name:\s*'([^']+)'")


def _dart_sources() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for d in DART_DIRS if d.exists()
                     for p in d.rglob("*.dart"))


def _unquote(literals: str) -> str:
    """相邻的 Dart 单引号字符串拼起来,认 \\n 和 \\' 这两种转义(文案里只用到这些)。"""
    parts = re.findall(_LIT, literals)
    return "".join(p[1:-1].replace("\\n", "\n").replace("\\'", "'") for p in parts)


def _client_defaults() -> dict[str, str]:
    src = _dart_sources()
    out = {k: _unquote(v) for k, v in _TEXT_RE.findall(src)}
    # 首页业务的名字不是 text() 调用:SzChannel.title 读 'channel.<key>.name',默认值是 kChannels 里写的 name
    chan = (REPO / "packages/shared/lib/src/channels.dart").read_text(encoding="utf-8")
    assert "RemoteCopy.text('channel.$key.name', name)" in chan, "SzChannel.title 不读后台文案了?"
    # 去掉注释行:kChannels 下面有一段注释掉的「下一个频道」示例(打车),不是已上线的业务
    live = "\n".join(line for line in chan.splitlines() if not line.lstrip().startswith("//"))
    for key, name in _CHANNEL_RE.findall(live):
        out[f"channel.{key}.name"] = name
    return out


def test_every_client_key_is_registered_and_defaults_match():
    client = {k: v for k, v in _client_defaults().items() if not k.startswith("pledge.")}
    assert client, "一个 RemoteCopy.text 都没找到:正则失效了"
    missing = sorted(set(client) - set(COPY_KEYS))
    assert not missing, f"客户端读了这些 key,登记表里没有(后台改不了):{missing}"
    unused = sorted(set(COPY_KEYS) - set(client))
    assert not unused, f"登记了、客户端却没人读(后台改了不会生效):{unused}"
    for key, meta in COPY_KEYS.items():
        assert meta.default == client[key], f"{key} 默认值两边不一样:登记表 {meta.default!r},客户端 {client[key]!r}"


def test_hideable_keys_are_checked_by_client():
    shown = set(_SHOWN_RE.findall(_dart_sources()))
    for key, meta in COPY_KEYS.items():
        if meta.hideable:
            assert key in shown, f"{key} 登记成能藏,客户端却没判 RemoteCopy.shown —— 后台藏了用户那边照样显示"
        else:
            assert meta.hide_note, f"{key} 不能藏,要写明为什么(或者去哪儿藏)"
    assert shown <= set(COPY_KEYS), f"客户端判了没登记的位置:{sorted(shown - set(COPY_KEYS))}"


def test_defaults_fit_their_own_limits():
    for key, meta in COPY_KEYS.items():
        assert 0 < len(meta.default) <= meta.max_len, f"{key} 的默认值自己就超长了"
    # 首页、我的这两格藏了就进不去设置,不许藏
    assert not COPY_KEYS["nav.home"].hideable and not COPY_KEYS["nav.me"].hideable
