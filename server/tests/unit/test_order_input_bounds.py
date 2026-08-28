"""下单入参的边界:超长不能变成 500,电话不能是垃圾。

## 这一组守什么

`/orders` 是全站最重要的接口,而它的入参里最早那批字符串字段
**一个长度上限都没有**,库里那几列却是 String(200)/String(50)/String(20)。
于是备注写到 201 个字,用户拿到的是裸的 `Internal Server Error` ——
重试还是 500,他不知道哪里错了,也没法绕过去。

实测过:150 字 → 200,201 字 → 500。

有意思的是**后加的字段都设了上限**(address_public 200、salutation 12、
floor 范围、tip_cents 范围),最早那批没有 —— 纪律是后来建立的,
老字段没人回补。所以这里用一条**通用断言**盯住整个模型,
而不是逐个字段列举:以后新加的字段也一样被管着。
"""
import pytest
from pydantic import ValidationError

from app.models import Order
from app.schemas import OrderCreateIn


def max_len(field) -> int | None:
    for m in field.metadata:
        if getattr(m, "max_length", None):
            return m.max_length
    return None


class Test每个字符串入参都有上限:
    def test_没有裸的_str_字段(self):
        missing = [n for n, f in OrderCreateIn.model_fields.items()
                   if f.annotation is str and max_len(f) is None]
        assert not missing, (
            f"这些字段没有长度上限:{missing} —— "
            f"超过库里那一列的长度就是裸 500,用户看到 Internal Server Error")

    def test_上限不超过库里那一列(self):
        """设了上限还不够,**上限必须 ≤ 列宽**,否则照样 500。"""
        cols = {c.name: c.type.length for c in Order.__table__.columns
                if hasattr(c.type, "length") and c.type.length}
        bad = []
        for name, f in OrderCreateIn.model_fields.items():
            if f.annotation is not str or name not in cols:
                continue
            lim = max_len(f)
            if lim is None or lim > cols[name]:
                bad.append(f"{name}: 入参上限 {lim} > 列宽 {cols[name]}")
        assert not bad, "\n".join(bad)


class Test超长直接被拒而不是落到库里炸:
    @pytest.mark.parametrize("field", ["remark", "address",
                                       "contact_name", "contact_phone"])
    def test_超长报_422_而不是穿到库里(self, field):
        with pytest.raises(ValidationError):
            OrderCreateIn(merchant_id=1, items=[{"dish_id": 1, "quantity": 1}],
                          **{field: "啊" * 5000})


class Test联系电话:
    """骑手拨的就是这个号。空号意味着这一单出岔子就没法收场。"""

    def test_乱填被拒(self):
        with pytest.raises(ValidationError):
            OrderCreateIn(merchant_id=1, items=[{"dish_id": 1, "quantity": 1}],
                          contact_phone="abcdefg")

    def test_少一位被拒(self):
        with pytest.raises(ValidationError):
            OrderCreateIn(merchant_id=1, items=[{"dish_id": 1, "quantity": 1}],
                          contact_phone="1380000000")

    def test_空是允许的(self):
        """**不在这里硬性必填。**

        号码服务端本来就有(账号手机号),让客户端再传一遍是没意义的仪式;
        自提单和加菜单也确实用不上它。空值由路由层回落到账号手机号 ——
        见下面那条。
        """
        o = OrderCreateIn(merchant_id=1, items=[{"dish_id": 1, "quantity": 1}])
        assert o.contact_phone == ""

    def test_路由在空的时候回落到账号手机号(self):
        """回落比存一个空串好:骑手到了楼下总能打通一个号。"""
        import inspect
        import re
        src = inspect.getsource(
            __import__("app.routers.orders", fromlist=["x"]).create_order)
        src = re.sub(r'"""(?:.|\n)*?"""', "", src)
        src = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        assert "user.phone" in src, (
            "下单时联系电话为空却没有回落到账号手机号 —— "
            "订单里存的是空串,而骑手拨的就是它")
