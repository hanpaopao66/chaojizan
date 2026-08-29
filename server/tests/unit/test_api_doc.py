"""开发者文档里的数字,必须和代码里的一致。

## 为什么值得单独一条测试

`docs/API.md` 把限流额度、可查的透明中心口径、以及「助手令牌能做什么」
都写给了外部开发者。**公开的数字对不上,比不公开更坏** ——
接入方按文档写了退避策略,而真实额度是另一个,他要么白白限速,
要么一直撞 429 却查不出原因。

这条规矩在 services/dispatch.py 的注释里已经写过一遍:
「公开的前提是只有一份」。文档不能是抄的第二份。
"""
import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[3] / "docs" / "API.md"


@pytest.fixture(scope="module")
def doc() -> str:
    assert DOC.exists(), f"找不到 {DOC}"
    return DOC.read_text()


class Test限流数字和配置一致:
    def test_逐个对上(self, doc):
        from app.config import Settings
        s = Settings(_env_file=None)
        expect = {
            "下单": s.rate_limit_order_per_minute,
            "注册": s.rate_limit_register_per_minute,
            "短信": s.rate_limit_sms_per_minute,
        }
        # **只在限流那张表里找**。第一版没限定范围,「短信」两个字
        # 命中了状态码表里的「上游(地图、短信、支付渠道)出问题」那一行 ——
        # 断言于是在拿一个完全无关的行做判据。
        # 切分隔线要用**整行**的 `\n---\n`:markdown 表格的分隔行是
        # `|---|---|`,按裸的 "---" 切会在表头就断掉,于是一行都找不到
        table = doc.split("## 三、限流", 1)[1].split("\n---\n", 1)[0]
        for label, n in expect.items():
            row = next((l for l in table.splitlines()
                        if l.startswith("|") and label in l), None)
            assert row, f"文档的限流表里没有「{label}」这一行"
            assert f"**{n}**" in row, (
                f"文档说「{label}」的额度写着别的数,而配置里是 {n}:{row.strip()}")

    def test_公开页那个数也对(self, doc):
        src = (Path(__file__).resolve().parents[2]
               / "app" / "routers" / "screen.py").read_text()
        # 调用是跨行写的,所以要允许换行(DOTALL),否则永远匹配不上 ——
        # 而匹配不上时这条测试会以「找不到」的名义红,看着像代码删了
        m = re.search(r'check_rate_limit\(\s*"screen".*?(\d+)\)', src, re.S)
        assert m, "screen.py 里找不到公开页的限流额度"
        assert f"**{m.group(1)}**" in doc, (
            f"公开页限流实际是 {m.group(1)}/分钟,文档里写的是别的数")


class Test文档里列的透明中心口径真的存在:
    def test_五个都能路由到(self, doc):
        from app.main import app
        paths = set(app.openapi()["paths"])
        listed = set(re.findall(r"GET /transparency/([a-z-]+)", doc))
        assert listed, "文档里一条透明中心接口都没列"
        for topic in listed:
            assert f"/transparency/{topic}" in paths, (
                f"文档里让开发者查 /transparency/{topic},而这个接口不存在")


class Test文档没有把业务口径抄一份:
    """抄的那份迟早和真实口径对不上,而那时候公开的是假的。"""

    @pytest.mark.parametrize("word", [
        "起步价 3 元", "每公里 1 元", "佣金 5%", "服务费 2%",
    ])
    def test_不出现具体的费率数字(self, doc, word):
        assert word not in doc, (
            f"文档里抄了一个业务数字「{word}」—— 这类口径只该有一份,"
            f"在透明中心。抄一份就是给自己埋一个说假话的时间点")


class Test助手令牌那几句和代码一致:
    def test_写操作只有一条这句话是真的(self, doc):
        from app.security import AGENT_ALLOWED
        writes = [(m, p) for m, p in AGENT_ALLOWED if m != "GET"]
        assert "**只有一条**" in doc, "文档没说清助手的写操作只有一条"
        assert len(writes) == 1, (
            f"文档说助手的写操作只有一条,实际有 {len(writes)} 条:{writes}")

    def test_文档承诺的没有支付路径是真的(self, doc):
        from app.security import agent_can
        assert "付不了钱" in doc or "不能" in doc
        for path in ("/orders/abc/pay/mock", "/orders/abc/self-refund"):
            assert not agent_can("POST", path), (
                f"文档承诺助手付不了钱,而 {path} 实际是放行的")
