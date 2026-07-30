"""图片上传与读取(#124)。

按**用途**分公开/私密两类,分别落不同的桶(或本地不同目录):

- 公开类(菜品图/门头照/相册/开屏/头像)→ `/img/{key}`,可缓存、可直出;
- 私密类(身份证/健康证/营业执照/送达留证)→ `/files/{key}`,
  **唯一出口就是本文件里的 private_file**,每次访问都要过鉴权。

老 URL `/uploads/{name}` 保留兼容:库里存的全是相对路径,批量改一旦要回滚就全乱。
命中私密清单的老文件不再直出,转到鉴权逻辑。
"""
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import Merchant, Order, RiderProfile, User, UserRole
from ..security import (get_current_user, get_current_user_optional,
                        require_role)
from ..services import storage
from ..services.storage import PRIVATE_DIR, UPLOAD_DIR

router = APIRouter(tags=["上传"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    # **没有默认值**:调用方必须显式声明用途。让它猜一个"安全默认"看似稳妥,
    # 但猜错的那一次就是一张身份证进了公开桶
    purpose: str = Form(...),
    # 商家传菜品/门头照,骑手传证件照,用户传头像,管理员传开屏运营图
    user: User = Depends(require_role("merchant", "rider", "customer", "admin")),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(422, "仅支持 jpg / png / webp 图片")
    try:
        private = storage.is_private(purpose)
    except KeyError:
        raise HTTPException(
            422, f"未知的图片用途 {purpose!r};"
                 f"可用:{'/'.join(sorted(storage.PURPOSES))}")
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(413, "图片不能超过 5MB")
    try:
        stored = storage.save(data, ext, purpose)
    except storage.StorageError as e:
        # 明确失败,不静默退回本地磁盘:一半文件在桶里一半在磁盘上,事后对不齐
        raise HTTPException(503, f"图片存储暂时不可用,请稍后重试({e})")
    return {"url": stored.url, "private": private}


async def _may_read_private(
    ref: str, user: User, db: AsyncSession
) -> bool:
    """私密文件判权。看的是「这个文件属于谁」,不是「这个人是什么角色」。

    ref 既可以是新版 key(`id_card/abc.jpg`),也可以是老文件名
    (`demo_idcard.jpg`)—— 库里存的老 URL 是 `/uploads/demo_idcard.jpg`,
    两种都用 contains 匹配得上。不按前缀分支,四类挨个查:
    这个接口调用频次极低,少一个分支就少一处能漏判的地方。
    """
    if user.role == UserRole.admin:
        return True                      # 审核要看

    # 骑手证件:只有本人
    if await db.scalar(select(RiderProfile.rider_id).where(
            RiderProfile.rider_id == user.id,
            (RiderProfile.id_card_photo_url.contains(ref))
            | (RiderProfile.health_cert_photo_url.contains(ref)))):
        return True

    # 营业执照/特种行业许可证:店主。店员不给 —— 资质材料不是接单要用的东西
    if await db.scalar(select(Merchant.id).where(
            Merchant.owner_id == user.id,
            Merchant.license_image_url.contains(ref))):
        return True

    # 送达留证:只有该订单的顾客。骑手拍完就不该再看得到 ——
    # 那是别人家门口的照片,拍摄者没有持续查看的正当理由
    if await db.scalar(select(Order.id).where(
            Order.customer_id == user.id,
            Order.delivery_photo_url.contains(ref))):
        return True

    return False


@router.get("/files/{key:path}")
async def private_file(
    key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """私密文件的唯一出口。权限不足给 403 而不是 404 ——
    这里没必要装作文件不存在,说清楚是权限问题反而少一轮排查。"""
    if ".." in key or key.startswith("/"):
        raise HTTPException(400, "非法路径")
    if not await _may_read_private(key, user, db):
        raise HTTPException(403, "没有查看这个文件的权限")
    try:
        data = storage.read(key, private=True)
    except storage.StorageError as e:
        raise HTTPException(503, f"存储暂时不可用({e})")
    if data is None:
        raise HTTPException(404, "文件不存在")
    media = mimetypes.guess_type(key)[0] or "application/octet-stream"
    # 私密文件不进任何缓存:CDN/代理缓存过一次,撤权就形同虚设
    return Response(data, media_type=media,
                    headers={"Cache-Control": "no-store, private"})


@router.get("/img/{key:path}")
async def public_file(key: str):
    """公开图片。生产由 nginx 反代到 public 桶直出,不会走到这里;
    本地开发(local 后端)和 nginx 未命中时由它兜底。"""
    if ".." in key or key.startswith("/"):
        raise HTTPException(400, "非法路径")
    try:
        data = storage.read(key, private=False)
    except storage.StorageError as e:
        raise HTTPException(503, f"存储暂时不可用({e})")
    if data is None:
        raise HTTPException(404, "文件不存在")
    media = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(data, media_type=media,
                    headers={"Cache-Control": "public, max-age=604800"})


@router.get("/uploads/{name:path}")
async def legacy_file(
    name: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """老 URL 兼容。库里存的全是 `/uploads/xxx.jpg` 这种相对路径,
    批量改一旦要回滚就全乱套 —— 所以路径不动,行为在这里分流。

    判定「是不是私密」不靠维护一份清单,靠**文件在哪**:
    迁移脚本把证照类挪进 private,挪过去的就得过鉴权。
    清单会和现实脱节,文件位置不会。
    """
    if ".." in name or name.startswith("/"):
        raise HTTPException(400, "非法路径")

    legacy_key = f"legacy/{name}"
    try:
        is_private_file = storage.backend().exists(legacy_key, private=True)
    except storage.StorageError as e:
        raise HTTPException(503, f"存储暂时不可用({e})")

    if is_private_file:
        if user is None:
            raise HTTPException(401, "请先登录")
        if not await _may_read_private(name, user, db):
            raise HTTPException(403, "没有查看这个文件的权限")
        data = storage.read(legacy_key, private=True)
        headers = {"Cache-Control": "no-store, private"}
    else:
        data = storage.read(name, private=False)
        headers = {"Cache-Control": "public, max-age=604800"}

    if data is None:
        raise HTTPException(404, "文件不存在")
    media = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Response(data, media_type=media, headers=headers)


__all__ = ["router", "UPLOAD_DIR", "PRIVATE_DIR"]
