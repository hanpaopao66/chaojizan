"""图片上传(菜品图/门头照/证照)。

MVP 存本地磁盘、由 FastAPI 静态托管,返回相对路径 /uploads/xxx.jpg。
上量后换对象存储(OSS/七牛):改这一个文件,返回的 URL 结构不变。
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..models import User
from ..security import require_role

router = APIRouter(tags=["上传"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    # 商家传菜品/门头照,骑手传证件照,用户传头像,管理员传开屏运营图
    user: User = Depends(require_role("merchant", "rider", "customer", "admin")),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(422, "仅支持 jpg / png / webp 图片")
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(413, "图片不能超过 5MB")
    UPLOAD_DIR.mkdir(exist_ok=True)
    name = uuid.uuid4().hex + ext
    (UPLOAD_DIR / name).write_bytes(data)
    return {"url": f"/uploads/{name}"}
