"""验证 common/Gbk.ets 的建表算法。

没有 DevEco 就跑不了 ArkTS,但**这个算法是纯逻辑,可以在本机验** ——
而它是整个蓝牙打印的地基:表建错了,小票整张印成乱码,
而且不会抛异常、不会报错,只有商家拿到那张纸时才知道。

Python 的 cp936 就是 GBK。这里用同一套算法建表,再和 cp936 全量对拍。

    python3 tools/verify_gbk.py

改了 Gbk.ets 的建表逻辑就跑一遍。
"""
# 修正:码位之间插 \n 分隔。0x0A 不在 GBK 次字节范围(0x40-0xFE)内,
# 永远不会被当成双字节的一部分吞掉,所以它一定能活下来当分隔符。
codes, raw = [], bytearray()
for hi in range(0x81, 0xFF):
    for lo in range(0x40, 0xFF):
        if lo == 0x7F:
            continue
        codes.append((hi << 8) | lo)
        raw += bytes([hi, lo, 0x0A])

text = raw.decode('gbk', errors='replace')
segs = text.split('\n')
if segs and segs[-1] == '':
    segs.pop()
print(f"码位数 {len(codes)}  分段数 {len(segs)}  {'一致' if len(codes)==len(segs) else '★不一致'}")

table = {}
for i, seg in enumerate(segs):
    if len(seg) != 1:
        continue          # 非法码位解成了"替换字符+尾字节"
    ch = ord(seg)
    if ch == 0xFFFD:
        continue
    if ch not in table:
        table[ch] = codes[i]
print(f"表条目 {len(table)}")

def encode(s):
    out = []
    for c in s:
        o = ord(c)
        if o < 0x80:
            out.append(o); continue
        code = table.get(o)
        out.append(0x3F) if code is None else out.extend([(code >> 8) & 0xFF, code & 0xFF])
    return bytes(out)

cases = ['超级赞','宫保鸡丁','订单','小票','收货地址:成都市武侯区','共 3 件 ¥48.00',
         '(备注:不要辣)','№①','麻婆豆腐 x2','取餐码 8823','鱼香肉丝盖浇饭',
         '平台佣金','今日实收','骑手已接单','【自取】','—' ,'·','…','℃','㎡']
bad = []
for s in cases:
    mine, real = encode(s), s.encode('gbk', errors='replace')
    if mine != real:
        bad.append((s, mine.hex(), real.hex()))
print(f"用例 {len(cases)} 条,差异 {len(bad)} 条")
for s, m, r in bad:
    print(f"  ★ {s!r} 我={m} 真={r}")

# 全量对拍:所有能被 GBK 编码的 BMP 字符
mismatch = tot = 0
for cp in range(0x20, 0x10000):
    ch = chr(cp)
    try:
        real = ch.encode('gbk')
    except UnicodeEncodeError:
        continue
    tot += 1
    if encode(ch) != real:
        mismatch += 1
        if mismatch <= 5:
            print(f"  差异 U+{cp:04X} {ch!r} 我={encode(ch).hex()} 真={real.hex()}")
print(f"\n全量对拍:{tot} 个可编码字符,差异 {mismatch} 个")
print("emoji 兜底:", encode('好吃😋').hex())
print("结论:", "算法可用" if not bad and mismatch == 0 else "★仍有问题")
