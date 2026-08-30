"""收货地址智能识别:一段粘贴文本 → 姓名 / 电话 / 地址 / 门牌(#169)。

## 为什么值得做

用户的地址往往已经存在于别处:微信里同事发的、上一个外卖平台复制的、
快递单上抄的。让他对着一段现成的文字**重新手打一遍**,是在制造错误 ——
打错一个数字,骑手就打不通电话。

饿了么的做法是「粘贴 → 智能识别」,把一段
`上海市徐汇区乐山路33号 大雄 1223334444` 拆成三栏。这个交互值得对齐。

## 纯本地正则,不调任何外部服务

**平台无补贴预算**,不选按次计费的方案;而且这段文本里有姓名和手机号,
送去第三方解析等于把用户的个人信息交出去 —— 本地能做就不该外发。

代价是解析不了特别刁钻的写法。所以设计上守一条:

**解析结果一律是「建议」,必须让用户过目确认后才落库。**
猜错不可怕(用户改一下就行),不给他改的机会才可怕。

## 顺序很重要

先抽电话(数字串最好认)、再抽姓名(在剩下的短词里找)、剩下的当地址。
反过来做会把手机号当成门牌号的一部分。
"""
from __future__ import annotations

import re

#: 手机号:11 位,1 开头。允许中间有空格/横线(从别处复制常带)
_PHONE = re.compile(r"(?<!\d)(1[3-9]\d)[\s\-]?(\d{4})[\s\-]?(\d{4})(?!\d)")

#: 兜底:7-11 位的裸数字串。**故意放宽** ——
#: 粘贴来的号码常是假号、漏位、或带分机。抽出来放进电话栏让用户改,
#: 比"认不出→整段留在地址里"好得多:后者他多半不会发现
_PHONE_LOOSE = re.compile(r"(?<!\d)(\d{7,11})(?!\d)")

#: 座机(区号-号码)。比手机少见,但医院/公司地址常留座机
_TEL = re.compile(r"(?<!\d)(0\d{2,3})[\s\-]?(\d{7,8})(?!\d)")

#: 邮编:6 位数字,单独出现。抽掉它免得被当成门牌号
_ZIP = re.compile(r"(?<!\d)\d{6}(?!\d)")

#: 收货人常见的前缀词,识别时要剥掉
_NAME_PREFIX = re.compile(r"^(收货人|联系人|姓名|收件人)[:：]?\s*")
_PHONE_PREFIX = re.compile(r"(电话|手机|联系方式|tel|mobile)[:：]?\s*", re.I)
_ADDR_PREFIX = re.compile(r"^(地址|收货地址|详细地址)[:：]?\s*")

#: 行政区划与地址特征词。含这些的片段判定为地址而不是人名。
#
# ⚠️ **单字和词组必须分开写。** 第一版把「大厦」「广场」「小区」「花园」
# 直接塞进字符类,结果「大」「小」「广」「花」「园」都成了单字特征词 ——
# 于是「大雄」「小明」「花花」这类再常见不过的人名全被判成地址。
# 中文里这些字在人名里出现的频率远高于它们单独指代地址的频率。
_ADDR_HINT = re.compile(
    # 单字:单独出现就足以说明是地址
    r"[省市县镇乡街巷弄栋幢室苑]"
    # 词组:必须成词才算
    r"|大厦|广场|小区|花园|公寓|单元|号楼|大道|胡同|社区|开发区|工业园"
    r"|新区|园区|写字楼|商厦|中心|车站|机场|医院|学校|大学|路\d|号\d?$"
    # 英文+数字的门牌(如 A3、B12)
    r"|[A-Za-z]\d")

#: 门牌特征:X 单元 X 室 / X 号楼 / X 层 / X-X-X
_DOOR = re.compile(
    r"([\d一二三四五六七八九十]+\s*(?:单元|门|栋|幢|座|号楼|楼|层|室|房)\s*"
    r"[\dA-Za-z\-]*)+|(\d+[-‐–]\d+(?:[-‐–]\d+)?)$")

#: 称谓
_SALUTATION = re.compile(r"(先生|女士|小姐|老师|师傅)")

#: 中文姓名:2-4 个汉字,且不含地址特征词
_CN_NAME = re.compile(r"^[一-龥]{2,4}$")


def _norm(text: str) -> str:
    """归一化:全角转半角、压空白。粘贴来的文本什么格式都有。"""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    # 逗号/顿号/竖线都当分隔符,统一成空格
    s = re.sub(r"[,、|;；\t\r\n]+", " ", "".join(out))
    return re.sub(r"\s{2,}", " ", s).strip()


def parse(text: str) -> dict:
    """把一段文本拆成 {name, phone, address, detail, salutation}。

    拆不出的字段留空字符串 —— **不猜**。宁可让用户补一栏,
    也不要塞一个看着像但其实是错的值进去:他多半不会逐字复核。
    """
    raw = _norm(text or "")[:400]
    if not raw:
        return {"name": "", "phone": "", "address": "", "detail": "",
                "salutation": "", "note": "没有可识别的内容"}

    rest = raw

    # 1) 电话:数字串最好认,先抽走
    phone = ""
    m = _PHONE.search(rest)
    if m:
        phone = "".join(m.groups())
        rest = rest[:m.start()] + " " + rest[m.end():]
    else:
        m = _TEL.search(rest)
        if m:
            phone = "-".join(m.groups())
            rest = rest[:m.start()] + " " + rest[m.end():]
        else:
            # 放宽兜底。先把邮编摘掉,免得 6 位邮编之外的数字被误抓;
            # 门牌里的数字一般短于 7 位,不会撞
            probe = _ZIP.sub(" ", rest)
            m = _PHONE_LOOSE.search(probe)
            if m:
                phone = m.group(1)
                rest = probe[:m.start()] + " " + probe[m.end():]
    rest = _PHONE_PREFIX.sub(" ", rest)
    rest = _ZIP.sub(" ", rest)

    # 2) 称谓
    salutation = ""
    m = _SALUTATION.search(rest)
    if m:
        salutation = m.group(1)
        rest = rest[:m.start()] + " " + rest[m.end():]

    # 3) 姓名:在剩下的片段里找一个「像人名」的短词。
    #    **含地址特征词的一律不算** —— 否则"乐山路"会被当成人名
    name = ""
    parts = [p for p in re.split(r"\s+", rest) if p]
    for i, p in enumerate(parts):
        cand = _NAME_PREFIX.sub("", p)
        if _CN_NAME.fullmatch(cand) and not _ADDR_HINT.search(cand):
            name = cand
            parts.pop(i)
            break

    rest = " ".join(parts)
    rest = _ADDR_PREFIX.sub("", rest).strip()

    # 粘连文本兜底:`13911112222王小明北京市海淀区…` 这种从聊天记录直接复制的,
    # 抽走电话后开头就是人名紧贴着地址,没有空格可切。
    # 判据:开头 2-3 个汉字,紧跟着的部分含行政区划特征 —— 那前面这段多半是人名。
    # **只在还没识别出姓名时才试**,避免把"上海市"之类切成人名
    # 姓名兜底:**只从末尾找,不从开头找。**
    #
    # 试过从开头切(`王小明北京市…`),结果把"上海"、"成都"当成了人名 ——
    # 开头的汉字压倒性地更可能是省市名,那个方向天然赢不了。
    # 而中文地址的书写习惯是「地址在前、人名在后」,末尾兜底才站得住。
    #
    # 判据:最后一段是 2-4 个纯汉字、不含地址特征词,且**前面还有内容**
    # (否则整段就是个地名,比如单独一个"春熙路")
    if not name:
        segs = [x for x in re.split(r"\s+", rest) if x]
        if len(segs) >= 2 and _CN_NAME.fullmatch(segs[-1]) \
                and not _ADDR_HINT.search(segs[-1]):
            name = segs[-1]
            rest = " ".join(segs[:-1])

    # 4) 门牌:从地址尾部切出来。骑手要的是「哪栋楼」+「几零几」两段,
    #    合成一行会让他在楼下才发现不知道上几楼
    address, detail = rest, ""
    m = _DOOR.search(rest)
    if m and m.start() > 0:
        address = rest[:m.start()].strip()
        detail = rest[m.start():].strip()

    hit = sum(1 for v in (name, phone, address) if v)
    return {
        "name": name,
        "phone": phone,
        "address": address,
        "detail": detail,
        "salutation": salutation,
        # 识别结果是**建议**,要用户过目 —— 猜错不可怕,不给他改的机会才可怕
        "note": ("识别结果仅供参考,请核对后再保存" if hit >= 2 else
                 "只认出了一部分,请手动补齐"),
    }
