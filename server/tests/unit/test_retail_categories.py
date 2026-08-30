"""品类按业态分组:key 全局唯一,校验一律按业态(#304)。

## 这组测试守什么

加零售业态时,「品类」从一张平表变成了按业态分组。而 `Merchant.category`
仍然是**一列** —— 这两件事合起来产生两个坑,加零售那天两个都踩了:

1. **key 撞车。** `snacks` 在餐饮里已经是「特色小吃」,零售的「休闲零食」
   如果也叫 `snacks`,那么光看 category 这一列分不出它属于哪个业态,
   得联合 biz_type 才能解释一个值 —— 自找的麻烦。
2. **拿合并表做校验。** 入驻、改店铺设置、后台纠错**三处**当时都还在查
   合并表,于是一家快餐店能把自己归到「母婴玩具」。三处漏了三处,
   说明这类遗漏靠自觉防不住,得有测试兜着。

第 2 条是 `e2e_category` 先抓出来的(它断言品类接口正好 23 个),
这里把它固化成单测,并把三个校验点逐个点名。
"""
import inspect

import pytest

from app import categories as C


class Test_key全局唯一:
    def test_餐饮与零售不重名(self):
        dup = set(C.FOOD_CATEGORIES) & set(C.RETAIL_CATEGORIES)
        assert not dup, (
            f"品类 key 撞车:{sorted(dup)} —— category 只有一列,"
            f"撞了就得靠 biz_type 联合才能解释一个值")

    def test_合并表条数等于两边之和(self):
        """撞车的话合并表会短几条,这是同一件事的另一个观测点。"""
        assert len(C.MERCHANT_CATEGORIES) == (
            len(C.FOOD_CATEGORIES) + len(C.RETAIL_CATEGORIES))

    def test_导入时就会炸(self):
        """撞车不该等到线上出现一个解释不了的品类值。"""
        assert callable(C._assert_unique)
        orig = C.RETAIL_CATEGORIES.copy()
        try:
            C.RETAIL_CATEGORIES["fast_food"] = "故意撞车"
            with pytest.raises(RuntimeError, match="重名"):
                C._assert_unique()
        finally:
            C.RETAIL_CATEGORIES.clear()
            C.RETAIL_CATEGORIES.update(orig)
        C._assert_unique()   # 还原之后必须还是干净的


class Test按业态取品类:
    def test_餐饮取不到零售品类(self):
        assert "mom_baby" not in C.categories_of("food")

    def test_零售取不到餐饮品类(self):
        assert "sichuan_hunan" not in C.categories_of("retail")

    def test_未知业态给空而不是兜底到餐饮(self):
        """住宿不用品类(档次在 hotel_profiles.tier)。给空不给兜底 ——
        兜底会让酒店莫名其妙地能选「快餐便当」。"""
        assert C.categories_of("hotel") == {}
        assert C.categories_of("") == {}

    def test_每个业态都有默认品类(self):
        for biz in C.CATEGORIES_BY_BIZ:
            assert C.DEFAULT_CATEGORY_BY_BIZ[biz] in C.CATEGORIES_BY_BIZ[biz]


class Test三个校验点都按业态:
    """三处当时都漏了。逐个点名,别再靠自觉。"""

    def _src(self, fn):
        return inspect.getsource(fn)

    def test_入驻(self):
        from app.routers.merchants import apply_shop
        src = self._src(apply_shop)
        assert "categories_of(payload.biz_type)" in src, "入驻还在查合并表"

    def test_改店铺设置(self):
        from app.routers.merchants import update_my_shop
        assert "categories_of(shop.biz_type)" in self._src(update_my_shop), \
            "改店铺设置还在查合并表"

    def test_后台纠错(self):
        from app.routers.admin import set_merchant_category
        assert "categories_of(shop.biz_type)" in \
            self._src(set_merchant_category), "后台纠错还在查合并表"

    def test_列表筛选(self):
        from app.routers.merchants import list_merchants
        assert "CATEGORIES_BY_BIZ[biz_type]" in self._src(list_merchants)


class Test品类接口的默认值:
    def test_不带参数给餐饮不给合并表(self):
        """这个接口喂的是商家端的品类下拉,所以必须是**某一个业态**的清单。
        给合并表意味着快餐店的下拉里出现「母婴玩具」,选了之后服务端才报错。
        e2e_category 断言它正好 23 个。"""
        from app.routers.merchants import merchant_categories
        src = inspect.getsource(merchant_categories)
        assert "return FOOD_CATEGORIES" in src
        assert "return MERCHANT_CATEGORIES" not in src
