"""导出我的数据(DEV-PROMPTS-40 S5「能导出自己的聊天记录(JSON + 媒体)和自己的投稿」)。

一次导出 = 后台打一个 zip,放进私密桶,记成一行 `media_files`(purpose=export、只有本人能下载,
判权走 media.can_read 的「owner 本人」那一条),下载走现有的 `/media/v1/files/{id}` 签名地址。

- 只导出**现在还读得到**的内容:在的会话、自己清空之前的不要、群里入群前看不到的不要、自己隐藏的不要
  —— 和客户端翻聊天记录看到的完全一样,导出不是绕过可见性规则的后门;
- 媒体按消息顺序往里放,**总量封顶 2GB**(和每天上传配额一个量级),超出的只在 JSON 里留名字和大小;
- 投稿:元数据 + 每 P 最高那档 mp4(同一个 2GB 里扣);
- 同一时间只跑一个;成功后 24 小时内不能再导出(导出很重,别拿它刷服务器);
- 只留最新一份,新的做好了把旧的删掉。

跑的状态放 Redis(`chat:export:<uid>`,只有 running / failed);做好的那份以库里的 media_files 为准。
"""
import asyncio
import json
import logging
import re
import shutil
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import and_, delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (ACTIVE_ROLES, Chat, ChatMember, ChatMessage, MediaFile, MessageHide,
                      SocialBlock, SocialContact, SocialProfile, User, Video, VideoPart)
from . import storage
from .chat_view import enrich_messages, now_utc, private_peer_id, visible_floor
from .media import signed_url
from .rt_events import append_user_event

logger = logging.getLogger("superz.export")

STATE_KEY = "chat:export:{uid}"
MEDIA_BUDGET = 2 * 1024 ** 3
COOLDOWN = timedelta(hours=24)
PAGE = 500
_RUNNING: set[int] = set()


async def _redis():
    from ..redis_client import get_redis
    return get_redis()


async def _get_state(uid: int) -> dict | None:
    try:
        raw = await (await _redis()).get(STATE_KEY.format(uid=uid))
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _set_state(uid: int, state: dict | None) -> None:
    try:
        r = await _redis()
        if state is None:
            await r.delete(STATE_KEY.format(uid=uid))
        else:
            await r.set(STATE_KEY.format(uid=uid), json.dumps(state), ex=6 * 3600)
    except Exception:
        logger.warning("写导出状态失败", exc_info=True)


async def latest_export(db: AsyncSession, uid: int) -> MediaFile | None:
    return await db.scalar(select(MediaFile).where(MediaFile.owner_id == uid,
                                                   MediaFile.purpose == "export")
                           .order_by(MediaFile.id.desc()).limit(1))


async def status(db: AsyncSession, uid: int) -> dict:
    """`GET /chat/v1/export`:running / failed / ready / none,ready 时带下载地址。"""
    st = await _get_state(uid)
    if st and st.get("state") == "running" and uid not in _RUNNING and \
            now_utc().timestamp() - st.get("started", 0) > 3600:
        st = {"state": "failed", "error": "导出中断了,重新开始一次"}  # 进程重启丢了任务
    mf = await latest_export(db, uid)
    ready = None
    if mf is not None:
        ready = {"media_id": mf.id, "size": mf.size, "name": mf.name,
                 "created_at": mf.created_at.isoformat() if mf.created_at else None,
                 "url": signed_url(mf.id, uid), "summary": (mf.meta or {}).get("summary", {}),
                 "next_at": (mf.created_at + COOLDOWN).isoformat() if mf.created_at else None}
    if st and st.get("state") in ("running", "failed"):
        return {**st, "last": ready}
    if ready:
        return {"state": "ready", **ready, "last": ready}
    return {"state": "none", "last": None}


async def start(db: AsyncSession, me: User) -> dict:
    """`POST /chat/v1/export`。已经在跑就原样返回;24 小时内做过一份就 429。"""
    st = await _get_state(me.id)
    if st and st.get("state") == "running" and me.id in _RUNNING:
        return st
    mf = await latest_export(db, me.id)
    if mf is not None and mf.created_at and now_utc() - mf.created_at < COOLDOWN:
        left = COOLDOWN - (now_utc() - mf.created_at)
        raise HTTPException(429, f"24 小时内只能导出一次,{int(left.total_seconds() // 3600) + 1} 小时后再来;"
                                 "上一份还能下载")
    st = {"state": "running", "started": now_utc().timestamp(), "progress": "准备中"}
    await _set_state(me.id, st)
    _RUNNING.add(me.id)
    task = asyncio.get_running_loop().create_task(_run(me.id))
    task.add_done_callback(lambda t: _RUNNING.discard(me.id))
    return st


def _safe(name: str, fallback: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name or "").strip(" .")
    return (name or fallback)[:80]


async def _run(uid: int) -> None:
    from ..db import SessionLocal

    tmp = Path(tempfile.mkdtemp(prefix="superz-export-"))
    try:
        async with SessionLocal() as db:
            zip_path = tmp / "export.zip"
            summary = await _build(db, uid, tmp, zip_path)
            key = f"media/export/u{uid}/{now_utc().strftime('%Y%m%d%H%M%S')}.zip"
            await asyncio.to_thread(storage.put_path, zip_path, key, True, "application/zip")
            old = list(await db.scalars(select(MediaFile).where(MediaFile.owner_id == uid,
                                                                MediaFile.purpose == "export")))
            mf = MediaFile(owner_id=uid, purpose="export", private=True, key=key, kind="file",
                           mime="application/zip", size=zip_path.stat().st_size,
                           name=f"superz-export-{now_utc().strftime('%Y%m%d')}.zip",
                           status="ready", meta={"summary": summary})
            db.add(mf)
            if old:
                await db.execute(delete(MediaFile).where(MediaFile.id.in_([o.id for o in old])))
            await db.flush()
            await append_user_event(db, uid, "export", {"state": "ready", "media_id": mf.id})
            await db.commit()
            for o in old:
                try:
                    await asyncio.to_thread(storage.remove, o.key, True)
                except Exception:
                    logger.warning("删旧导出失败 %s", o.key, exc_info=True)
        await _set_state(uid, None)
        logger.info("导出完成 user=%s %s", uid, summary)
    except Exception as e:
        logger.exception("导出失败 user=%s", uid)
        await _set_state(uid, {"state": "failed", "error": f"导出失败:{type(e).__name__},稍后重试"})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _progress(uid: int, text: str) -> None:
    await _set_state(uid, {"state": "running", "started": now_utc().timestamp(), "progress": text})


async def _build(db: AsyncSession, uid: int, tmp: Path, zip_path: Path) -> dict:
    budget = MEDIA_BUDGET
    summary = {"chats": 0, "messages": 0, "media": 0, "media_skipped": 0, "videos": 0}
    zf = zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True)
    try:
        me = await db.get(User, uid)
        prof = await db.get(SocialProfile, uid)
        contacts = (await db.execute(select(SocialContact.contact_id, SocialContact.alias, User.name)
                                     .join(User, User.id == SocialContact.contact_id)
                                     .where(SocialContact.owner_id == uid))).all()
        blocks = list(await db.scalars(select(SocialBlock.blocked_id).where(SocialBlock.user_id == uid)))
        zf.writestr("profile.json", json.dumps({
            "id": uid, "name": me.name if me else "", "username": prof.username if prof else None,
            "bio": prof.bio if prof else "", "privacy": prof.privacy if prof else {},
            "contacts": [{"user_id": c, "alias": a, "name": n} for c, a, n in contacts],
            "blocked_user_ids": blocks, "exported_at": now_utc().isoformat(),
        }, ensure_ascii=False, indent=1))

        chats = (await db.execute(select(Chat, ChatMember).join(ChatMember, ChatMember.chat_id == Chat.id)
                                  .where(ChatMember.user_id == uid, ChatMember.role.in_(ACTIVE_ROLES),
                                         Chat.deleted_at.is_(None)).order_by(Chat.id))).all()
        #: 放进 zip 的媒体:编号 → 包里的路径(同一个文件被转发到好几个会话只放一次)
        media_done: dict[int, str] = {}
        for n, (chat, member) in enumerate(chats, 1):
            await _progress(uid, f"会话 {n}/{len(chats)}")
            floor = visible_floor(chat, member)
            hidden = exists().where(and_(MessageHide.chat_id == ChatMessage.chat_id,
                                         MessageHide.seq == ChatMessage.seq,
                                         MessageHide.user_id == uid))
            out_msgs: list[dict] = []
            after = floor
            while True:
                msgs = list(await db.scalars(select(ChatMessage).where(
                    ChatMessage.chat_id == chat.id, ChatMessage.seq > after,
                    ChatMessage.deleted_at.is_(None), ~hidden)
                    .order_by(ChatMessage.seq).limit(PAGE)))
                if not msgs:
                    break
                after = msgs[-1].seq
                for m in await enrich_messages(db, uid, chat, msgs):
                    files = []
                    for it in m.get("media") or []:
                        mid = it.get("id")
                        entry = {"id": mid, "kind": it.get("kind"), "name": it.get("name"),
                                 "size": it.get("size")}
                        if mid in media_done:
                            entry["file"] = media_done[mid]
                        elif mid:
                            mf = await db.get(MediaFile, mid)
                            if mf is not None and mf.key and mf.size <= budget:
                                arc = f"media/{mid}_{_safe(mf.name, str(mid))}"
                                if await _add_object(zf, tmp, mf.key, mf.private, arc):
                                    budget -= mf.size
                                    media_done[mid] = arc
                                    summary["media"] += 1
                                    entry["file"] = arc
                            elif mf is not None:
                                summary["media_skipped"] += 1
                        files.append(entry)
                    out_msgs.append({
                        "seq": m["seq"], "date": m["created_at"], "edited": m.get("edited_at"),
                        "from": (m.get("sender") or {}).get("name") if not m.get("as_chat") else chat.title,
                        "from_id": (m.get("sender") or {}).get("id"), "kind": m["kind"],
                        "text": m.get("text", ""), "entities": m.get("entities") or [],
                        "reply_to_seq": m.get("reply_to_seq"), "forward": m.get("forward"),
                        "media": files, "poll": m.get("poll"), "location": m.get("location"),
                        "contact": m.get("contact"), "service": m.get("service"), "call": m.get("call"),
                        "reactions": [{"emoji": r.get("emoji"), "count": r.get("count")}
                                      for r in m.get("reactions") or []],
                    })
            title = chat.title or ("收藏夹" if chat.type == "saved" else "")
            if chat.type == "private":
                peer = await db.get(User, (await private_peer_id(db, chat, uid)) or 0)
                title = peer.name if peer else "私聊"
            zf.writestr(f"chats/{chat.id}_{_safe(title, chat.type)}.json", json.dumps(
                {"chat": {"id": chat.id, "type": chat.type, "title": title}, "messages": out_msgs},
                ensure_ascii=False, indent=1))
            summary["chats"] += 1
            summary["messages"] += len(out_msgs)

        await _progress(uid, "投稿")
        videos = list(await db.scalars(select(Video).where(Video.uploader_id == uid,
                                                           Video.deleted_at.is_(None)).order_by(Video.id)))
        vid_out = []
        for v in videos:
            parts = list(await db.scalars(select(VideoPart).where(VideoPart.video_id == v.id)
                                          .order_by(VideoPart.idx)))
            p_out = []
            for p in parts:
                best = max(p.renditions or [], key=lambda r: r.get("q", 0), default=None)
                entry = {"idx": p.idx, "title": p.title, "duration_ms": p.duration_ms}
                size = int((best or {}).get("size") or 0)
                if best and best.get("key") and size <= budget:
                    arc = f"videos/{v.vid}/P{p.idx + 1}_{best.get('q', '')}.mp4"
                    if await _add_object(zf, tmp, best["key"], True, arc):
                        budget -= size or storage.stat_size(best["key"], True) or 0
                        entry["file"] = arc
                elif best:
                    summary["media_skipped"] += 1
                p_out.append(entry)
            vid_out.append({"vid": v.vid, "title": v.title, "description": v.description,
                            "zone": v.zone, "tags": list(v.tags or []), "status": v.status,
                            "created_at": v.created_at.isoformat() if v.created_at else None,
                            "published_at": v.published_at.isoformat() if v.published_at else None,
                            "views": v.views, "likes": v.likes, "parts": p_out})
        zf.writestr("videos.json", json.dumps(vid_out, ensure_ascii=False, indent=1))
        summary["videos"] = len(vid_out)
        zf.writestr("README.txt", _readme(summary))
    finally:
        zf.close()
    return summary


async def _add_object(zf: zipfile.ZipFile, tmp: Path, key: str, private: bool, arc: str) -> bool:
    dst = tmp / "obj"
    try:
        await asyncio.to_thread(storage.download_to, key, private, dst)
        await asyncio.to_thread(zf.write, dst, arc)
        return True
    except Exception:
        logger.warning("导出时取文件失败 %s", key, exc_info=True)
        return False
    finally:
        dst.unlink(missing_ok=True)


def _readme(s: dict) -> str:
    return (
        "超级赞 · 我的数据导出\n\n"
        "profile.json    你的资料、隐私设置、联系人、拉黑名单\n"
        "chats/*.json    每个会话一个文件:你现在还能看到的全部消息(按 seq 从旧到新)\n"
        "media/          消息里的图片、视频、语音、文件(文件名前面是媒体编号,和 JSON 里 media[].id 对应)\n"
        "videos.json     你的投稿;videos/ 下是每 P 最高清晰度的视频文件\n\n"
        f"本次:{s['chats']} 个会话、{s['messages']} 条消息、{s['media']} 个媒体文件、{s['videos']} 个投稿。\n"
        + (f"有 {s['media_skipped']} 个文件因为超过 2GB 总量没放进来,JSON 里留了名字和大小。\n"
           if s["media_skipped"] else "")
        + "\n只导出你现在还能看到的内容:你清空过的、入群前看不到的、隐藏掉的都不在里面。\n"
    )
