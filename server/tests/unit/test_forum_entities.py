"""论坛实体解析(DEV-PROMPTS-41 §5.6)的纯函数部分。

实体**只由服务端解析** —— 客户端报什么都不算数。这里钉住的是「同一段正文解析出什么」:
话题的两种写法、截止字符、上限、@ 的格式、链接。改规则要连着 docs/FORUM-API.md 一起改。
"""
from app.services import forum as f


class Test话题:
    def test_两种写法都认(self):
        assert f.parse_tags("#周末# 出去玩") == [{"tag": "周末", "display": "周末"}]
        assert f.parse_tags("今天 #周末 出去玩") == [{"tag": "周末", "display": "周末"}]

    def test_带闭合井号的优先(self):
        # 「#成都# 的天气」里话题是「成都」,不是「成都# 的天气」
        assert f.parse_tags("#成都# 的天气") == [{"tag": "成都", "display": "成都"}]

    def test_遇到空白井号和中英文标点截止(self):
        assert f.parse_tags("#成都,今天") == [{"tag": "成都", "display": "成都"}]
        assert f.parse_tags("#成都。") == [{"tag": "成都", "display": "成都"}]
        assert f.parse_tags("#coffee, tea") == [{"tag": "coffee", "display": "coffee"}]
        # `#a#b`:闭合写法把两个井号都吃掉,后面的 b 是普通文字(和 X 的 `#话题#` 一样)
        assert f.parse_tags("#a#b") == [{"tag": "a", "display": "a"}]
        assert f.parse_tags("#a #b") == [{"tag": "a", "display": "a"},
                                         {"tag": "b", "display": "b"}]

    def test_不分大小写_原样留展示(self):
        assert f.parse_tags("#Coffee") == [{"tag": "coffee", "display": "Coffee"}]
        # 同一个话题两种写法只算一个,展示用第一次出现的那个
        assert f.parse_tags("#Coffee #coffee") == [{"tag": "coffee", "display": "Coffee"}]

    def test_最多十个(self):
        text = " ".join(f"#t{i}" for i in range(20))
        assert len(f.parse_tags(text)) == f.TAGS_MAX == 10

    def test_长度上限三十字(self):
        assert f.parse_tags("#" + "字" * 30)[0]["tag"] == "字" * 30
        # 超过 30 字的截到 30(正则的 {1,30});剩下的字不另起一个话题
        assert f.parse_tags("#" + "字" * 35)[0]["tag"] == "字" * 30

    def test_光一个井号不算话题(self):
        assert f.parse_tags("# 空的") == []
        assert f.parse_tags("##") == []


class Test提及:
    def test_按超级赞号的格式(self):
        assert f.parse_mentions("@xiaoming 你好") == ["xiaoming"]
        assert f.parse_mentions("@ab 太短") == [], "超级赞号至少 5 位"
        assert f.parse_mentions("@abc_de") == ["abc_de"]

    def test_小写去重最多十个(self):
        assert f.parse_mentions("@Xiaoming @xiaoming") == ["xiaoming"]
        assert len(f.parse_mentions(" ".join(f"@user{i:05d}" for i in range(20)))) == \
            f.MENTIONS_MAX == 10


class Test链接:
    def test_最多三个_去重(self):
        text = "看 https://a.cn/1 和 http://b.cn/2 还有 https://a.cn/1 再 https://c.cn/3 " \
               "外加 https://d.cn/4"
        assert f.parse_links(text) == ["https://a.cn/1", "http://b.cn/2", "https://c.cn/3"]
        assert f.LINKS_MAX == 3

    def test_句号不算在链接里(self):
        assert f.parse_links("打开 https://chaojizan.cc/a。") == ["https://chaojizan.cc/a"]


class Test编号:
    def test_前缀是fp加十位base58(self):
        pid = f.new_pid()
        assert pid.startswith("fp") and len(pid) == 12
        assert f.PID_RE.match(pid)
        # base58 不含 0OIl:看错一个字符就打不开别人的帖子
        assert not set(pid[2:]) & set("0OIl")

    def test_乱七八糟的编号直接不认(self):
        for bad in ("", "fp", "sv1234567890", "fp0000000000", "fp" + "a" * 11):
            assert not f.PID_RE.match(bad), bad


class Test原因代码:
    def test_共用C1xx和X999_另加F4xx(self):
        codes = f.reason_codes()
        assert {"C101", "C109", "X999", "F401", "F402", "F403"} <= set(codes)
        # 视频专有的 V2xx 不在里面:给帖子按「视频侵权」下架说不通
        assert not [c for c in codes if c.startswith("V")]

    def test_X999必须写说明(self):
        import pytest
        from fastapi import HTTPException

        f.reason_ok("F401", "")           # 别的代码不用写说明
        with pytest.raises(HTTPException) as e:
            f.reason_ok("X999", "太短")
        assert e.value.status_code == 422
        with pytest.raises(HTTPException):
            f.reason_ok("NOPE", "说明够长的一句话")
        f.reason_ok("X999", "写清楚为什么下架")


class Test正文与图片:
    def test_正文五百字(self):
        import pytest
        from fastapi import HTTPException

        assert f.TEXT_MAX == 500
        assert f.clean_text("  你好  ") == "你好"
        with pytest.raises(HTTPException):
            f.clean_text("字" * 501)

    def test_图片只能是本人上传的(self):
        import pytest
        from fastapi import HTTPException

        ok = f._clean_media([{"url": "/img/forum/u42-abc.jpg", "w": 10, "h": 20}], 42)
        assert ok == [{"url": "/img/forum/u42-abc.jpg", "w": 10, "h": 20}]
        for bad in ("/img/forum/u7-abc.jpg",          # 别人传的
                    "/img/avatar/u42-abc.jpg",        # 用途不对
                    "https://evil.cn/x.jpg"):         # 站外
            with pytest.raises(HTTPException):
                f._clean_media([{"url": bad}], 42)

    def test_最多四张(self):
        import pytest
        from fastapi import HTTPException

        urls = [{"url": f"/img/forum/u1-{i}.jpg"} for i in range(5)]
        with pytest.raises(HTTPException):
            f._clean_media(urls, 1)
        assert len(f._clean_media(urls[:4], 1)) == f.MEDIA_MAX == 4


class Test投票:
    def test_二到四项_每项二十五字_五分钟到七天(self):
        import pytest
        from datetime import datetime, timezone
        from fastapi import HTTPException

        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        opts, ends = f._clean_poll({"options": ["甲", "乙"], "minutes": 60}, now)
        assert opts == [{"text": "甲", "votes": 0}, {"text": "乙", "votes": 0}]
        assert (ends - now).total_seconds() == 3600
        for bad in ({"options": ["只有一个"], "minutes": 60},
                    {"options": list("甲乙丙丁戊"), "minutes": 60},
                    {"options": ["甲", "甲"], "minutes": 60},
                    {"options": ["甲", "字" * 26], "minutes": 60},
                    {"options": ["甲", "乙"], "minutes": 1},
                    {"options": ["甲", "乙"], "minutes": 7 * 24 * 60 + 1}):
            with pytest.raises(HTTPException):
                f._clean_poll(bad, now)


def test_浏览去重的键_登录按账号_没登录按设备哈希():
    assert f.viewer_key(42, "dev") == "u42"
    k = f.viewer_key(None, "dev-abc")
    assert k.startswith("d") and len(k) == 33
    assert k != f.viewer_key(None, "dev-xyz")
