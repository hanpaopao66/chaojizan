"""收藏分页:翻页不漏不重,老客户端(不传参数)照常。

老口径是服务端写死 limit(100) 且没有分页参数 —— 收藏满 100 家的人
第 101 家起永远看不到,界面上只表现为「我明明收藏过,它不见了」。

这条守住三件事:老调用方口径不变、翻页拼回来等于全集、页边界不错行。
全集口径拿 /favorites/ids(它本来就不截断),所以演示库收藏多少家
这条都成立 —— 有人把 100 的硬上限改回来,这里会当场炸。
"""
from .util import CUSTOMER, MERCHANT, call, demo_shop, login

PAGE = 3  # 故意取小,演示库收藏再少也能翻出好几页


def _walk(token, page=PAGE):
    """按 page 大小翻完整个收藏列表。"""
    out, offset = [], 0
    while True:
        got = call("GET", f"/favorites?limit={page}&offset={offset}",
                   token=token)
        assert len(got) <= page, got
        out.extend(got)
        if len(got) < page:
            return out
        offset += page


def main() -> None:
    token = login(CUSTOMER)

    # 全集口径:/favorites/ids 不分页也不截断
    all_ids = call("GET", "/favorites/ids", token=token)
    total = len(all_ids)
    print(f"✓ 演示用户共收藏 {total} 家(/favorites/ids 全集口径)")

    # 老客户端:不传参数照常拿一页(默认上限 100)
    plain = call("GET", "/favorites", token=token)
    assert isinstance(plain, list), plain
    assert len(plain) == min(total, 100), (len(plain), total)
    print(f"✓ 不传分页参数返回 {len(plain)} 家,仍是纯 list(老客户端不受影响)")

    walked = _walk(token)
    ids = [m["id"] for m in walked]
    assert len(ids) == len(set(ids)), "翻页出现重复的店"
    assert len(ids) == total, f"翻页只拿到 {len(ids)} 家,全集是 {total} 家"
    assert set(ids) == set(all_ids), "翻页拿到的店与全集对不上"
    print(f"✓ 每页 {PAGE} 家翻完 {len(ids)} 家:不重复、不漏、与全集一致")

    # 页边界不错行:翻页的前 N 家必须与不分页的前 N 家逐位相同。
    # 只按 created_at 排序时同刻收藏的几家在边界上会串位,这条能抓到
    head = [m["id"] for m in plain]
    assert ids[:len(head)] == head, "翻页与整页的顺序对不上(排序键不是全序?)"
    print("✓ 翻页顺序与整页逐位一致(排序键含 merchant_id,同刻收藏也不串位)")

    # 越过末尾:返回空 list,不是报错
    beyond = call("GET", f"/favorites?limit={PAGE}&offset={total}", token=token)
    assert beyond == [], beyond
    print("✓ offset 越过末尾返回空 list")

    # 上限保护:超过 100 由 FastAPI 挡在门口
    bad = call("GET", "/favorites?limit=101", token=token, expect_error=True)
    assert bad["_error"] == 422, bad
    bad = call("GET", "/favorites?offset=-1", token=token, expect_error=True)
    assert bad["_error"] == 422, bad
    print("✓ limit>100 / offset<0 一律 422")

    # 最新收藏的排在最前:排序键在重构后仍然生效
    sid = demo_shop()["id"]
    was_favorited = sid in all_ids
    if was_favorited:
        call("DELETE", f"/favorites/{sid}", token=token)
    call("POST", f"/favorites/{sid}", token=token)
    first = call("GET", "/favorites?limit=1", token=token)
    assert first and first[0]["id"] == sid, first
    print(f"✓ 刚收藏的 {sid} 号店排在第一位(按收藏时间倒序)")
    if not was_favorited:  # 跑之前没收藏就还原,套件可重复跑
        call("DELETE", f"/favorites/{sid}", token=token)

    # 角色闸门:分页参数不是绕开鉴权的口子
    err = call("GET", "/favorites?limit=1", token=login(MERCHANT),
               expect_error=True)
    assert err["_error"] == 403, err
    print("✓ 带分页参数同样只限用户角色(403)")

    print("\ne2e_favorites_paging 全部通过 ✅")


if __name__ == "__main__":
    main()
