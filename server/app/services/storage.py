"""对象存储抽象层(#124/#125)。

**为什么要有这一层**:原先所有上传都落 server/uploads/ 并由 StaticFiles
无鉴权直出 —— 菜品图和骑手身份证在同一个目录、同一套公开 URL。
UUID4 不可枚举所以扫不到,但 URL 一旦泄露(截图/日志/Referer/转发)
就是永久可访问且无法撤销。对证件照这个级别不够。

于是按**用途**硬分两类,这是这个模块存在的全部理由:

- `public`  菜品图 / 门头照 / 门店相册 / 开屏图 → 公开桶,可缓存,直出;
- `private` 身份证 / 健康证 / 营业执照 / 送达留证 → 私密桶,
            **任何静态托管都不许直出**,只能走 `GET /files/{key}`
            由服务端判权后回读。

后端可切(`STORAGE_BACKEND=local|minio`):local 给本地开发用,
生产用 minio。**local 不是生产的过渡态** —— 生产直接切 minio。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import settings

# 用途 → 是否私密。**没有默认值**:调用方必须显式声明用途。
# 让调用方猜一个"安全默认"看似稳妥,但猜错的那一次就是一张身份证进了公开桶
PURPOSES: dict[str, bool] = {
    # ---- 公开:本来就是给所有人看的 ----
    "dish": False,          # 菜品图
    "shop": False,          # 门头照 / 店铺 logo
    "gallery": False,       # 门店相册
    "room": False,          # 住宿房型图
    "splash": False,        # 开屏运营图
    "avatar": False,        # 用户头像
    "review": False,        # 评价配图(评价本身就是公开的)
    "miniapp_icon": False,  # 小程序图标、截图:详情页公开展示
    "miniapp_shot": False,
    # 消息与视频(DEV-PROMPTS-40)。聊天媒体**不走这里**:它们在 media_files 里、一律私密
    "link_preview": False,  # 链接预览的配图:取自公开网页的 og:image,由服务端代取(不让客户端直连第三方)
    "sticker": False,       # 贴纸:发出去就是给会话里所有人看的
    "chat_photo": False,    # 群 / 频道头像
    "video_cover": False,   # 视频封面、雪碧图(视频本身在私密桶,判权后播放)

    # ---- 私密:泄露了会伤到具体的人 ----
    "id_card": True,        # 身份证
    "health_cert": True,    # 健康证
    "license": True,        # 营业执照 / 特种行业许可证
    "delivery_proof": True, # 送达拍照留证(拍的是别人家门口)
    # 发货照(零售):商家拣完货拍的。是商品不是住处,但**照片会说明
    # 这个人买了什么** —— 买药、买成人用品都在这一类里,所以进私密桶
    "handover_proof": True,
    "incident": True,       # 骑手事故/配送异常现场照
    "after_sale": True,     # 售后凭证照
    # 食安投诉可附**医疗凭证** —— 医疗健康信息在个保法下属于敏感个人信息,
    # 这一类比身份证更不能公开直出
    "food_safety": True,
    # 小程序举报截图(#332):截的是举报人自己手机上的画面,可能带着别的通知、
    # 聊天内容;只给举报人和审核员看,**不给被举报的开发者**
    "miniapp_report": True,
    # 开发者企业认证的营业执照(#329):和商家的执照同一类材料
    "dev_license": True,
}

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = SERVER_DIR / "uploads"
# 私密文件放 uploads **之外**:光靠"路径没人猜得到"不算隔离,
# 得让它根本不在 StaticFiles 挂载的那棵树下
PRIVATE_DIR = SERVER_DIR / "private_uploads"

PUBLIC_BUCKET = "superz-public"
PRIVATE_BUCKET = "superz-private"


class StorageError(RuntimeError):
    """存储不可用。**绝不静默降级到本地磁盘** —— 那会让一半文件在桶里
    一半在磁盘上,事后根本对不齐。宁可这次上传明确失败。"""


@dataclass(frozen=True)
class Stored:
    key: str          # 桶内对象名(也是 local 后端的文件名)
    private: bool
    url: str          # 写进数据库的地址


def is_private(purpose: str) -> bool:
    if purpose not in PURPOSES:
        raise KeyError(purpose)
    return PURPOSES[purpose]


def _new_key(purpose: str, ext: str, uploader_id: int | None = None) -> str:
    """key 带用途前缀:出了事一眼看得出哪类文件,也便于按前缀做策略。

    再编入上传者(u{id}-):私密文件在「上传成功」到「提交表单落库」之间
    不被任何 DB 行引用,按归属判权必 403 —— 入驻表单的证照缩略图会破图,
    OCR 在唯一被设计的场景里永远失败。key 里带上传者,判权多一条
    「本人可读」的通路,且不用为此加表。"""
    owner = f"u{uploader_id}-" if uploader_id else ""
    return f"{purpose}/{owner}{uuid.uuid4().hex}{ext}"


# ---------------- local 后端(本地开发) ----------------
class LocalBackend:
    name = "local"

    def put(self, data: bytes, key: str, private: bool) -> None:
        base = PRIVATE_DIR if private else UPLOAD_DIR
        path = base / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str, private: bool) -> bytes | None:
        base = PRIVATE_DIR if private else UPLOAD_DIR
        path = base / key
        if not path.exists():
            # 兼容老数据:早期文件是平铺在 uploads/ 根下的裸文件名
            legacy = UPLOAD_DIR / Path(key).name
            if legacy.exists():
                return legacy.read_bytes()
            return None
        return path.read_bytes()

    def exists(self, key: str, private: bool) -> bool:
        return self.get(key, private) is not None


# ---------------- minio 后端(生产) ----------------
class MinioBackend:
    name = "minio"

    def __init__(self) -> None:
        from minio import Minio

        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    def _bucket(self, private: bool) -> str:
        return PRIVATE_BUCKET if private else PUBLIC_BUCKET

    def put(self, data: bytes, key: str, private: bool) -> None:
        from io import BytesIO

        from minio.error import S3Error

        try:
            self._client.put_object(
                self._bucket(private), key, BytesIO(data), len(data))
        except S3Error as e:
            raise StorageError(f"对象存储写入失败:{e.code}") from e
        except Exception as e:  # 连不上等
            raise StorageError(f"对象存储不可用:{type(e).__name__}") from e

    def get(self, key: str, private: bool) -> bytes | None:
        from minio.error import S3Error

        resp = None
        try:
            resp = self._client.get_object(self._bucket(private), key)
            return resp.read()
        except S3Error as e:
            if e.code in ("NoSuchKey", "NoSuchBucket"):
                return None
            raise StorageError(f"对象存储读取失败:{e.code}") from e
        except Exception as e:
            raise StorageError(f"对象存储不可用:{type(e).__name__}") from e
        finally:
            if resp is not None:
                resp.close()
                resp.release_conn()

    def exists(self, key: str, private: bool) -> bool:
        from minio.error import S3Error

        try:
            self._client.stat_object(self._bucket(private), key)
            return True
        except S3Error:
            return False
        except Exception as e:
            raise StorageError(f"对象存储不可用:{type(e).__name__}") from e


_backend: LocalBackend | MinioBackend | None = None


def backend() -> LocalBackend | MinioBackend:
    global _backend
    if _backend is None:
        _backend = (MinioBackend() if settings.storage_backend == "minio"
                    else LocalBackend())
    return _backend


def reset_backend() -> None:
    """测试用:切换 STORAGE_BACKEND 后重建。"""
    global _backend
    _backend = None


def url_for(key: str, private: bool) -> str:
    """写进数据库的地址。

    公开类走 `/img/{key}` —— 生产由 nginx 反代到 public 桶并设长缓存;
    私密类走 `/files/{key}`,那是唯一出口,每次访问都要过鉴权。
    两类都是**相对路径**:换域名、换 CDN 都不用动库里的存量数据。
    """
    return f"/files/{key}" if private else f"/img/{key}"


def save(data: bytes, ext: str, purpose: str,
         uploader_id: int | None = None) -> Stored:
    private = is_private(purpose)
    key = _new_key(purpose, ext, uploader_id)
    backend().put(data, key, private)
    return Stored(key=key, private=private, url=url_for(key, private))


def read(key: str, private: bool) -> bytes | None:
    return backend().get(key, private)


# ---------------- 大文件(DEV-PROMPTS-40 #341):按路径写、按区间读 ----------------
#
# 聊天视频、视频投稿动辄几百 MB,不能像图片那样整块读进内存再 put。
# 下面这几个函数给 media 服务用:落盘的文件直接传、下载按 Range 一段段读。
# 用途判定(公开 / 私密)仍由调用方显式给,和上面 save() 同一个原则:没有默认值。

CHUNK = 1024 * 1024


def _local_path(key: str, private: bool) -> Path:
    base = PRIVATE_DIR if private else UPLOAD_DIR
    path = (base / key).resolve()
    if not path.is_relative_to(base.resolve()):
        raise StorageError("非法的存储路径")
    return path


def put_path(src: Path, key: str, private: bool, content_type: str = "") -> None:
    b = backend()
    if isinstance(b, MinioBackend):
        from minio.error import S3Error
        try:
            b._client.fput_object(b._bucket(private), key, str(src),
                                  content_type=content_type or "application/octet-stream")
        except S3Error as e:
            raise StorageError(f"对象存储写入失败:{e.code}") from e
        except Exception as e:
            raise StorageError(f"对象存储不可用:{type(e).__name__}") from e
        return
    dst = _local_path(key, private)
    dst.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copyfile(src, dst)


def stat_size(key: str, private: bool) -> int | None:
    b = backend()
    if isinstance(b, MinioBackend):
        from minio.error import S3Error
        try:
            return b._client.stat_object(b._bucket(private), key).size
        except S3Error:
            return None
        except Exception as e:
            raise StorageError(f"对象存储不可用:{type(e).__name__}") from e
    p = _local_path(key, private)
    return p.stat().st_size if p.exists() else None


def read_range(key: str, private: bool, start: int, length: int) -> bytes:
    """读 [start, start+length) 这一段。给 Range 下载用,一次最多读一个 CHUNK 的量级。"""
    b = backend()
    if isinstance(b, MinioBackend):
        from minio.error import S3Error
        resp = None
        try:
            resp = b._client.get_object(b._bucket(private), key, offset=start, length=length)
            return resp.read()
        except S3Error as e:
            raise StorageError(f"对象存储读取失败:{e.code}") from e
        except Exception as e:
            raise StorageError(f"对象存储不可用:{type(e).__name__}") from e
        finally:
            if resp is not None:
                resp.close()
                resp.release_conn()
    with open(_local_path(key, private), "rb") as f:
        f.seek(start)
        return f.read(length)


def download_to(key: str, private: bool, dst: Path) -> None:
    b = backend()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(b, MinioBackend):
        from minio.error import S3Error
        try:
            b._client.fget_object(b._bucket(private), key, str(dst))
        except S3Error as e:
            raise StorageError(f"对象存储读取失败:{e.code}") from e
        except Exception as e:
            raise StorageError(f"对象存储不可用:{type(e).__name__}") from e
        return
    import shutil
    shutil.copyfile(_local_path(key, private), dst)


def remove(key: str, private: bool) -> None:
    if not key:
        return
    b = backend()
    if isinstance(b, MinioBackend):
        try:
            b._client.remove_object(b._bucket(private), key)
        except Exception:
            pass
        return
    try:
        _local_path(key, private).unlink(missing_ok=True)
    except StorageError:
        pass


def presigned_get(key: str, private: bool, seconds: int = 120) -> str | None:
    """生产上 nginx 直出大文件用(X-Accel-Redirect 带着预签名参数去 MinIO 取)。本地后端没有。"""
    b = backend()
    if not isinstance(b, MinioBackend):
        return None
    from datetime import timedelta
    return b._client.presigned_get_object(b._bucket(private), key,
                                          expires=timedelta(seconds=seconds))
