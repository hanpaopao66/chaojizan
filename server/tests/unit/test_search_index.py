"""搜索的二元组预筛:能走索引,而且不能改变结果。

## 为什么不是 pg_trgm

第一反应是三元组 + GIN,**实测下来它对中文基本没用**:

    查 '烧'      索引扫出 3705 行 / 全表 3705    ← 一行没滤掉
    查 '烧烤'     索引扫出 3705 行 / 全表 3705    ← 一行没滤掉
    查 '红烧肉'    索引扫出    0 行              ← 有效

三元组要**三个字符**才有选择性,而中文搜索绝大多数是两个字
(烧烤/火锅/奶茶/麻辣/米线)—— 那种情况它会做一次全索引扫再逐行 recheck,
**比全表扫还慢**。不量就加上去,等于上了一个负收益的索引。

## 这一组守什么

预筛是个**优化**,优化最怕的是把结果改了。所以这里钉的是它的正确性,
不是它的速度:

    「name 含子串 q」⇒「q 的每个二元组都出现在 name 里」

这个方向成立(没有假阴性),所以预筛不会漏;反方向不成立,会有假阳性,
由查询里保留的 ILIKE 兜住。
"""
import pytest


def bigrams(t: str) -> set[str]:
    """和 SQL 里 sz_bigrams 同一口径(迁移 0115)——**这份是判据的副本**,
    两边对不上时以 SQL 那份为准,这里跟着改。"""
    s = t.lower()
    return {s[i:i + 2] for i in range(max(len(s) - 1, 0))}


class Test预筛不会漏:
    """含子串 ⇒ 二元组被包含。反例会让整个优化变成"搜不到"。"""

    @pytest.mark.parametrize("name,q", [
        ("张记面馆", "面馆"),
        ("张记面馆", "记面"),
        ("张记面馆", "张记面馆"),
        ("老王烧烤店", "烧烤"),
        ("Coffee Bar", "ffee"),
        ("川味小炒", "小炒"),
        ("麻辣香锅", "麻辣"),
        ("A1 号食堂", "号食"),
    ])
    def test_含子串就一定被预筛放行(self, name, q):
        assert bigrams(q) <= bigrams(name), (
            f"{name!r} 含 {q!r},但二元组预筛会把它滤掉 —— 用户搜得到的东西消失了")

    @pytest.mark.parametrize("name,q", [
        ("Coffee Bar", "COFFEE"),
        ("ABC 烧烤", "abc"),
        ("abc 烧烤", "ABC"),
    ])
    def test_大小写不影响(self, name, q):
        """两边都 lower,和 ILIKE 的口径一致。

        (第一版这里写的是「张记面馆 / ZHANGJI」—— 那是拼音不是子串,
        跟大小写无关,是我把两件事混了。拼音搜索目前不支持,单列在待办里。)
        """
        assert bigrams(q) <= bigrams(name)


class Test单字查询自然退化:
    def test_单字的二元组是空集(self):
        """`@> '{}'` 对所有行成立 —— 退化成全表扫,结果仍然正确。

        不为单字加复杂度:单字搜索本来也搜不出什么。
        """
        assert bigrams("烧") == set()
        assert bigrams("") == set()

    def test_空集被任何集合包含(self):
        assert bigrams("烧") <= bigrams("老王烧烤店")


class Test假阳性由_ILIKE_兜住:
    def test_二元组够了但不是子串(self):
        """'面张' 的二元组在 '张记面馆' 里凑不齐,但换个例子能凑齐 ——
        这类假阳性必须靠查询里保留的 ILIKE 判掉。"""
        name, q = "abab", "ba"
        assert bigrams(q) <= bigrams(name)      # 预筛放行
        assert q in name                        # 这个恰好是真的
        # 真正的假阳性:二元组都在,但顺序连不起来
        name2, q2 = "ab_bc", "abc"
        assert bigrams(q2) <= bigrams(name2), "构造的例子不成立,换一个"
        assert q2 not in name2, "这个例子不是假阳性"

    def test_查询里必须保留_ILIKE(self):
        """预筛单独用会把假阳性放出去 —— 源码里两个条件必须同时在。"""
        import inspect
        import re
        from app.routers import merchants
        src = inspect.getsource(merchants.search_merchants)
        src = re.sub(r'"""(?:.|\\n)*?"""', "", src)
        assert "sz_bigrams" in src, "搜索没接上二元组预筛,索引白建"
        assert "ILIKE :pattern" in src, (
            "只剩预筛没有 ILIKE 复核 —— 二元组凑齐但不是子串的店会被搜出来")
