"""商家坐标加空间索引:首页「附近的店」不再逐个算球面距离

## 为什么需要它

首页 `/merchants?lat&lng` 是用户端第一流量口,每次打开都要跑。它靠
`ST_DWithin` 圈出附近的店,而 merchants 表上**一个空间索引都没有** ——
执行计划里 ST_DWithin 是当 Filter 跑的:先按 biz_type + status 拉出
1680 家,再逐个把 (lng, lat) 造成 geography 算球面距离,扔掉 817 家。

这个开销随店铺数**线性涨**,而且恰恰是生意做起来之后才涨。

## 为什么是这个索引定义

- **表达式索引**:坐标存的是两个 double 列(lng / lat),不是 geometry
  列。所以索引必须建在和查询里**一模一样**的表达式上
  (`ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography`),差一个字
  规划器就用不上它。routers/merchants.py 的 _DIST_EXPR 和这里必须同步改。
- **不加 WHERE 做成部分索引**:`is_open` 是商家一天开关好几次的字段,
  拿它做部分索引意味着每次开关店都要动索引;而它能省下的那点体积
  (885/3080)不值这个代价。status 稳定但同理收益有限。
- **不是 CONCURRENTLY**:迁移在独立的一次性 migrate 容器里跑
  (见 deploy/docker-compose.prod.yml),此刻没有流量,普通 CREATE INDEX
  拿的写锁没有代价;而 CONCURRENTLY 不能在事务里跑,alembic 默认包事务。

住宿(biz_type='stay')那条列表用的是同一个表达式,顺带也受益。
"""
from alembic import op

revision = '0112'
down_revision = '0111'
branch_labels = None
depends_on = None

_EXPR = "(ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography)"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_merchants_geo "
        f"ON merchants USING GIST ({_EXPR})")
    # 规划器要有新鲜的统计才会选它
    op.execute("ANALYZE merchants")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_merchants_geo")
