"""目录排序与「不卖位置」的守卫(#326,不变量 I3)。

例子和 docs/miniapp/operations.md 的「排序规则」一节是同一组 —— 文档说什么,这里验什么。
"""
import inspect
from datetime import datetime, timedelta, timezone

from app import models
from app.services import miniapp_catalog as cat
from app.services.miniapp_catalog import CatalogItem, catalog_order, search

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def item(appid, name, days, pos=None, tagline="", dev=""):
    return CatalogItem(appid=appid, name=name, first_released_at=T0 + timedelta(days=days),
                       curation_position=pos, tagline=tagline, developer_name=dev)


def test_doc_example_order():
    # 文档例子:记事本(精选 1)、2048(精选 2)、番茄钟(9-10 上架)、单词卡(9-05 上架)
    apps = [item("sz03", "番茄钟", 9), item("sz01", "2048", 0, pos=2),
            item("sz04", "单词卡", 4), item("sz02", "记事本", 1, pos=1)]
    assert [a.name for a in catalog_order(apps)] == ["记事本", "2048", "番茄钟", "单词卡"]


def test_releasing_again_does_not_move_you_up():
    """排序只看首次上架时间:发新版不改 first_released_at,所以刷不上去。"""
    old = item("sz01", "老应用", 0)
    new = item("sz02", "新应用", 5)
    assert [a.name for a in catalog_order([old, new])] == ["新应用", "老应用"]


def test_deterministic_ties():
    a = item("sz0b", "同名", 1)
    b = item("sz0a", "同名", 1)
    assert [i.appid for i in catalog_order([a, b])] == ["sz0a", "sz0b"]
    assert catalog_order([a, b]) == catalog_order([b, a])


def test_search_tiers():
    apps = [item("sz01", "记事本", 0), item("sz02", "记事本 Pro", 3),
            item("sz03", "每日速记", 2), item("sz04", "番茄钟", 1, tagline="专注记时"),
            item("sz05", "2048", 4)]
    assert [a.name for a in search(apps, "记事本")] == ["记事本", "记事本 Pro"]
    assert [a.name for a in search(apps, "记")] == ["记事本 Pro", "记事本", "每日速记", "番茄钟"]


def test_order_function_reads_only_public_fields():
    """I3:排序函数的输入只有这几个公开字段 —— 加字段(打开次数、评分、付费)这里就红。"""
    fields = set(inspect.signature(CatalogItem).parameters)
    assert fields == {"appid", "name", "first_released_at", "curation_position",
                      "tagline", "developer_name"}
    src = inspect.getsource(cat)
    for word in ("open_count", "opens", "rating", "score", "paid", "bid", "boost"):
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("#", '"')))
        assert word not in code.split('"""', 2)[-1], word


def test_no_paid_placement_columns_anywhere_in_catalog_tables():
    """I3:目录相关的表里不允许出现能被卖的字段。"""
    forbidden = ("bid", "boost", "paid", "rank_score", "sponsor", "promoted", "ad_")
    for model in (models.MiniApp, models.MiniAppCuration, models.MiniAppVersion):
        for col in model.__table__.columns:
            assert not any(f in col.name for f in forbidden), f"{model.__name__}.{col.name}"
