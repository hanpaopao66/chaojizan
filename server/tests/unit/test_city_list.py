"""全国城市清单的解析(#308)。

## 为什么这层要有单测

网络那一层测不了,但**直辖市会不会把区混进城市列表**这种判断
恰恰最容易错、也最该被钉住:错了的表现是城市选择器里出现
「东城」「朝阳」和「成都」并列,而这不会报任何错。
"""
from app.services.city_list import parse, _initial


def _prov(name, fullname, cidx, pinyin, lat=30.0, lng=104.0):
    return {"name": name, "fullname": fullname, "cidx": cidx,
            "pinyin": pinyin, "location": {"lat": lat, "lng": lng}}


def _city(name, fullname, pinyin, lat=30.0, lng=104.0):
    return {"name": name, "fullname": fullname, "pinyin": pinyin,
            "location": {"lat": lat, "lng": lng}}


class Test直辖市:
    def test_直辖市自己是城市_下一层的区不进列表(self):
        result = [
            [_prov("北京", "北京市", [0, 1], ["bei", "jing"])],
            [_city("东城", "东城区", ["dong", "cheng"]),
             _city("朝阳", "朝阳区", ["chao", "yang"])],
        ]
        out = parse(result)
        names = [c["short"] for c in out]
        assert names == ["北京"], (
            f"直辖市的区混进城市列表了:{names} —— "
            f"城市选择器里会出现「东城」和「成都」并列")

    def test_普通省份展开到地级市(self):
        result = [
            [_prov("四川", "四川省", [0, 1], ["si", "chuan"])],
            [_city("成都", "成都市", ["cheng", "du"]),
             _city("绵阳", "绵阳市", ["mian", "yang"])],
        ]
        out = parse(result)
        assert [c["short"] for c in out] == ["成都", "绵阳"]
        assert out[0]["province"] == "四川"

    def test_同名的地级市不能被当成直辖市的区误删(self):
        """辽宁有个**朝阳市**,和北京朝阳区同名。

        按名字去重就会把它删掉 —— 判据必须是「父级是不是直辖市」,
        不是「这个名字像不像区」。
        """
        result = [
            [_prov("北京", "北京市", [0, 0], ["bei", "jing"]),
             _prov("辽宁", "辽宁省", [1, 1], ["liao", "ning"])],
            [_city("朝阳", "朝阳区", ["chao", "yang"]),
             _city("朝阳", "朝阳市", ["chao", "yang"])],
        ]
        out = parse(result)
        assert [(c["short"], c["province"]) for c in out] == [
            ("北京", "北京"), ("朝阳", "辽宁")]


class Test首字母:
    def test_取拼音首字母大写(self):
        assert _initial(["cheng", "du"], "成都") == "C"

    def test_拿不到拼音归到井号而不是丢掉(self):
        """归 # 是有意的:丢掉等于这个城市在选择器里**永远搜不到**,
        而那是静默的 —— 没有任何报错。"""
        assert _initial(None, "某市") == "#"
        assert _initial([], "某市") == "#"
        assert _initial(["123"], "某市") == "#"


class Test结构异常:
    def test_层级不足时返回空而不是抛(self):
        """接口降级(只返回省一层)时不能把整个城市接口拖崩 ——
        它只是选择器的一部分,有店的城市照常能选。"""
        assert parse([]) == []
        assert parse([[{"name": "四川"}]]) == []

    def test_cidx_越界不炸(self):
        result = [[_prov("四川", "四川省", [0, 99], ["si", "chuan"])],
                  [_city("成都", "成都市", ["cheng", "du"])]]
        assert [c["short"] for c in parse(result)] == ["成都"]
