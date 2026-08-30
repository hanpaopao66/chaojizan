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
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (Merchant, Order, OrderStatus, RiderProfile, User,
                      UserRole)
from ..security import (get_current_user, get_current_user_optional,
                        require_role)
from ..services import storage
from ..services.storage import PRIVATE_DIR, UPLOAD_DIR

router = APIRouter(tags=["上传"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_SIZE = 5 * 1024 * 1024  # 5MB

# HEIF 家族的 ftyp brand(iPhone 相册默认格式)。判格式看**内容**不看文件名:
# 商家把 HEIC 改名成 .jpg 骗过后缀检查后,存进去的是所有浏览器都打不开的图
_HEIF_BRANDS = {b"heic", b"heix", b"heif", b"hevc", b"mif1", b"msf1"}


def _sniff_ext(data: bytes) -> str | None:
    """按魔数识别图片真实格式;认不出返回 None(回退到文件名后缀)。"""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) > 12 and data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return ".heic"
    return None


def _heic_to_jpeg(data: bytes) -> bytes:
    """iPhone 的 HEIC 转 JPEG 再入库,商家不用知道格式这回事。
    依赖装不上时给明确指引而不是 500。"""
    try:
        from io import BytesIO

        import pillow_heif
        from PIL import Image

        pillow_heif.register_heif_opener()
        img = Image.open(BytesIO(data))
        out = BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=90)
        return out.getvalue()
    except ImportError:
        raise HTTPException(
            422, "暂不支持 HEIC 格式,请在相册设置里改用「最兼容」格式,"
                 "或换一张 jpg / png 图片")
    except Exception:
        raise HTTPException(422, "图片解析失败,请换一张 jpg / png 图片重试")


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    # **没有默认值**:调用方必须显式声明用途。让它猜一个"安全默认"看似稳妥,
    # 但猜错的那一次就是一张身份证进了公开桶
    purpose: str = Form(...),
    # 商家传菜品/门头照,骑手传证件照,用户传头像,管理员传开屏运营图
    user: User = Depends(require_role("merchant", "rider", "customer", "admin")),
):
    try:
        private = storage.is_private(purpose)
    except KeyError:
        raise HTTPException(
            422, f"未知的图片用途 {purpose!r};"
                 f"可用:{'/'.join(sorted(storage.PURPOSES))}")
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(413, "图片不能超过 5MB")
    ext = _sniff_ext(data)
    if ext == ".heic":
        data = _heic_to_jpeg(data)
        ext = ".jpg"
        # HEIC 压缩率比 JPEG 高一截,转码后可能反超 5MB 上限 ——
        # 入库前再查一遍,别让"合规的原图"变出一个超限的存量文件
        if len(data) > MAX_SIZE:
            raise HTTPException(413, "图片转换后超过 5MB,请压缩后重试")
    if ext is None:
        # **认不出就拒绝,不回退到文件名后缀。**
        #
        # 原来这里是 `ext = Path(file.filename).suffix.lower()` —— 而文件名
        # 是攻击者可控的。白名单里那三种(jpg/png/webp)加 heic 全都嗅得出来,
        # 所以这条回退**只可能放进非图片**:传一个内容是 HTML 的 evil.jpg,
        # 魔数认不出 → 用文件名的 .jpg → 过白名单 → 存进公开桶。
        #
        # 现代浏览器不会把 image/jpeg 嗅成 HTML,所以它不是一条可用的
        # 利用链;但让任意字节以图片扩展名躺在平台域名下,本身没有任何好处。
        raise HTTPException(
            422, "认不出这是图片(只支持 jpg / png / webp / heic)")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(422, "仅支持 jpg / png / webp 图片")
    try:
        stored = storage.save(data, ext, purpose, uploader_id=user.id)
    except storage.StorageError as e:
        # 明确失败,不静默退回本地磁盘:一半文件在桶里一半在磁盘上,事后对不齐
        raise HTTPException(503, f"图片存储暂时不可用,请稍后重试({e})")
    return {"url": stored.url, "private": private}


# 「上传者本人可读」不适用的用途:**这一类另有归属规则,上传者不在其中**。
#
# delivery_proof 拍的是别人家门口,归属是「该订单的顾客」,骑手拍完就该看不到。
# 用排除法而不是白名单:incident / after_sale / food_safety 这几类在库里
# 没有任何一行引用它们(工单正文里存的是 URL 文本),白名单会把上传者
# 自己的事故照、售后凭证一起锁死 —— 修一个洞不能顺手废掉三个功能。
_NOT_SELF_PURPOSES = {"delivery_proof"}


def _key_parts(ref: str) -> tuple[str, str]:
    """把 `{purpose}/{name}` 拆开。老文件是平铺的裸文件名,拆出来 purpose 为空。

    **只认两段**:`id_card/u5-abc.jpg` 这种。多一段就是拼出来的路径,
    一律当成认不出(见 _may_read_private 末尾那条注释)。
    """
    parts = ref.strip("/").split("/")
    return (parts[0], parts[1]) if len(parts) == 2 else ("", "")


def _purpose_of(ref: str) -> str:
    return _key_parts(ref)[0]


def _uploader_of(ref: str) -> int | None:
    """从 key 的首个 owner 段解析上传者 id;认不出返回 None。"""
    import re
    m = re.match(r"^u(\d+)-", _key_parts(ref)[1])
    return int(m.group(1)) if m else None


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

    # 营业执照/特种行业许可证:店主。店员不给 —— 资质材料不是接单要用的东西。
    # 进件资料(#203)的三张图一并算进来:上传者本人那条通路只在
    # 「同一个账号传的」时候成立,连锁换人操作或换设备重登后就不成立了,
    # 表现是收款资料页的证件照全部破图
    if await db.scalar(select(Merchant.id).where(
            Merchant.owner_id == user.id,
            Merchant.license_image_url.contains(ref)
            | Merchant.business_license_image_url.contains(ref)
            | Merchant.legal_person_id_front_url.contains(ref)
            | Merchant.legal_person_id_back_url.contains(ref))):
        return True

    # 酒店的第二证照落在 HotelProfile 上,单独查(否则店主看不了自己的证)
    from ..models import HotelProfile
    if await db.scalar(
            select(HotelProfile.merchant_id)
            .join(Merchant, Merchant.id == HotelProfile.merchant_id)
            .where(Merchant.owner_id == user.id,
                   HotelProfile.special_license_image_url.contains(ref)
                   | HotelProfile.hygiene_image_url.contains(ref))):
        return True

    # 送达留证:只有该订单的顾客。骑手拍完就不该再看得到 ——
    # 那是别人家门口的照片,拍摄者没有持续查看的正当理由
    if await db.scalar(select(Order.id).where(
            Order.customer_id == user.id,
            Order.delivery_photo_url.contains(ref))):
        return True

    # 发货照(零售):**三方都要看得到,但各有各的理由**。
    #
    #   顾客   —— 纠纷时是他在主张"少给了",不给他看等于让他空口说
    #   该店   —— 是他拍的、拍的是他自己柜台上的货
    #   骑手   —— 取货时照着核对。**只在这单还在他手上时** ——
    #             送完就没有继续看的理由了,而照片说明这个人买了什么
    #             (买药、买成人用品都在这一类里)
    #
    # 和送达留证那条的差别:那张拍的是别人家门口,所以拍摄者(骑手)
    # 拍完就该看不到;这张拍的是商家自己的货,所以商家可以一直看。
    if await db.scalar(select(Order.id).where(
            Order.handover_photo_url.contains(ref),
            or_(Order.customer_id == user.id,
                Order.merchant_id.in_(
                    select(Merchant.id).where(Merchant.owner_id == user.id)),
                and_(Order.rider_id == user.id,
                     Order.status.notin_((OrderStatus.COMPLETED,
                                          OrderStatus.CANCELLED)))))):
        return True

    # 上传者本人:key 里编着 u{id}-(见 storage._new_key)。
    # 入驻/认证表单在「上传成功」到「提交落库」之间,文件不被任何行引用,
    # 只按归属判权会让上传者自己都看不了刚传的证照(缩略图破图、OCR 失效)。
    #
    # **放在最后,而且只对表单类用途生效**,两条都是必需的:
    #   - 原先它排在最前面,于是「送达留证只给该单顾客」那条整个失效 ——
    #     照片是骑手传的,他永远先命中这一条,能长期回看别人家门口;
    #   - 原先是裸子串 `f"/u{user.id}-" in f"/{ref}"`,路径里任意位置
    #     出现 /u5- 就放行,下面按归属查库的分支一条都不执行。
    #     现在只认 key 的**首个 owner 段**。
    return (_uploader_of(ref) == user.id
            and _purpose_of(ref) not in _NOT_SELF_PURPOSES)


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
    # nosniff:告诉浏览器别拿内容去猜类型。上面已经保证入库的都是真图片,
    # 这一条是第二道 —— 存量里可能还有走过老回退路径的文件
    return Response(data, media_type=media,
                    headers={"Cache-Control": "public, max-age=604800",
                             "X-Content-Type-Options": "nosniff"})


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
