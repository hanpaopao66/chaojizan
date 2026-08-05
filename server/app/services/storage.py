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

    # ---- 私密:泄露了会伤到具体的人 ----
    "id_card": True,        # 身份证
    "health_cert": True,    # 健康证
    "license": True,        # 营业执照 / 特种行业许可证
    "delivery_proof": True, # 送达拍照留证(拍的是别人家门口)
    "incident": True,       # 骑手事故/配送异常现场照
    "after_sale": True,     # 售后凭证照
    # 食安投诉可附**医疗凭证** —— 医疗健康信息在个保法下属于敏感个人信息,
    # 这一类比身份证更不能公开直出
    "food_safety": True,
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
