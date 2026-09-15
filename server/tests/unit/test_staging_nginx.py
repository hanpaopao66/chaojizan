"""预发 nginx 配置生成器(scripts/gen_staging_nginx.py,docs/STAGING.md)。

预发的意义是和生产一样,所以 location 段必须从生产 superz.conf 原样照抄。这里守住:
标记还在、生产的 location 一个不少、预发自己加的证书和门禁都在,以及门禁里那个
「return 早于 auth_basic 执行」的坑没有被人顺手改回去。
"""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PROD = ROOT / "deploy" / "nginx" / "conf.d" / "superz.conf"


def _gen():
    spec = importlib.util.spec_from_file_location(
        "gen_staging_nginx", ROOT / "scripts" / "gen_staging_nginx.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _locations(text: str) -> list[str]:
    return [" ".join(m.split()) for m in re.findall(r"^\s*location\s+[^{]+\{", text, re.M)]


def _block(text: str, head: str) -> str:
    start = text.index(head)
    return text[start:text.index("}", start)]


def test_prod_locations_all_copied():
    gen = _gen()
    src = PROD.read_text(encoding="utf-8")
    _, prod_part = gen.split(src)
    staging = _locations(gen.render(src))
    prod = _locations(prod_part)
    assert prod, "locations-begin 和 locations-end 之间一个 location 都没有:标记放错了"
    for loc in prod:
        assert loc in staging, f"预发少了生产的 {loc}"
    # 预发只比生产多一个门禁
    assert sorted(staging) == sorted(prod + ["location = /__gate {"])


def test_http_part_is_verbatim():
    gen = _gen()
    src = PROD.read_text(encoding="utf-8")
    http, _ = gen.split(src)
    assert http in gen.render(src)
    assert "log_format superz_masked" in http


def test_staging_cert_and_gate():
    out = _gen().render(PROD.read_text(encoding="utf-8"))
    assert "certs/chaojizan" not in out
    assert "server_name chaojizan.cc" not in out
    assert "ssl_certificate     /etc/nginx/certs/staging/fullchain.pem;" in out
    assert "auth_basic_user_file /etc/nginx/staging-gate/htpasswd;" in out
    # 对外是非标准端口:跳转必须是相对地址,反代给 api 的 Host 要带端口
    assert "absolute_redirect off;" in out
    assert "proxy_set_header Host $host;" not in out
    assert "proxy_set_header Host $http_host;" in out
    # return 在 rewrite 阶段执行,早于 auth_basic —— 门禁 location 里一旦有 return 指令,密码框就不会弹
    assert not re.search(r"^\s*return\b", _block(out, "location = /__gate"), re.M)


@pytest.mark.parametrize("breakage", [
    lambda s: s.replace("# [staging] locations-end", "# (删掉了)"),
    lambda s: s + "\n# [staging] http-end\n",
    lambda s: s.replace("# [staging] http-end", "# (挪走)", 1).replace(
        "    # [staging] locations-end", "    # [staging] locations-end\n# [staging] http-end"),
])
def test_broken_markers_fail_loudly(breakage):
    gen = _gen()
    with pytest.raises(ValueError):
        gen.split(breakage(PROD.read_text(encoding="utf-8")))
