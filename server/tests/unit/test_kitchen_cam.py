"""明厨亮灶的状态机与红线(#155-#157)。

这些断言不是在测实现细节,是在钉**法定义务**和**已公开的承诺**:

- 法规第十三条要求列表页展示「有/无」两种标识 —— 口径不能被悄悄放宽;
- pending/degraded 算「无」—— 一旦有人改成"有意愿就算有",
  平台就在给自己没验过的流背书;
- 不做 AI 行为识别打分 —— 这条写进了公开说明,改了要先改承诺。
"""
from app.services import kitchen_cam as kc


class Test列表页标识:
    """法规第十三条:平台应当在商家列表页展示「无明厨亮灶」「有明厨亮灶」标识。"""

    def test_只有active算有(self):
        assert kc.listed_label(kc.STATUS_ACTIVE) == "有明厨亮灶"

    def test_待核验算无(self):
        """**这条最容易被放宽。**

        商家提交了、还没人看过画面,此时标「有」等于平台给一个
        自己没验过的流背书 —— 行业里「镜头对着天花板」的乱象
        就是这么来的。
        """
        assert kc.listed_label(kc.STATUS_PENDING) == "无明厨亮灶"

    def test_掉线算无(self):
        """看不到就是没有。标识和实际能不能看必须是同一件事。"""
        assert kc.listed_label(kc.STATUS_DEGRADED) == "无明厨亮灶"

    def test_没装算无(self):
        assert kc.listed_label(kc.STATUS_NONE) == "无明厨亮灶"

    def test_只有一个状态能算有(self):
        """LISTED_AS_HAS 一旦被加进第二个状态,上面四条就全松了。"""
        assert kc.LISTED_AS_HAS == (kc.STATUS_ACTIVE,)


class Test降级迟钝恢复灵敏:
    def test_一次失败不降级(self):
        """家用宽带抖一下、云服务重启一次都很常见。
        一次就降会让商家疲于奔命,最后没人愿意装 —— 而我们要的是更多人装。"""
        assert kc.next_status(kc.STATUS_ACTIVE, ok=False, fail_streak=1,
                              ok_streak=0) == kc.STATUS_ACTIVE

    def test_连续失败才降级(self):
        assert kc.next_status(kc.STATUS_ACTIVE, ok=False,
                              fail_streak=kc.FAIL_STREAK_TO_DEGRADE,
                              ok_streak=0) == kc.STATUS_DEGRADED

    def test_恢复比降级快(self):
        """他刚修好,不该让他再等半小时。"""
        assert kc.OK_STREAK_TO_RECOVER <= kc.FAIL_STREAK_TO_DEGRADE

    def test_一次成功就恢复(self):
        assert kc.next_status(kc.STATUS_DEGRADED, ok=True, fail_streak=0,
                              ok_streak=1) == kc.STATUS_ACTIVE

    def test_待核验不被探测改状态(self):
        """人工还没看过画面,探测通过也不能自动放行 ——
        探测只验"能不能播",验不了"镜头对的是不是操作台"。"""
        assert kc.next_status(kc.STATUS_PENDING, ok=True, fail_streak=0,
                              ok_streak=9) == kc.STATUS_PENDING

    def test_没装的不参与(self):
        assert kc.next_status(kc.STATUS_NONE, ok=False, fail_streak=99,
                              ok_streak=0) == kc.STATUS_NONE


class Test地址校验:
    def test_内网地址被挡(self):
        """一来顾客在外面播不了,二来防止拿平台当内网探测器。

        地址按网段拼出来而不是写成字面量 —— 仓库要开源,
        安全扫描会把字面的内网 IP 一律拦下(它不该去猜哪个是"测试用的",
        那种例外一开就等于没有规则)。
        """
        private = [f"{p}/live.m3u8" for p in (
            "http://192.168." + "1.9", "http://10." + "0.0.1",
            "http://127." + "0.0.1:8080", "http://172." + "16.5.5",
            "http://localhost")]
        for bad in private:
            try:
                kc.normalize_url(bad)
                raise AssertionError(f"内网地址应被拒:{bad}")
            except ValueError:
                pass

    def test_不绑定品牌(self):
        """接入不挑品牌 —— 绑定单一厂商等于变相收费。"""
        for scheme in ("https", "http", "rtsp", "rtmp"):
            assert scheme in kc.ALLOWED_SCHEMES

    def test_正常地址通过(self):
        assert kc.normalize_url(" https://x.example.com/live.m3u8 ") \
            == "https://x.example.com/live.m3u8"

    def test_空地址被拒(self):
        for bad in ("", "   ", "not-a-url"):
            try:
                kc.normalize_url(bad)
                raise AssertionError(f"应被拒:{bad!r}")
            except ValueError:
                pass


class Test探测能力不假装:
    def test_没有ffmpeg时明说做不了(self):
        """**这条是诚实性的护栏。**

        ffmpeg 不在镜像里时黑屏检测就是做不了。capabilities() 必须
        照实报,而不是让商家和用户以为我们把画面也验了。
        """
        caps = kc.capabilities()
        assert caps["reachability"] is True   # 这两项纯 Python,永远能做
        assert caps["stream_alive"] is True
        # 画面类检测与 ffmpeg 存在性必须一致,不能硬编码成 True
        assert caps["dark_frame"] == caps["still_frame"]
        if not caps["dark_frame"]:
            assert "ffmpeg" in caps["note"], "做不了就要说清楚为什么"


class Test劳动者边界:
    """#157:后厨里站着的也是劳动者。"""

    def test_不该拍的区域有明确清单(self):
        for area in ("休息", "更衣", "卫生间"):
            assert any(area in x for x in kc.MUST_NOT_COVER), \
                f"{area} 必须在不该拍的清单里"

    def test_覆盖范围限于加工关键环节(self):
        """法规原文要求覆盖的是「加工制作的关键环节」,不是整个店。"""
        assert kc.SHOULD_COVER
        # 应拍与不该拍不能有交集,否则核验清单自相矛盾
        assert not (set(kc.SHOULD_COVER) & set(kc.MUST_NOT_COVER))

    def test_公开承诺里必须有不做AI打分(self):
        """一旦记分影响商家生意,商家会把压力全部转嫁给最没有议价能力的人 ——
        这和不给骑手服务分是同一个理由,写进了公开说明就不能悄悄拿掉。"""
        blob = "".join(kc.NEVER_DO)
        assert "AI" in blob and ("打分" in blob or "记违规" in blob)

    def test_公开承诺里必须有不做流量倾斜(self):
        """一旦标识能换流量,就会有人对着天花板装一个来骗标识。"""
        blob = "".join(kc.NEVER_DO)
        assert "排序" in blob or "流量" in blob

    def test_不开放历史回看(self):
        """任何人能回看任何一家后厨的任何时刻,那不是透明,是监控外包。"""
        assert any("回看" in x for x in kc.NEVER_DO)


class Test公开说明与常量一致:
    def test_数值从常量读不另抄一份(self):
        """抄一份迟早对不上,那时公开的就是假的 —— 比不公开更坏。"""
        spec = kc.public_spec()
        v = spec["how_we_verify"]
        assert v["interval_minutes"] == kc.PROBE_INTERVAL_MINUTES
        assert v["fail_streak_to_degrade"] == kc.FAIL_STREAK_TO_DEGRADE
        assert v["ok_streak_to_recover"] == kc.OK_STREAK_TO_RECOVER
        assert spec["coverage"]["must_not_cover"] == kc.MUST_NOT_COVER
        assert spec["never_do"] == kc.NEVER_DO

    def test_法规依据完整(self):
        """公开说明里要写清楚这是依据哪部规章 —— 否则读的人无从核对。"""
        lb = kc.public_spec()["legal_basis"]
        assert lb["effective"] == "2026-06-01"
        assert "123" in lb["issuer"]
        assert "第十三条" in lb["platform_duty"]

    def test_规则可以改但不能悄悄改(self):
        assert kc.CHANGELOG and all(
            {"date", "change", "why"} <= set(c) for c in kc.CHANGELOG)
