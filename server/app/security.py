import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw.encode(), hashed.encode())


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": int(time.time()) + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期,请重新登录")
    user = await db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    if user.phone.startswith("del"):  # 已注销(匿名化标记),旧 token 立即失效
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号已注销")
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """未登录返回 None 而不是 401。

    只给「同一个路径既服务公开内容也服务私密内容」的地方用
    (目前是 /uploads 老 URL 兼容):公开文件不该因为没带 token 就 401,
    私密文件再由调用方自己判 None 并抛 401。
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


def require_role(*roles: str):
    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "当前角色无权访问")
        return user

    return checker
