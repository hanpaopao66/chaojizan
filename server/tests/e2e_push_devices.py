"""自建推送:设备登记与选路(#384)。

推送原本走极光(服务端只认 `u{user_id}` 别名,设备 token 在极光那边)。自己发之后,
设备地址存在我们自己的 `push_devices` 表里,发的时候按设备选通道。

守的是:

- 登记是幂等的,每次启动都能调;不认识的通道**当场拒**(打错一个字的后果是
  这台设备再也收不到推送,而接口会高高兴兴回 200);
- **一个 token 只属于一台设备**:换人登录时那一行改挂过去,不是新插一行 ——
  不然上一个人退出登录之后,推送还继续发到这台手机上;
- 名下**有**自建设备就走自建那条路(这里 APNs 没配,所以 push_logs 里写的是
  「apns 没配」而不是「没有可用通道」—— 这一句就是选路走对了的证据);
- 退出登录(下线设备)之后又回到没有可用通道;
- 注销账号把名下设备全下线 —— 账号都没了还在弹「你有一条新消息」是最刺眼的残留。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_push_devices
"""
import random
import time

from tests.chat_util import person
from tests.miniapp_util import sql
from tests.util import call


def logs(user_id: int) -> list[tuple]:
    rows = sql("select title, error from push_logs where user_id = :u order by id desc",
               {"u": user_id}, fetch="all")
    return [tuple(r) for r in rows]


def wait_log(user_id: int, n: int = 1, *, seconds: float = 8.0) -> list[tuple]:
    end = time.time() + seconds
    got: list[tuple] = []
    while time.time() < end:
        got = logs(user_id)
        if len(got) >= n:
            return got
        time.sleep(0.3)
    return got


def devices(user_id: int) -> list[tuple]:
    rows = sql("""select channel, token, app, sandbox, disabled_at is null
                    from push_devices where user_id = :u order by id""",
               {"u": user_id}, fetch="all")
    return [tuple(r) for r in rows]


def main():
    me, friend = person(), person()
    token = f"apnstok{random.getrandbits(48):012x}"
    print(f"  账号:收推送的={me.id} 发消息的={friend.id}")

    # ---- 登记 ----
    r = me.post("/push/v1/devices", {"channel": "apns", "token": token, "app": "user",
                                     "sandbox": True})
    assert r["channel"] == "apns" and r["app"] == "user", r
    assert devices(me.id) == [("apns", token, "user", True, True)], devices(me.id)
    print("  ✓ 登记成功")

    # 每次启动都调一次:幂等,不多出一行
    me.post("/push/v1/devices", {"channel": "apns", "token": token, "app": "user",
                                 "sandbox": True})
    assert len(devices(me.id)) == 1, devices(me.id)
    print("  ✓ 再登记一次不多占一行(客户端每次启动都会调)")

    # ---- 不认识的通道当场拒 ----
    e = call("POST", "/push/v1/devices", me.token,
             {"channel": "aqns", "token": token + "x"}, expect_error=True)
    assert e.get("_error") == 422, e
    print("  ✓ 通道名打错了回 422,不是默默收下")

    # ---- 名下有设备:走自建那条路 ----
    pv = friend.private_with(me)
    friend.send(pv["id"], "在吗")
    got = wait_log(me.id, 1)
    assert got, "该有一条推送记录"
    assert "apns" in got[0][1], f"名下有 apns 设备就该走 apns,而不是回落:{got}"
    print(f"  ✓ 走了自建通道(记录里是「{got[0][1]}」,APNs 没配所以发不出去,但路走对了)")

    # ---- 同一个 token 换人登录:改挂,不新插 ----
    friend.post("/push/v1/devices", {"channel": "apns", "token": token, "app": "user"})
    assert devices(me.id) == [], f"上一个人名下不该还留着这台设备:{devices(me.id)}"
    assert len(devices(friend.id)) == 1, devices(friend.id)
    print("  ✓ 换人登录:那一行改挂过去,上一个人再也收不到这台设备的推送")

    # ---- 下线之后回到没有可用通道 ----
    friend.post("/push/v1/devices/remove", {"channel": "apns", "token": token})
    assert devices(friend.id)[0][4] is False, devices(friend.id)
    before = len(logs(friend.id))
    me.send(pv["id"], "睡了吗")
    got = wait_log(friend.id, before + 1)
    assert len(got) > before, got
    assert "没有可用通道" in got[0][1], f"设备下线了就该回到没有通道:{got[0]}"
    print("  ✓ 退出登录下线设备之后,回到「没有可用通道」")

    # ---- 注销账号:名下设备全下线 ----
    third = person()
    tok3 = f"apnstok{random.getrandbits(48):012x}"
    third.post("/push/v1/devices", {"channel": "apns", "token": tok3})
    assert devices(third.id)[0][4] is True
    third.delete("/auth/me")
    rows = devices(third.id)
    assert rows and rows[0][4] is False, f"注销之后设备该下线:{rows}"
    print("  ✓ 注销账号:名下设备一起下线")

    print("自建推送设备 e2e 通过 ✓")


if __name__ == "__main__":
    main()
