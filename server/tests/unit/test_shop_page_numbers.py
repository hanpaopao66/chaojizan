"""单元测试:店铺页上「同一件事只有一个数」的几处。

- 评分:店铺页的「4.8 分」(商家表的 rating_avg)和评价概览的均分走同一个取整函数;
- 起送价:下单拦的和客户端显示的都是 effective_min_order_cents;
- 评价筛选:列表和概览的计数共用同一份筛选条件;
- 拼单:一行按(人, 菜, 规格, 备注)认,备注下单时拼进订单备注。

纯函数,不起服务、不连库。
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import settings  # noqa: E402
from app.models import Merchant, rating_avg_of  # noqa: E402
from app.routers.group_cart import (  # noqa: E402
    GROUP_NOTE_MAX,
    NOTE_MAX,
    line_key,
    order_note_for,
)
from app.routers.reviews import REVIEW_FILTERS, review_filter_clause  # noqa: E402


class TestRatingOneNumber:
    @pytest.mark.parametrize("total,count", [
        (4285, 890), (17, 4), (85, 20), (21, 5), (9, 2), (1, 1), (5, 1)])
    def test_店铺页的分和概览的分是同一个函数算的(self, total, count):
        shop = Merchant(rating_sum=total, rating_count=count)
        assert shop.rating_avg == rating_avg_of(total, count)

    def test_没有评价是空不是零(self):
        """0 分会被当成「这家店很差」,没评价就该说没评价。"""
        assert rating_avg_of(0, 0) is None
        assert Merchant(rating_sum=0, rating_count=0).rating_avg is None

    def test_一位小数(self):
        assert rating_avg_of(4285, 890) == 4.8
        assert rating_avg_of(19, 4) == 4.8


class TestEffectiveMinOrder:
    def test_商家没设起送价时按平台下限(self):
        """设成 0 的店原来页面上写「起送 ¥0」,凑了 ¥12 到结算才被拒。"""
        floor = settings.min_order_floor_cents
        assert Merchant(min_order_cents=0).effective_min_order_cents == floor

    def test_商家设得比下限低也按下限(self):
        floor = settings.min_order_floor_cents
        assert Merchant(min_order_cents=floor - 500).effective_min_order_cents == floor

    def test_商家设得更高就按商家的(self):
        high = settings.min_order_floor_cents + 500
        assert Merchant(min_order_cents=high).effective_min_order_cents == high


def _sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(),
                              compile_kwargs={"literal_binds": True}))


class TestReviewFilters:
    def test_五个筛选(self):
        assert REVIEW_FILTERS == ("all", "photo", "good", "bad", "append")
        assert review_filter_clause("all") is None

    def test_好评四到五星_差评一到二星(self):
        """和用户端透明中心「差评占比(1–2 星)」同一口径,3 星两边都不算。"""
        assert _sql(review_filter_clause("good")) == "reviews.merchant_rating >= 4"
        assert _sql(review_filter_clause("bad")) == "reviews.merchant_rating <= 2"

    def test_有图看首评和追评的图(self):
        sql = _sql(review_filter_clause("photo"))
        assert "reviews.image_urls" in sql and "reviews.append_images" in sql
        assert " OR " in sql

    def test_有追评看追评时间(self):
        assert _sql(review_filter_clause("append")) == "reviews.append_at IS NOT NULL"


class TestGroupCartLines:
    def test_规格先后顺序不算不同的行(self):
        assert line_key(1, 9, ["微辣", "大份"], "") == line_key(1, 9, ["大份", "微辣"], "")

    def test_规格或备注不同就是不同的行(self):
        assert line_key(1, 9, ["大份"], "") != line_key(1, 9, ["小份"], "")
        assert line_key(1, 9, [], "不要香菜") != line_key(1, 9, [], "")
        assert line_key(1, 9, [], "") != line_key(2, 9, [], "")

    def test_老车里没有这两个字段的行按空的算(self):
        """上线前开的车还在 Redis 里,那些行没有 choices / note。"""
        assert line_key(1, 9, None, None) == line_key(1, 9, [], "")
        assert line_key(1, 9, [], "  少辣 ") == line_key(1, 9, [], "少辣")

    def test_备注拼进订单备注_没写的不拼(self):
        cart = {"items": [
            {"by": "孙七", "name": "牛肉面", "note": "不要香菜"},
            {"by": "赵六", "name": "油泼扯面(大份+微辣)", "note": ""},
            {"by": "王小明", "name": "卤蛋"},
        ]}
        # 不带是谁点的:订单备注商家、骑手都看得到,同伴的昵称不该跟着出去
        assert order_note_for(cart) == "拼单备注 牛肉面:不要香菜"
        assert order_note_for({"items": []}) == ""

    def test_整车备注和用户自己的备注加起来放得进订单备注(self):
        """订单备注 String(200);App 里用户自己写的限 100 字,中间一个空格。
        整车备注超了在加菜时 422,下单时就不会被截断。"""
        from app.models import Order

        assert 100 + 1 + GROUP_NOTE_MAX <= Order.__table__.c.remark.type.length
        # 一道菜的备注写满也能单独放进去
        one = order_note_for({"items": [
            {"by": "王小明", "name": "油泼扯面(大份+加牛肉+微辣)", "note": "字" * NOTE_MAX}]})
        assert len(one) <= GROUP_NOTE_MAX
