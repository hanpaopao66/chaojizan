"""小程序:清单 + initData 签发(#277,Telegram 模式)。

小程序就是网页:清单告诉客户端「有哪些、入口在哪、桥对哪些域名生效」;
initData 告诉小程序后端「这确实是超级赞 App 里的这个用户」。
签名协议在 services/mini_app.py 的 docstring,那就是第三方的对接文档。

边界(DEV-PROMPTS-31 定死):登录 token 永远不进 WebView;
清单顺序是运营拍的 sort,不做推荐;第三方入驻未开放,管理接口只给 admin。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import MiniApp, User
from ..schemas import MiniAppIn, MiniAppOut
from ..security import get_current_user, require_role
from ..services.mini_app import sign_init_data

router = APIRouter(prefix="/mini-apps", tags=["小程序"])


@router.get("", response_model=list[MiniAppOut])
async def list_mini_apps(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下拉面板的数据源:只回上架条目。空清单时客户端不呼出面板。"""
    rows = await db.scalars(
        select(MiniApp).where(MiniApp.status == "on").order_by(MiniApp.sort, MiniApp.id)
    )
    return rows.all()


@router.post("/{app_id}/init-data")
async def issue_init_data(
    app_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """给「当前用户 × 这一个小程序」签一份身份包,客户端经桥透传给页面。

    时效分钟级(services/mini_app.py 的 MAX_AGE_SECONDS),页面要长会话
    自己换 —— 平台不给长期凭据,泄露面就只有这几分钟。
    """
    app = await db.get(MiniApp, app_id)
    if app is None or app.status != "on":
        raise HTTPException(404, "小程序不存在或已下架")
    return sign_init_data(app.id, user.id, user.name or "用户")


# ---- 管理(admin.html 面板以后再挂,先保证 curl 能管) ----


@router.get("/admin", response_model=list[MiniAppOut])
async def admin_list(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """管理侧看全量(含下架),仍复用 MiniAppOut —— status 用下面的 toggle 管。"""
    rows = await db.scalars(select(MiniApp).order_by(MiniApp.sort, MiniApp.id))
    return rows.all()


@router.post("/admin", response_model=MiniAppOut)
async def admin_create(
    body: MiniAppIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    app = MiniApp(**body.model_dump())
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


@router.put("/admin/{app_id}", response_model=MiniAppOut)
async def admin_update(
    app_id: int,
    body: MiniAppIn,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    app = await db.get(MiniApp, app_id)
    if app is None:
        raise HTTPException(404, "小程序不存在")
    for k, v in body.model_dump().items():
        setattr(app, k, v)
    await db.commit()
    await db.refresh(app)
    return app


@router.post("/admin/{app_id}/toggle")
async def admin_toggle(
    app_id: int,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    app = await db.get(MiniApp, app_id)
    if app is None:
        raise HTTPException(404, "小程序不存在")
    app.status = "off" if app.status == "on" else "on"
    await db.commit()
    return {"id": app.id, "status": app.status}
