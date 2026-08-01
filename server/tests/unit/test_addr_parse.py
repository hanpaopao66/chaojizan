"""收货地址智能识别(#169)。

用真实形态的样例钉住:粘贴来的地址什么写法都有,
而这个功能的价值恰恰在于**替用户省掉重打一遍**——
拆错了还不如不拆(他会照单全收,然后骑手打不通电话)。
"""
import pytest

from app.services.addr_parse import parse

# (输入, 期望姓名, 期望电话, 地址里必须含, 门牌)
CASES = [
    # 主流平台的官方示例
    ("上海市徐汇区乐山路33号 大雄 1223334444", "大雄", "1223334444", "乐山路33号", ""),
    # 逗号分隔(最常见)
    ("张三，13800138000，成都市锦江区春熙路8号 3栋1单元502",
     "张三", "13800138000", "春熙路8号", "3栋1单元502"),
    # 带前缀词
    ("收货人:李四 手机:18392121865 地址:陕西省人民医院住院大楼 一楼",
     "李四", "18392121865", "人民医院", "一楼"),
    # 座机 + 称谓
    ("王五 女士 028-88886666 成都天府广场地铁站 B口",
     "王五", "028-88886666", "天府广场", ""),
    # 只有地址,没有人
    ("成都市锦江区春熙路8号", "", "", "春熙路8号", ""),
]


@pytest.mark.parametrize("text,name,phone,addr_has,detail", CASES)
def test_真实样例(text, name, phone, addr_has, detail):
    r = parse(text)
    assert r["name"] == name, f"姓名:{r}"
    assert r["phone"] == phone, f"电话:{r}"
    assert addr_has in r["address"], f"地址:{r}"
    if detail:
        assert r["detail"] == detail, f"门牌:{r}"


class Test不能把地名当人名:
    """第一版把「大厦」「广场」「小区」「花园」塞进了**字符类**,
    于是「大」「小」「广」「花」「园」都成了单字地址特征词 ——
    「大雄」「小明」「花花」这类再常见不过的人名全被判成地址。

    反过来也不行:试过从开头切人名(`王小明北京市…`),
    结果「上海」「成都」被当成了人名 —— 开头的汉字压倒性地
    更可能是省市名,那个方向天然赢不了。
    """

    @pytest.mark.parametrize("name", ["大雄", "小明", "花花", "李广", "王园"])
    def test_含大小广花园的人名要认得出(self, name):
        r = parse(f"北京市朝阳区建国路1号 {name} 13800138000")
        assert r["name"] == name, r

    @pytest.mark.parametrize("city", ["上海", "成都", "北京", "西安"])
    def test_省市名不能被当成人名(self, city):
        r = parse(f"{city}市锦江区春熙路8号")
        assert r["name"] == "", f"{city} 被当成了人名:{r}"


class Test门牌要单独切出来:
    """骑手要的是「哪栋楼」+「几零几」两段。合成一行,
    他会在楼下才发现不知道上几楼。"""

    def test_单元室(self):
        r = parse("成都市锦江区春熙路8号 3栋1单元502 张三 13800138000")
        assert r["detail"] == "3栋1单元502" and "3栋" not in r["address"]

    def test_没有门牌时不硬切(self):
        r = parse("成都天府广场地铁站 王五 13800138000")
        assert r["detail"] == "", r


class Test安全与边界:
    def test_空输入不炸(self):
        for t in ("", "   ", "\n\n"):
            r = parse(t)
            assert r["name"] == "" and r["address"] == ""

    def test_超长截断(self):
        r = parse("成都市锦江区春熙路8号" * 200)
        assert len(r["address"]) <= 400

    def test_结果永远标注是建议(self):
        """解析不了刁钻写法是常态。**必须让用户过目再保存** ——
        猜错不可怕,不给他改的机会才可怕。"""
        r = parse("张三 13800138000 成都市锦江区春熙路8号")
        assert r["note"], "必须带一句提醒用户核对的话"

    def test_纯本地不外发(self):
        """这段文本里有姓名和手机号,送去第三方解析等于把用户的
        个人信息交出去。本地能做就不该外发。"""
        import inspect

        from app.services import addr_parse
        src = inspect.getsource(addr_parse)
        for bad in ("httpx", "requests", "aiohttp", "urlopen"):
            assert bad not in src, f"解析不该联网,却出现了 {bad}"
