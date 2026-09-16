"""设备推送地址的登记(#384)。

客户端拿到系统给的 device token 之后报上来,退出登录时报下去。
**不需要任何第三方**:苹果的 token 由系统发给 App,我们存下来直接发给苹果。

这里只有两条接口,故意做得很薄 —— 规矩都在 services/push_devices.py 里。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import User
from ..security import get_current_user
from ..services import push_devices

router = APIRouter(prefix="/push/v1", tags=["push"])


class DeviceIn(BaseModel):
    #: apns / hms / xiaomi / oppo / vivo / honor / jpush
    channel: str = Field(max_length=10)
    #: 系统给的 device token。苹果是 64 位十六进制,厂商的是各自的 regid
    token: str = Field(min_length=8, max_length=512)
    #: 哪个端 —— 决定推给哪个 bundle id / 包名
    app: str = Field(default="user", pattern="^(user|merchant|rider)$")
    #: APNs 的开发沙箱(Xcode / TestFlight 装的包)。发错环境收不到,所以由客户端如实报
    sandbox: bool = False


@router.post("/devices")
async def register_device(body: DeviceIn, me: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """登记这台设备。客户端每次启动都可以调,幂等。"""
    if body.channel not in push_devices.CHANNELS:
        # 打错一个字的后果是这台设备再也收不到推送,而接口会高高兴兴回 200。在入口就拦下
        raise HTTPException(422, f"不认识的推送通道:{body.channel}")
    row = await push_devices.register(db, me.id, channel=body.channel,
                                      token=body.token.strip(), app=body.app,
                                      sandbox=body.sandbox)
    await db.commit()
    return {"id": row.id, "channel": row.channel, "app": row.app}


class DeviceOut(BaseModel):
    channel: str = Field(max_length=10)
    token: str = Field(min_length=8, max_length=512)


@router.post("/devices/remove")
async def remove_device(body: DeviceOut, me: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """退出登录时下线这台设备。

    **不校验这台设备是不是你的**:token 是系统发给这台设备的,谁手里有它谁就在这台设备上。
    拿别人的 token 来下线,等于他自己把自己的推送关了 —— 换不来任何东西,
    而校验反而挡住了"上一个人没点退出就把手机给了别人"这种真实情况。
    """
    await push_devices.unregister(db, channel=body.channel, token=body.token.strip())
    await db.commit()
    return {"ok": True}
