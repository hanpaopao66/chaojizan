"""测试用的坐标工具。**这个模块必须保持零副作用**。

为什么单独拆出来:`tests/util.py` 在 import 时就会登录演示账号、清骑手积压
(模块级调了 `_clear_demo_rider_backlog()` 等),也就是说 **import 它就需要
一个起着的服务端**。单元测试 `make unit` 是不起服务的,于是
`from tests.util import unique_spot` 这一行让一条纯函数测试连上了网 ——
本地开发机的服务恰好在跑所以一直是绿的,CI 上才炸出来。

所以规矩很简单:**这里只放不碰网络、不碰库、不碰 Redis 的纯函数**,
`tests/util.py` 再从这里 re-export 给 e2e 用。
"""
from __future__ import annotations

import random


def unique_spot(seed: str = "") -> tuple[float, float]:
    """给一次测试跑动挑一个「独占」的下单坐标(lat, lng)。

    为什么需要:#44 风控的 addr_freq 规则用 ~65m 的包围盒统计——同一格子里
    24 小时内 ≥N 单且 ≥2 个账号就标记,而被标记的单**不触发邀请奖励**
    (services/risk.py + referrals.py,设计如此)。
    原先各用例自己写 `30.6650 + (ts % 20) * 1.3e-3`,只有 20 个点且每 20 秒
    循环一次——一天里反复跑必然撞格子,表现为"发券功能时好时坏",
    很容易被误判成代码坏了。

    这里在商家周边 ~2.4km 内切 30×30 的网格(格间距 ~88m > 65m 包围盒),
    选一格,撞车概率低且仍在 4km 配送半径内。

    ⚠️ `seed` **不保证跨进程稳定**:CPython 默认开 PYTHONHASHSEED 随机化,
    `hash("risk")` 每次跑都不一样,所以带不带 seed 实际都是随机选格。
    别指望"同一个 seed 永远落同一格" —— 而且真那样反而更糟:
    一天里重复跑同一条用例就必然堆在同一格,直接把风控框撑爆。
    seed 的作用只是**同一进程内**同名调用取到同一格。
    """
    base_lat, base_lng, step = 30.6650, 104.0823, 0.0008
    n = random.randrange(900) if not seed else (hash(seed) % 900)
    return base_lat + (n // 30) * step, base_lng + (n % 30) * step
