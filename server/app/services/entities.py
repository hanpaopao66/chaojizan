"""消息实体:格式、提及、话题、链接(DEV-PROMPTS-40 §5.2,#346)。

**偏移按 UTF-16 码元**(和 Telegram、Dart 的 String 下标一致)。Python 的 str 按码点数,
「👍」在 Python 里长 1、在 UTF-16 里长 2 —— 两边不换算的话,emoji 后面的粗体会整体错一位。

客户端只发格式类实体(粗体、斜体……);链接、@提及、#话题由服务端识别补齐,
这样老版本客户端发的纯文字消息也能点链接、@人。
"""
import re

FORMAT_TYPES = {"bold", "italic", "underline", "strike", "spoiler", "code", "pre",
                "text_link", "text_mention"}
AUTO_TYPES = {"mention", "hashtag", "url"}
MAX_ENTITIES = 100

_URL_RE = re.compile(r"(?:https?://)[^\s<>\"'，。！？、）」』]+", re.IGNORECASE)
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_@])@([A-Za-z][A-Za-z0-9_]{3,30}[A-Za-z0-9])")
_HASHTAG_RE = re.compile(r"(?<![\w#])#([0-9A-Za-z_一-鿿]{1,64})")
_LANG_RE = re.compile(r"^[a-z0-9+#.\-]{1,32}$")


def utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def utf16_offsets(s: str) -> list[int]:
    """第 i 个码点在 UTF-16 里的起始偏移;最后多一个元素 = 总长度。"""
    out = [0]
    for ch in s:
        out.append(out[-1] + (2 if ord(ch) > 0xFFFF else 1))
    return out


class EntityError(ValueError):
    pass


def validate_entities(text: str, entities: list | None) -> list[dict]:
    """校验客户端发来的格式实体,返回规整后的列表(按 offset 排序)。不合规抛 EntityError。"""
    if not entities:
        return []
    if not isinstance(entities, list) or len(entities) > MAX_ENTITIES:
        raise EntityError(f"格式标记最多 {MAX_ENTITIES} 个")
    total = utf16_len(text)
    out = []
    for e in entities:
        if not isinstance(e, dict):
            raise EntityError("格式标记不对")
        t = e.get("type")
        if t not in FORMAT_TYPES:
            raise EntityError(f"不支持的格式:{t}")
        off, ln = e.get("offset"), e.get("length")
        if not isinstance(off, int) or not isinstance(ln, int) or off < 0 or ln <= 0 \
                or off + ln > total:
            raise EntityError("格式标记的位置超出了文字范围")
        item = {"type": t, "offset": off, "length": ln}
        if t == "text_link":
            url = str(e.get("url") or "")
            if not re.match(r"^https?://", url, re.IGNORECASE) or len(url) > 2048:
                raise EntityError("链接只能是 http 或 https 地址")
            item["url"] = url
        elif t == "text_mention":
            if not isinstance(e.get("user_id"), int):
                raise EntityError("提及缺少用户")
            item["user_id"] = e["user_id"]
        elif t == "pre" and e.get("language"):
            lang = str(e["language"]).lower()
            if _LANG_RE.match(lang):
                item["language"] = lang
        out.append(item)
    out.sort(key=lambda x: (x["offset"], -x["length"]))
    return out


def auto_entities(text: str, existing: list[dict] | None = None) -> list[dict]:
    """识别文字里的链接、@提及、#话题。代码块 / 行内代码里的不算。"""
    if not text:
        return []
    offs = utf16_offsets(text)
    code_spans = [(e["offset"], e["offset"] + e["length"]) for e in existing or ()
                  if e.get("type") in ("code", "pre")]

    def in_code(a: int, b: int) -> bool:
        return any(a < ce and b > cs for cs, ce in code_spans)

    found: list[dict] = []
    taken: list[tuple[int, int]] = []
    for rx, typ, group in ((_URL_RE, "url", 0), (_MENTION_RE, "mention", 0),
                           (_HASHTAG_RE, "hashtag", 0)):
        for m in rx.finditer(text):
            s, e = m.start(group), m.end(group)
            # 链接结尾的英文标点不算链接的一部分
            if typ == "url":
                while e > s and text[e - 1] in ".,;:!?)]}":
                    e -= 1
            a, b = offs[s], offs[e]
            if b <= a or in_code(a, b) or any(a < te and b > ts for ts, te in taken):
                continue
            taken.append((a, b))
            found.append({"type": typ, "offset": a, "length": b - a})
    found.sort(key=lambda x: x["offset"])
    return found


def slice_utf16(text: str, offset: int, length: int) -> str:
    """按 UTF-16 偏移取子串。"""
    offs = utf16_offsets(text)
    try:
        start = offs.index(offset)
        end = offs.index(offset + length)
    except ValueError:
        return ""
    return text[start:end]


def mask_spoilers(text: str, entities: list[dict] | None) -> str:
    """剧透那几段换成「▒」,给预览用(推送、引用、置顶提示)。

    剧透的意思就是「点开才看」—— 推送横幅、会话列表、回复引用里直接露出来就白标了。
    """
    spans = [(e["offset"], e["offset"] + e["length"]) for e in entities or ()
             if e.get("type") == "spoiler"]
    if not spans or not text:
        return text or ""
    offs = utf16_offsets(text)
    out = []
    for i, ch in enumerate(text):
        a = offs[i]
        out.append("▒" if any(s <= a < e for s, e in spans) and not ch.isspace() else ch)
    return "".join(out)


def mentioned_usernames(text: str, entities: list[dict]) -> set[str]:
    return {slice_utf16(text, e["offset"], e["length"]).lstrip("@").lower()
            for e in entities if e.get("type") == "mention"}


def mentioned_user_ids(entities: list[dict]) -> set[int]:
    return {int(e["user_id"]) for e in entities if e.get("type") == "text_mention"}


def hashtags(text: str, entities: list[dict]) -> list[str]:
    return [slice_utf16(text, e["offset"], e["length"]) for e in entities
            if e.get("type") == "hashtag"]


def urls(text: str, entities: list[dict]) -> list[str]:
    out = []
    for e in entities:
        if e.get("type") == "url":
            out.append(slice_utf16(text, e["offset"], e["length"]))
        elif e.get("type") == "text_link":
            out.append(e["url"])
    return out
