"""视频模块的不变量守卫:代码形状上的那一半(DEV-PROMPTS-40 §3)。

- S4 不收钱:视频 / 互动消息 / 视频治理的表、列、路由、处理函数、service 函数里没有付款相关的名字;
  硬币只有「每日首次打开视频」「投稿过审」两个来源(另两种流水是转手:投出去、收到投币),
  没有充值、提现、兑换的入口;
- #375 开关:生产缺省关、开发缺省开 —— 忘了配的后果是视频打不开,不是没许可证就上线了;
- 路由数得对:include_router 不再把路由摊平,扫描要钻进去(见 test_miniapp_invariants._leaf_routes)。
"""
import inspect
import re
from pathlib import Path

from app.models import VIDEO_MODELS
from app.services import video as vsvc

ROOT = Path(__file__).resolve().parents[3]
SERVER = ROOT / "server/app"

#: 付款相关的名字(英文标识符里的片段)。硬币(coin)本身是积分,不在这里
PAY = re.compile(r"pay|price|cash|money|recharge|top_?up|withdraw|wallet|purchase|refund|"
                 r"premium|vip|donat|sponsor|reward|charge|exchange|redeem|cents|yuan", re.I)
#: tip(打赏)只认独立的词,免得误伤 multiple / tooltip
TIP = re.compile(r"(^|_)tips?($|_)", re.I)


def _leaf_routes(routes):
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _leaf_routes(inner.routes)
        else:
            yield r


def _video_routes():
    from app.main import app
    out = []
    for r in _leaf_routes(app.routes):
        path = getattr(r, "path", "")
        if path.startswith(("/video/v1", "/social/v1/notifications", "/admin/social")):
            out.append(r)
    return out


def _bad(name: str) -> bool:
    return bool(PAY.search(name) or TIP.search(name))


def test_video_routes_are_all_found():
    routes = _video_routes()
    assert len(routes) >= 70, f"只扫到 {len(routes)} 条视频相关路由,扫描方式和 FastAPI 对不上了"


def test_s4_no_payment_names_in_routes():
    bad = []
    for r in _video_routes():
        segs = [s for s in r.path.split("/") if s and not s.startswith("{")]
        for s in segs + [r.endpoint.__name__]:
            if _bad(s.replace("-", "_").replace(".", "_")):
                bad.append(f"{sorted(r.methods)} {r.path} ({r.endpoint.__name__})")
    assert not bad, f"S4:视频模块出现了付款相关的接口:{bad}"


def test_s4_no_payment_columns():
    bad = [f"{m.__tablename__}.{c.name}" for m in VIDEO_MODELS for c in m.__table__.columns
           if _bad(c.name)] + [m.__tablename__ for m in VIDEO_MODELS if _bad(m.__tablename__)]
    assert not bad, f"S4:视频模块的表里出现了和钱有关的列:{bad}"


def test_s4_no_payment_functions_in_services():
    bad = []
    for mod in ("video", "video_feed", "video_interact", "video_talk", "video_media",
                "video_state", "video_rank", "video_access", "social_notify"):
        src = (SERVER / f"services/{mod}.py").read_text(encoding="utf-8")
        for name in re.findall(r"^(?:async )?def ([a-z_0-9]+)", src, re.M):
            if _bad(name):
                bad.append(f"{mod}.{name}")
    assert not bad, f"S4:service 里出现了付款相关的函数:{bad}"


def test_coins_only_come_from_daily_and_approval():
    """硬币只有两个来源(D13、S4):每日首次 +1、投稿过审 +2(每天封顶)。投币是转手,不产生新硬币。"""
    assert set(vsvc.COIN_REASONS) == {"daily", "video_approved", "coin_give", "coin_receive"}
    assert vsvc.MINTING_REASONS == ("daily", "video_approved")
    assert (vsvc.DAILY_COINS, vsvc.APPROVAL_COINS) == (1, 2) and vsvc.APPROVAL_DAILY_CAP > 0
    assert vsvc.COIN_MAX == {"original": 2, "repost": 1}
    # 所有写流水的地方:正数只出现在 daily / video_approved / coin_receive,而 coin_receive
    # 和同一笔的 coin_give 成对出现(give_coins 里先扣投币的人、再加给 UP 主)
    src = inspect.getsource(vsvc)
    writes = re.findall(r'_ledger\(db, [^,]+, ([^,]+), "([a-z_]+)"', src)
    assert {r for _, r in writes} == {"daily", "coin_give", "coin_receive"}, writes
    assert "reason=\"video_approved\"" in src.replace("'", '"')
    give = inspect.getsource(vsvc.give_coins)
    assert give.index('"coin_give"') < give.index('"coin_receive"'), "先扣再加,扣不动整笔回滚"
    # 没有任何接口能直接改余额:改 social_profiles.coins 的只有这几个函数
    touch = [name for name, fn in inspect.getmembers(vsvc, inspect.iscoroutinefunction)
             if "SocialProfile.coins +" in inspect.getsource(fn)
             or "SocialProfile.coins -" in inspect.getsource(fn)]
    assert sorted(touch) == ["give_coins", "grant_approval_coins", "grant_daily"], touch


def test_no_coin_endpoint_can_mint():
    """硬币相关的写接口只有:领每日硬币、投币、三连。"""
    writes = sorted(r.path for r in _video_routes()
                    if "coin" in r.path and r.methods & {"POST", "PUT", "PATCH", "DELETE"})
    assert writes == ["/video/v1/me/coins/daily", "/video/v1/videos/{vid}/coin"], writes


def test_video_flags_default_off_in_prod_on_in_dev(monkeypatch):
    from app.config import settings
    from app.services import flags

    monkeypatch.setattr(settings, "app_env", "prod")
    assert flags.video_flag_default() == "off", "生产缺省关:没拿到许可证之前不能不经意地打开"
    for env in ("staging", "", "Prod", "dev "):
        monkeypatch.setattr(settings, "app_env", env)
        assert flags.video_flag_default() == ("on" if env.strip().lower() == "dev" else "off"), env
    monkeypatch.setattr(settings, "app_env", "dev")
    assert flags.video_flag_default() == "on"
    assert set(flags.VIDEO_FLAGS) == {"video_enabled", "video_upload_enabled"}


def test_video_flags_are_known_to_the_admin_console():
    from app.routers.admin import _KNOWN_FLAGS
    assert {"video_enabled", "video_upload_enabled"} <= _KNOWN_FLAGS


def test_upload_routes_are_gated_by_the_upload_flag():
    """建稿、加分 P、提交挂在「视频投稿」开关上(整个模块挂在「视频功能」上)。"""
    gated = set()
    for r in _video_routes():
        deps = {getattr(d.call, "__name__", "") for d in r.dependant.dependencies}
        if "upload_on" in deps:
            gated.add(r.path)
        if r.path.startswith("/video/v1"):
            assert "video_on" in deps, f"{r.path} 没挂视频开关"
    assert gated == {"/video/v1/uploads/videos", "/video/v1/videos/{vid}/parts",
                     "/video/v1/videos/{vid}/submit"}, gated
