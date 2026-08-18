"""小程序 initData 签名协议的锁(#277)。

一旦有第三方按 services/mini_app.py 的协议实现验签,字段序、规范化
规则、时效窗口就都改不动了 —— 这个文件就是那份协议的测试锁,
改动导致这里红,先想清楚是不是要通知所有验签方。

⚠️ **导入真代码,不复刻一份。**
"""
from app.services.mini_app import MAX_AGE_SECONDS, sign_init_data, verify_init_data


class Test签发与验签:
    def test_正常签发即验通过(self):
        pack = sign_init_data(1, 42, "张三")
        assert set(pack) == {"payload", "sign"}
        assert set(pack["payload"]) == {"app_id", "auth_date", "name", "user_id"}
        assert verify_init_data(pack["payload"], pack["sign"], app_id=1)

    def test_篡改任一字段验签失败(self):
        pack = sign_init_data(1, 42, "张三")
        for k, v in [("user_id", 43), ("name", "李四"), ("app_id", 2),
                     ("auth_date", pack["payload"]["auth_date"] + 1)]:
            assert not verify_init_data(
                dict(pack["payload"], **{k: v}), pack["sign"]), f"改 {k} 应失败"

    def test_键序打乱仍验过_验签方必须自己规范化(self):
        pack = sign_init_data(7, 1, "小王")
        shuffled = {k: pack["payload"][k]
                    for k in ["user_id", "name", "auth_date", "app_id"]}
        assert verify_init_data(shuffled, pack["sign"], app_id=7)

    def test_时效窗口边界(self):
        pack = sign_init_data(1, 42, "张三", auth_date=1_000_000)
        ok_edge = 1_000_000 + MAX_AGE_SECONDS
        assert verify_init_data(pack["payload"], pack["sign"], now=ok_edge)
        assert not verify_init_data(pack["payload"], pack["sign"], now=ok_edge + 1)
        # 时钟往回拨同样受限(abs):未来签发的包也不认
        assert not verify_init_data(
            pack["payload"], pack["sign"], now=1_000_000 - MAX_AGE_SECONDS - 1)

    def test_A应用的包到B应用验必失败(self):
        pack = sign_init_data(1, 42, "张三")
        assert not verify_init_data(pack["payload"], pack["sign"], app_id=2)

    def test_中文名不转义进签名(self):
        # 协议规定 ensure_ascii=False:验签方若用 \\uXXXX 转义,这里对不上
        pack = sign_init_data(1, 42, "王秀英")
        assert verify_init_data(pack["payload"], pack["sign"])
