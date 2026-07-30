"""可下发文案与帮助中心问答(#122)。

这条守的不是"能不能改文案",而是**哪些文案不许改**:
承诺类("总负担 5% 封顶")必须由服务端按真实费率算出来,后台改不了。
一旦它变成后台可填的自由文本,任何人都能把它写成「3% 封顶」而实际照抽 5%,
承诺就退化成广告词——整个透明叙事的地基就在这几句话上。
"""
from .util import ADMIN, CUSTOMER, call, login


def main() -> None:
    a_token = login(ADMIN)

    cfg = call("GET", "/config")
    assert isinstance(cfg["copy"], dict) and cfg["copy"], cfg
    assert isinstance(cfg["faq"], list), cfg
    assert cfg["rev"], "缺内容版本号"
    print(f"✓ /config 下发 {len(cfg['copy'])} 条文案 / "
          f"{len(cfg['faq'])} 条问答,rev={cfg['rev']}")

    # --- 承诺类:服务端算出来的,且与真实费率一致 ---
    pledge = cfg["copy"]["pledge.commission"]
    # 费率口径以商家真实费率为准:演示店的 commission_rate 不得高于承诺上限
    shop = call("GET", "/merchants/1")
    cap_in_copy = float(pledge.split("%")[0].split()[-1]) / 100
    assert float(shop["commission_rate"]) <= cap_in_copy + 1e-9, (
        f"承诺文案写的是 {cap_in_copy:.3f} 封顶,但演示店实际费率 "
        f"{shop['commission_rate']} 更高 —— 这就是说假话")
    assert "100%" in pledge and "骑手" in pledge, pledge
    print(f"✓ 承诺文案与真实费率一致:{pledge}")

    # --- 承诺类不能被后台改 ---
    denied = call("PUT", "/admin/copy/pledge.commission", token=a_token,
                  body={"text": "商家总负担 3% 封顶,配送费 100% 归骑手"},
                  expect_error=True)
    assert denied["_error"] == 422, denied
    assert "真实费率" in str(denied["detail"]), denied
    print(f"✓ 改承诺文案被拒:{denied['detail']}")

    # 拒了之后下发值必须没变(不是"拒了但其实写进去了")
    assert call("GET", "/config")["copy"]["pledge.commission"] == pledge
    print("✓ 被拒后下发值未被改动")

    # 删也不行
    denied = call("DELETE", "/admin/copy/pledge.rider", token=a_token,
                  expect_error=True)
    assert denied["_error"] == 422, denied
    print("✓ 删承诺文案同样被拒")

    # --- 说明性文案:能改,改完立刻下发 ---
    key = "home.category_vacancy"
    original = cfg["copy"].get(key)
    call("PUT", f"/admin/copy/{key}", token=a_token,
         body={"text": "该品类正在招商中(e2e 改过)"})
    after = call("GET", "/config")
    assert after["copy"][key] == "该品类正在招商中(e2e 改过)", after["copy"][key]
    assert after["rev"] != cfg["rev"], "内容变了 rev 却没变"
    print(f"✓ 说明性文案可改,rev 随之变化({cfg['rev']} → {after['rev']})")

    # 空文案被拒(别把点位改成空白)
    bad = call("PUT", f"/admin/copy/{key}", token=a_token,
               body={"text": "   "}, expect_error=True)
    assert bad["_error"] == 422, bad
    print("✓ 空文案被拒")

    # 删除 = 回退到客户端本地默认值(不是变空白)
    call("DELETE", f"/admin/copy/{key}", token=a_token)
    assert key not in call("GET", "/config")["copy"], "删了还在下发"
    print("✓ 删除后不再下发,客户端回退到本地默认值")
    if original is not None:  # 还原,不给别的用例留脏数据
        call("PUT", f"/admin/copy/{key}", token=a_token, body={"text": original})

    # --- FAQ 整表替换 ---
    call("PUT", "/admin/faq", token=a_token, body={"items": [
        {"q": "e2e 问题一", "a": "e2e 答案一"},
        {"q": "e2e 问题二", "a": "e2e 答案二"},
    ]})
    faq = call("GET", "/config")["faq"]
    assert [f["q"] for f in faq] == ["e2e 问题一", "e2e 问题二"], faq
    print(f"✓ FAQ 整表替换,顺序即提交顺序({len(faq)} 条)")

    bad = call("PUT", "/admin/faq", token=a_token,
               body={"items": [{"q": "只有问题", "a": ""}]}, expect_error=True)
    assert bad["_error"] == 422, bad
    print("✓ 空答案被拒")

    call("PUT", "/admin/faq", token=a_token, body={"items": []})
    assert call("GET", "/config")["faq"] == [], "清空失败"
    print("✓ 清空 FAQ 后客户端回退到本地默认值")

    # --- 越权 ---
    c_token = login(CUSTOMER)
    for method, path in (("GET", "/admin/copy"),
                         ("PUT", "/admin/copy/x"),
                         ("PUT", "/admin/faq")):
        r = call(method, path, token=c_token,
                 body={"text": "x", "items": []}, expect_error=True)
        assert r["_error"] in (401, 403), (method, path, r)
    print("✓ 顾客态访问后台文案接口全部被拒")

    print("\n全部通过:可下发文案与承诺锁定")


if __name__ == "__main__":
    main()
