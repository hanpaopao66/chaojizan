"""小程序云存储 CloudStorage(#325,DEV-PROMPTS-39 §5.5)。

作用域是(应用, 用户):A 应用永远读不到 B 应用的数据;开发者服务端不能直读(I8)——
这里的每个函数都要同时给 app_id 和 user_id,调用方只有宿主代用户发起的请求。

- 键 ^[A-Za-z0-9_.:-]{1,128}$;值为字符串,UTF-8 ≤ 65,536 字节;
- 配额:每个(应用, 用户)≤ 1024 个键、键 + 值总计 ≤ 5 MB;
- 每个键带单调递增的 rev;set 带 if_rev 时版本不符回 REV_CONFLICT(4007);
  if_rev=0 表示「这个键必须还不存在」;
- 配额在 mini_app_kv_usage 那一行上 FOR UPDATE 维护,同一个用户并发写不会一起越过上限。
"""
import re

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MiniAppKV, MiniAppKVUsage

KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
MAX_VALUE_BYTES = 65536
MAX_KEYS = 1024
MAX_TOTAL_BYTES = 5 * 1024 * 1024
MAX_BATCH = 100
RATE_PER_MINUTE = 120


class KVError(Exception):
    """桥错误码见 DEV-PROMPTS-39 §5.4:4004 参数、4006 配额、4007 版本冲突。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _check_key(key: str) -> None:
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise KVError(4004, "键只能是 1–128 个字母、数字或 _ . : -")


def _value_bytes(value: str) -> int:
    if not isinstance(value, str):
        raise KVError(4004, "值必须是字符串(对象请先 JSON.stringify)")
    n = len(value.encode("utf-8"))
    if n > MAX_VALUE_BYTES:
        raise KVError(4004, f"单个值 {n} 字节,超过上限 {MAX_VALUE_BYTES}")
    return n


def _keys(keys) -> list[str]:
    if not isinstance(keys, list) or not keys:
        raise KVError(4004, "keys 要是非空数组")
    if len(keys) > MAX_BATCH:
        raise KVError(4004, f"一次最多 {MAX_BATCH} 个键")
    for k in keys:
        _check_key(k)
    return list(dict.fromkeys(keys))


async def _lock_usage(db: AsyncSession, app_id: int, user_id: int) -> MiniAppKVUsage:
    await db.execute(insert(MiniAppKVUsage).values(
        app_id=app_id, user_id=user_id, keys=0, bytes=0).on_conflict_do_nothing())
    return (await db.execute(select(MiniAppKVUsage).where(
        MiniAppKVUsage.app_id == app_id, MiniAppKVUsage.user_id == user_id
    ).with_for_update())).scalar_one()


async def get_items(db: AsyncSession, app_id: int, user_id: int, keys) -> dict:
    ks = _keys(keys)
    rows = (await db.execute(select(MiniAppKV).where(
        MiniAppKV.app_id == app_id, MiniAppKV.user_id == user_id,
        MiniAppKV.key.in_(ks)))).scalars().all()
    found = {r.key: {"value": r.value, "rev": r.rev} for r in rows}
    return {k: found.get(k) for k in ks}


async def set_item(db: AsyncSession, app_id: int, user_id: int, key: str, value: str,
                   if_rev: int | None = None) -> dict:
    _check_key(key)
    vbytes = _value_bytes(value)
    if if_rev is not None and (not isinstance(if_rev, int) or if_rev < 0):
        raise KVError(4004, "ifRev 要是非负整数")
    usage = await _lock_usage(db, app_id, user_id)
    row = (await db.execute(select(MiniAppKV).where(
        MiniAppKV.app_id == app_id, MiniAppKV.user_id == user_id, MiniAppKV.key == key
    ).with_for_update())).scalar_one_or_none()
    if if_rev is not None:
        current = row.rev if row else 0
        if current != if_rev:
            raise KVError(4007, f"版本号不符:现在是 {current},你带的是 {if_rev}")
    size = len(key) + vbytes
    new_keys = usage.keys + (0 if row else 1)
    new_bytes = usage.bytes - (row.bytes if row else 0) + size
    if new_keys > MAX_KEYS:
        raise KVError(4006, f"键数到上限 {MAX_KEYS} 了")
    if new_bytes > MAX_TOTAL_BYTES:
        raise KVError(4006, "云存储满了(上限 5 MB)")
    if row:
        row.value = value
        row.bytes = size
        row.rev += 1
        rev = row.rev
    else:
        db.add(MiniAppKV(app_id=app_id, user_id=user_id, key=key, value=value,
                         bytes=size, rev=1))
        rev = 1
    usage.keys = new_keys
    usage.bytes = new_bytes
    await db.commit()
    return {"key": key, "rev": rev}


async def remove_items(db: AsyncSession, app_id: int, user_id: int, keys) -> dict:
    ks = _keys(keys)
    usage = await _lock_usage(db, app_id, user_id)
    rows = (await db.execute(select(MiniAppKV).where(
        MiniAppKV.app_id == app_id, MiniAppKV.user_id == user_id,
        MiniAppKV.key.in_(ks)).with_for_update())).scalars().all()
    for r in rows:
        usage.keys -= 1
        usage.bytes -= r.bytes
        await db.delete(r)
    await db.commit()
    return {"removed": len(rows)}


async def get_keys(db: AsyncSession, app_id: int, user_id: int, *, prefix: str = "",
                   cursor: str = "", limit: int = 500) -> dict:
    if prefix and not re.match(r"^[A-Za-z0-9_.:-]{1,128}$", prefix):
        raise KVError(4004, "prefix 格式不对")
    limit = max(1, min(int(limit or 500), 1000))
    stmt = select(MiniAppKV.key).where(
        MiniAppKV.app_id == app_id, MiniAppKV.user_id == user_id)
    if prefix:
        stmt = stmt.where(MiniAppKV.key.startswith(prefix, autoescape=True))
    if cursor:
        stmt = stmt.where(MiniAppKV.key > cursor)
    keys = list((await db.execute(stmt.order_by(MiniAppKV.key).limit(limit + 1))).scalars())
    more = len(keys) > limit
    keys = keys[:limit]
    return {"keys": keys, "next_cursor": keys[-1] if more else None}


async def usage(db: AsyncSession, app_id: int, user_id: int) -> dict:
    row = await db.get(MiniAppKVUsage, (app_id, user_id))
    return {"keys": row.keys if row else 0, "bytes": row.bytes if row else 0,
            "max_keys": MAX_KEYS, "max_bytes": MAX_TOTAL_BYTES}


async def export(db: AsyncSession, app_id: int, user_id: int) -> dict:
    rows = (await db.execute(select(MiniAppKV).where(
        MiniAppKV.app_id == app_id, MiniAppKV.user_id == user_id
    ).order_by(MiniAppKV.key))).scalars().all()
    return {r.key: r.value for r in rows}


async def clear(db: AsyncSession, app_id: int, user_id: int) -> int:
    n = (await db.execute(select(func.count()).select_from(MiniAppKV).where(
        MiniAppKV.app_id == app_id, MiniAppKV.user_id == user_id))).scalar_one()
    await db.execute(delete(MiniAppKV).where(
        MiniAppKV.app_id == app_id, MiniAppKV.user_id == user_id))
    await db.execute(delete(MiniAppKVUsage).where(
        MiniAppKVUsage.app_id == app_id, MiniAppKVUsage.user_id == user_id))
    await db.commit()
    return n
