"""坐标必须有范围:纬度 ±90、经度 ±180。

## 为什么单独一条

浮点字段不设范围,`Infinity` 就能穿进来 —— 而 Infinity 参与运算的结果是
`OverflowError: cannot convert float infinity to integer`,也就是一个裸 500。
实测过:下单时 `{"lat": Infinity}` → HTTP 500。

越界但有限的坐标(纬度 999)不会 500,但会走到「超出配送范围(4km),
换家近点的店吧」—— **坐标是坏的,却建议用户换家店**,这个提示是误导。

## 为什么是全库一起改而不是只改下单

坏坐标的影响面按入口不同差很多:

- `OrderCreateIn` / `AddressIn`:影响这一单、这个人;
- `LocationIn`(骑手上报):影响这个骑手看到的跑程,他可能据此接了远单;
- `MerchantIn`(商家自己设店铺坐标):**影响所有从这家店下单的人** ——
  「附近的店」和每一单的配送费都从它算。

所以判据是「凡是坐标就必须在地球上」,不是「下单这条路要小心」。
"""
import inspect
import types
import typing

import pytest
from pydantic import BaseModel, ValidationError

from app import schemas

COORD_FIELDS = ("lat", "lng", "pickup_lat", "pickup_lng")


def input_models():
    for name, obj in vars(schemas).items():
        if (inspect.isclass(obj) and issubclass(obj, BaseModel)
                and obj is not BaseModel):
            yield name, obj


def bases(ann):
    if isinstance(ann, types.UnionType) or typing.get_origin(ann) is typing.Union:
        return [a for a in typing.get_args(ann) if a is not type(None)]
    return [ann]


def bounds(field):
    lo = hi = None
    for m in field.metadata:
        lo = getattr(m, "ge", None) if getattr(m, "ge", None) is not None else lo
        hi = getattr(m, "le", None) if getattr(m, "le", None) is not None else hi
    return lo, hi


class Test每个坐标字段都有范围:
    def test_没有裸的坐标浮点(self):
        naked = []
        for name, obj in input_models():
            for f, fi in obj.model_fields.items():
                if f not in COORD_FIELDS or float not in bases(fi.annotation):
                    continue
                if bounds(fi) == (None, None):
                    naked.append(f"{name}.{f}")
        assert not naked, (
            f"这些坐标没有范围约束:{naked} —— "
            f"Infinity 穿进来就是 500,越界值则给出误导提示")

    def test_范围就是地球的范围(self):
        wrong = []
        for name, obj in input_models():
            for f, fi in obj.model_fields.items():
                if f not in COORD_FIELDS or float not in bases(fi.annotation):
                    continue
                lo, hi = bounds(fi)
                want = (-90, 90) if f.endswith("lat") else (-180, 180)
                if (lo, hi) != want:
                    wrong.append(f"{name}.{f}: {(lo, hi)} 应为 {want}")
        assert not wrong, "\n".join(wrong)


class Test下单时的坐标:
    @pytest.mark.parametrize("lat,lng", [
        (float("inf"), 104.0),
        (float("-inf"), 104.0),
        (30.6, float("inf")),
        (999.0, 104.0),
        (30.6, 400.0),
        (-91.0, 104.0),
    ])
    def test_坏坐标当场被拒(self, lat, lng):
        with pytest.raises(ValidationError):
            schemas.OrderCreateIn(
                merchant_id=1, items=[{"dish_id": 1, "quantity": 1}],
                lat=lat, lng=lng)

    def test_正常坐标照常通过(self):
        o = schemas.OrderCreateIn(
            merchant_id=1, items=[{"dish_id": 1, "quantity": 1}],
            lat=30.66, lng=104.08)
        assert o.lat == 30.66

    def test_不传坐标仍然可以(self):
        """自提单不需要坐标 —— 加了范围不能顺手改成必填。"""
        o = schemas.OrderCreateIn(
            merchant_id=1, items=[{"dish_id": 1, "quantity": 1}], pickup=True)
        assert o.lat is None


class Test派单看不到骑手身份:
    """`dispatch` 的模块注释承诺「不按骑手评分/等级差别对待」。

    原来只有一条测试检查**公示文案里写着这句话** —— 那是在测承诺有没有印出来,
    不是在测承诺有没有被遵守。这条钉住结构:排序的入参里根本没有
    骑手身份相关的字段,所以做不到差别对待。
    """

    def test_候选单里没有骑手身份字段(self):
        from app.services.dispatch import Candidate
        fields = set(Candidate.__dataclass_fields__)
        forbidden = {"rider_id", "rating", "rider_rating", "level",
                     "rider_level", "score", "grade", "tier"}
        assert not (fields & forbidden), (
            f"派单的候选单里出现了骑手身份/评分字段:{fields & forbidden} —— "
            f"「不按评分差别对待」这句公示就不再是结构上保证的了")


class Test校验错误自己不能炸:
    """422 的错误体会**回显收到的那个值**,而 Infinity / NaN 不是合法 JSON。

    表现很反直觉:**校验越严,这个 500 越容易撞上** —— 加了坐标范围之后,
    `{"lat": Infinity}` 从"混进去算出个怪数"变成"校验拒绝它,
    然后序列化这条 422 的时候炸掉",用户拿到的还是 500。

        ValueError: Out of range float values are not JSON compliant

    跟字段是不是坐标无关,任何 float 入参都这样,所以修在错误处理器上。
    """

    def test_非有限浮点被换成可编码的写法(self):
        from app.main import _json_safe
        out = _json_safe({"input": float("inf"), "loc": ["body", "lat"]})
        assert out["input"] == "inf"
        assert out["loc"] == ["body", "lat"]

    def test_nan_与负无穷同理(self):
        from app.main import _json_safe
        assert _json_safe(float("nan")) == "nan"
        assert _json_safe(float("-inf")) == "-inf"

    def test_正常值原样不动(self):
        """只动不能编码的那部分 —— 「你传的是什么」是排查的关键,
        整段删掉的话客户端只知道有个字段不对,不知道不对在哪。"""
        from app.main import _json_safe
        src = {"a": 1, "b": "x", "c": [1.5, True, None], "d": {"e": 2.5}}
        assert _json_safe(src) == src

    def test_结果真的能被_json_编码(self):
        """这条才是要害:上面几条都对、但整体仍编码不了的话,还是 500。"""
        import json
        from app.main import _json_safe
        payload = [{"type": "less_than_equal", "loc": ["body", "lat"],
                    "input": float("inf"), "ctx": {"le": 90.0}}]
        json.dumps(_json_safe(payload))   # 不抛就是过
