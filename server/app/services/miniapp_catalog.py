"""小程序目录的排序规则(#326,不变量 I3)。

**不卖位置、不做个性化推荐。** 排序是下面两个纯函数,只读公开字段:
精选位次、首次上架时间、名称。规则原文写在文档(docs/miniapp/operations.md)和透明中心,
tests/unit/test_miniapp_catalog.py 用文档里的例子逐条验。

- 精选在前,按精选位次升序(位次相同按首次上架早的在前);
- 其余按**首次上架时间**倒序 —— 不用 updated_at:反复发版刷不上去;
- 首次上架时间相同(几乎不会)按名称,再按 appid,保证结果确定;
- 搜索:名称精确命中 > 名称前缀 > 名称包含 > 一句话简介或开发者名包含;同一档内按上面的目录规则。

这里**故意没有**「打开次数」「评分」「收藏数」—— 热度排序就是马太效应,
而且是一种推荐。想加任何排序因子,先改文档、走规则留痕,再改这里。
"""
from dataclasses import dataclass
from datetime import datetime, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class CatalogItem:
    appid: str
    name: str
    first_released_at: datetime | None
    curation_position: int | None = None
    tagline: str = ""
    developer_name: str = ""


def _released(it: CatalogItem) -> datetime:
    return it.first_released_at or _EPOCH


def catalog_order(items: list[CatalogItem]) -> list[CatalogItem]:
    curated = sorted((i for i in items if i.curation_position is not None),
                     key=lambda i: (i.curation_position, _released(i), i.name, i.appid))
    rest = sorted((i for i in items if i.curation_position is None),
                  key=lambda i: (-_released(i).timestamp(), i.name, i.appid))
    return curated + rest


def search_rank(item: CatalogItem, q: str) -> int | None:
    """0 精确、1 前缀、2 名称包含、3 简介或开发者名包含;不命中 None。大小写不敏感。"""
    q = q.strip().lower()
    if not q:
        return 0
    name = item.name.lower()
    if name == q:
        return 0
    if name.startswith(q):
        return 1
    if q in name:
        return 2
    if q in item.tagline.lower() or q in item.developer_name.lower():
        return 3
    return None


def search(items: list[CatalogItem], q: str) -> list[CatalogItem]:
    ranked = [(r, i) for i in items if (r := search_rank(i, q)) is not None]
    order = {i.appid: n for n, i in enumerate(catalog_order([i for _, i in ranked]))}
    return [i for _, i in sorted(ranked, key=lambda p: (p[0], order[p[1].appid]))]
