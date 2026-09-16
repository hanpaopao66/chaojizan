"""音乐模块的不变量守卫:代码形状上的那一半(DEV-PROMPTS-41 §3)。

- §3.1 不收钱:音乐的表、列、路由、处理函数、service 函数里没有付款相关的名字;
- §3.2 不要求实名:music*.py 里不许引用 UserIdentity / require_realname;
- §3.8 开关是急停闸:`/music/v1` 下每一条路由都挂着 music_on,上传类另挂 music_upload_on;
  缺省值生产关、开发开 —— 忘了配的后果是音乐打不开,不是没许可证就上线了;
- 路由数得对:include_router 不再把路由摊平,扫描要钻进去(见 test_social_flags 的 walk)。
"""
import re
from pathlib import Path

from app.models import MUSIC_MODELS

ROOT = Path(__file__).resolve().parents[3]
SERVER = ROOT / "server/app"

#: 付款相关的名字(英文标识符里的片段)。和 test_video_invariants 用同一张表
PAY = re.compile(r"pay|price|cash|money|recharge|top_?up|withdraw|wallet|purchase|refund|"
                 r"premium|vip|donat|sponsor|reward|charge|exchange|redeem|cents|yuan", re.I)
#: tip(打赏)只认独立的词,免得误伤 multiple / tooltip
TIP = re.compile(r"(^|_)tips?($|_)", re.I)

#: 音乐的 service 和 router 文件(新加的音乐文件要一起进来)
MUSIC_SERVICES = ("music", "music_rank", "music_state", "music_interact", "music_talk",
                  "music_media", "music_access")
MUSIC_ROUTERS = ("music", "music_admin")

#: §5.3 的状态机里有一个「音乐人自己下架」叫 withdraw / withdrawn,§8.2 的路径也是
#: `POST /studio/releases/{rid}/withdraw`(客户端照着写)。它是**作品状态**,不是提现 ——
#: 这几个名字按原样放行,别的 withdraw(真的提现)照样红
WITHDRAW_OK = {"withdraw", "withdrawn", "withdraw_release"}


def _code(src: str) -> str:
    """去掉注释和文档字符串:守卫要扫的是代码,不是「这里不引用 X」这种说明。"""
    body = re.sub(r'"""(.*?)"""', "", src, flags=re.S)
    return "\n".join(line.split("#", 1)[0] for line in body.splitlines())


def _leaf_routes(routes):
    for r in routes:
        inner = getattr(r, "original_router", None)   # FastAPI 0.139 的 include_router 不摊平
        if inner is not None:
            yield from _leaf_routes(inner.routes)
        else:
            yield r


def _music_routes():
    from app.main import app

    return [r for r in _leaf_routes(app.routes)
            if getattr(r, "path", "").startswith(("/music/v1", "/admin/music"))]


def _bad(name: str) -> bool:
    if name in WITHDRAW_OK:
        return False
    return bool(PAY.search(name) or TIP.search(name))


def test_music_routes_are_all_found():
    routes = _music_routes()
    assert len(routes) >= 50, f"只扫到 {len(routes)} 条音乐路由,扫描方式和 FastAPI 对不上了"


def test_no_payment_names_in_routes():
    bad = []
    for r in _music_routes():
        segs = [s for s in r.path.split("/") if s and not s.startswith("{")]
        for s in segs + [r.endpoint.__name__]:
            if _bad(s.replace("-", "_").replace(".", "_")):
                bad.append(f"{sorted(r.methods)} {r.path} ({r.endpoint.__name__})")
    assert not bad, f"§3.1:音乐模块出现了付款相关的接口:{bad}"


def test_no_payment_columns():
    bad = [f"{m.__tablename__}.{c.name}" for m in MUSIC_MODELS for c in m.__table__.columns
           if _bad(c.name)] + [m.__tablename__ for m in MUSIC_MODELS if _bad(m.__tablename__)]
    assert not bad, f"§3.1:音乐的表里出现了和钱有关的列:{bad}"


def test_no_payment_functions_in_services():
    bad = []
    for mod in MUSIC_SERVICES:
        src = (SERVER / f"services/{mod}.py").read_text(encoding="utf-8")
        for name in re.findall(r"^(?:async )?def ([a-z_0-9]+)", src, re.M):
            if _bad(name):
                bad.append(f"{mod}.{name}")
    assert not bad, f"§3.1:service 里出现了付款相关的函数:{bad}"


def test_no_request_field_mentions_payment():
    """请求体的字段名也扫一遍 —— 「加个 paid 字段」和「加个付费接口」一样不行。"""
    bad = []
    for mod in MUSIC_ROUTERS:
        src = (SERVER / f"routers/{mod}.py").read_text(encoding="utf-8")
        for field in re.findall(r"^\s{4}([a-z_0-9]+)\s*:", src, re.M):
            if _bad(field):
                bad.append(f"{mod}.{field}")
    assert not bad, f"§3.1:请求字段里出现了付款相关的名字:{bad}"


def test_music_does_not_require_realname():
    """§3.2 不要求实名(2026-09-15 用户拍板):音乐的代码一个字都不许提实名。"""
    offenders = []
    for path in ([SERVER / f"services/{m}.py" for m in MUSIC_SERVICES]
                 + [SERVER / f"routers/{m}.py" for m in MUSIC_ROUTERS]
                 + [SERVER / "models_music.py"]):
        src = _code(path.read_text(encoding="utf-8"))
        if re.search(r"UserIdentity|require_realname|verify_identity|id_card|real_name", src):
            offenders.append(path.name)
    assert not offenders, f"§3.2:这些文件引用了实名:{offenders}"


def test_music_flags_default_off_in_prod_on_in_dev(monkeypatch):
    from app.config import settings
    from app.services import flags

    monkeypatch.setattr(settings, "app_env", "prod")
    assert flags.music_flag_default() == "off", "生产缺省关:版权和许可的结论出来之前不能打开"
    for env in ("staging", "", "Prod", "dev "):
        monkeypatch.setattr(settings, "app_env", env)
        assert flags.music_flag_default() == ("on" if env.strip().lower() == "dev" else "off"), env
    monkeypatch.setattr(settings, "app_env", "dev")
    assert flags.music_flag_default() == "on"
    assert set(flags.MUSIC_FLAGS) == {"music_enabled", "music_upload_enabled"}


def test_music_flags_are_known_to_the_admin_console():
    from app.routers.admin import _KNOWN_FLAGS

    assert {"music_enabled", "music_upload_enabled"} <= _KNOWN_FLAGS


def test_config_features_expose_music():
    src = (SERVER / "routers/platform.py").read_text(encoding="utf-8")
    assert '"music": await music_flag_on(db, "music_enabled")' in src
    assert '"music_upload": await music_flag_on(db, "music_upload_enabled")' in src


def test_every_music_route_hangs_on_the_music_flag():
    """急停要真能停:/music/v1 下每一条路由都挂着 music_on。"""
    for r in _music_routes():
        if not r.path.startswith("/music/v1"):
            continue
        deps = {getattr(d.call, "__name__", "") for d in r.dependant.dependencies}
        assert "music_on" in deps, f"{r.path} 没挂音乐开关"


def test_upload_routes_are_gated_by_the_upload_flag():
    """开通音乐人、建作品、加歌、提交审核挂在「音乐投稿」开关上(整个模块挂在「音乐功能」上)。"""
    gated = {r.path for r in _music_routes()
             if "music_upload_on" in {getattr(d.call, "__name__", "")
                                      for d in r.dependant.dependencies}}
    assert gated == {"/music/v1/studio/artist", "/music/v1/studio/releases",
                     "/music/v1/studio/releases/{rid}/tracks",
                     "/music/v1/studio/releases/{rid}/submit"}, gated


def test_media_upload_purpose_is_gated_too():
    """原始音频和封面也受投稿开关管(不然开关关着、存储照样被占满)。"""
    from app.routers.media import PURPOSES

    assert PURPOSES["music"] == {"audio_source", "cover"}
    src = (SERVER / "routers/media.py").read_text(encoding="utf-8")
    assert src.count("await _music_upload_gate(db,") == 2, "整块上传和分片上传都要过这道闸"
    from app.services.media import LIMITS
    assert LIMITS["audio_source"] == 200 * 1024 * 1024, "单首 ≤ 200MB(M4)"


def test_music_cover_bucket_is_public_and_audio_is_not():
    from app.services.storage import PURPOSES as SPURPOSES

    assert SPURPOSES["music_cover"] is False, "封面、头像是公开的"
    assert "music_audio" not in SPURPOSES, "音频不走公开桶,播放要签名(§5.5)"


def test_public_ids_have_the_right_prefixes():
    from app.services import music as msvc

    assert msvc.PREFIXES == {"track": "mt", "release": "mr", "playlist": "mp", "artist": "ma"}
    for kind, prefix in msvc.PREFIXES.items():
        pid = msvc.new_id(kind)
        assert pid.startswith(prefix) and len(pid) == 12
        assert msvc.valid_id(kind, pid)
        assert not msvc.valid_id(kind, prefix + "0" * 10), "base58 里没有 0/O/I/l"
        assert not msvc.valid_id(kind, "1")


def test_reason_codes_cover_the_music_ones():
    from app.services import music as msvc

    assert set(msvc.MUSIC_ONLY_CODES) == {"M301", "M302", "M303", "M304", "M305"}
    assert msvc.COPYRIGHT_CODE == "M301"
    assert {"C101", "C109", "X999"} <= set(msvc.REASON_CODES)
    doc = (ROOT / "docs/DEV-PROMPTS-41.md").read_text(encoding="utf-8")
    for code, label in msvc.MUSIC_ONLY_CODES.items():
        assert f"`{code}`" in doc and label in doc, f"{code} 的说明和 §5.11 对不上"


def test_card_of_is_available_for_the_shared_resolver():
    """§8.3:services/cards.py(论坛后端建)会注册这四种类型,签名必须对得上。"""
    import inspect

    from app.services import music as msvc

    sig = inspect.signature(msvc.card_of)
    assert list(sig.parameters) == ["db", "type", "public_id", "viewer_id"]
    assert inspect.iscoroutinefunction(msvc.card_of)
