"""证照 OCR 识别(入驻表单自动填充,预留)。

默认**未启用**:`OCR_ENDPOINT` 留空时接口返回 `{"enabled": false}`,
客户端静默跳过 —— OCR 只是省几下手输,不是入驻流程的一环,
识别服务挂了/没配,商家照样手填提交。

启用方式:本地模型起一个 HTTP 服务,`.env` 配 `OCR_ENDPOINT` 指过去。
**对接契约**(识别服务需实现,字段认不出可缺省):

    POST {OCR_ENDPOINT}
    请求 JSON: {"image_b64": "<base64 编码的 jpg/png>", "kind": "license"}
    响应 JSON: {"license_no": "统一社会信用代码/许可证号", "name": "主体名称"}

安全口径:入参是**已上传文件的站内相对 URL**(/files/... 或 /img/...),
不接受外部地址;私密文件先过 `_may_read_private` 判权 ——
否则任何商家都能拿别人证件照的 key 来「OCR 抽取」他人身份信息。
"""
import base64

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import User
from ..security import require_role
from ..services import storage
from .uploads import _may_read_private

router = APIRouter(prefix="/ocr", tags=["证照识别"])


class OcrIn(BaseModel):
    image_url: str = Field(max_length=300)  # /upload 返回的站内相对路径


def _split_key(image_url: str) -> tuple[str, bool] | None:
    """站内相对 URL → (存储 key, 是否私密);不认识的地址返回 None。"""
    for prefix, private in (("/files/", True), ("/img/", False)):
        if image_url.startswith(prefix):
            return image_url[len(prefix):], private
    return None


@router.post("/license")
async def ocr_license(
    payload: OcrIn,
    user: User = Depends(require_role("merchant")),
    db: AsyncSession = Depends(get_db),
):
    if not settings.ocr_configured:
        return {"enabled": False, "ok": False}

    parsed = _split_key(payload.image_url)
    if parsed is None:
        raise HTTPException(422, "只支持识别本站上传的图片")
    key, private = parsed
    if ".." in key or key.startswith("/"):
        raise HTTPException(400, "非法路径")
    if private and not await _may_read_private(key, user, db):
        raise HTTPException(403, "没有查看这个文件的权限")

    try:
        data = storage.read(key, private=private)
    except storage.StorageError:
        return {"enabled": True, "ok": False}
    if data is None:
        raise HTTPException(404, "文件不存在")

    # 识别失败一律 ok=false 而不是抛错:客户端静默降级为手填
    try:
        import httpx

        async with httpx.AsyncClient(
                timeout=settings.ocr_timeout_seconds) as client:
            resp = await client.post(settings.ocr_endpoint, json={
                "image_b64": base64.b64encode(data).decode(),
                "kind": "license",
            })
            resp.raise_for_status()
            result = resp.json()
    except Exception:
        return {"enabled": True, "ok": False}

    return {
        "enabled": True,
        "ok": True,
        "license_no": str(result.get("license_no") or "")[:50],
        "name": str(result.get("name") or "")[:50],
    }
