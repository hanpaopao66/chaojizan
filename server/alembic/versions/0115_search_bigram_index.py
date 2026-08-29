"""搜索加二元组索引:中文子串检索走得动索引

## 为什么不是 pg_trgm

第一反应是 `pg_trgm` + GIN,但**实测下来它对中文基本没用**:

    查 '烧'      索引扫出 3705 行 / 全表 3705    ← 一行没滤掉
    查 '烧烤'     索引扫出 3705 行 / 全表 3705    ← 一行没滤掉
    查 '红烧肉'    索引扫出    0 行              ← 有效
    查 'abc'     索引扫出    0 行              ← 有效

三元组要**三个字符**才有选择性。而中文搜索绝大多数是两个字
(烧烤、火锅、奶茶、麻辣、米线)—— 那种情况它做一次全索引扫再逐行 recheck,
**比全表扫还慢**(5.8ms vs 1.7ms)。加上去是负收益。

## 用二元组,而且不装扩展

`pg_bigm` 是为 CJK 设计的,但它不在镜像里,装它要改数据库镜像。
二元组用纯 SQL 就能做:一个 IMMUTABLE 函数把名字切成所有相邻两字,
GIN 索引建在它上面。实测同样的查询:

    查 '烧烤'   索引扫出 1 行 / 全表 3705   （trgm 是 3705）
    查 '面馆'   索引扫出 1 行   0.032ms

## 为什么它是安全的预筛

「name 含子串 q」⇒「q 的每个二元组都出现在 name 里」,所以**不会漏**
(没有假阴性);反过来不成立,会有假阳性 —— 所以查询里仍然带着
`name ILIKE '%q%'` 做精确复核。索引负责把候选从几万缩到几个,
ILIKE 负责判对错。

单字查询(`sz_bigrams('烧')` = `{}`)时 `@> '{}'` 对所有行成立,
自然退化成全表扫 —— 结果仍然正确,只是没有索引收益。单字搜索本来
也搜不出什么,不值得为它加复杂度。

## 现在加是提前量

当前 3653 家店、7291 道菜,全表扫 2.5ms,规划器**根本不会选这个索引**
(它现在算得对)。加它是为了 10 万家店那天不用救火 ——
到时候规划器自己会开始用。
"""
from alembic import op

revision = '0115'
down_revision = '0114'
branch_labels = None
depends_on = None

# lower() 让它和 ILIKE 的大小写口径一致
FN = """
CREATE OR REPLACE FUNCTION sz_bigrams(t text) RETURNS text[] AS $$
  SELECT coalesce(array_agg(DISTINCT substr(s, i, 2)), '{}')
  FROM (SELECT lower(t) AS s) x,
       generate_series(1, greatest(length(lower(t)) - 1, 0)) AS i
$$ LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE;
"""


def upgrade() -> None:
    op.execute(FN)
    # 不用 CONCURRENTLY:迁移跑在独立的一次性容器里,此刻没有流量,
    # 而 CONCURRENTLY 不能在事务里跑(alembic 默认包事务)
    op.execute("CREATE INDEX IF NOT EXISTS ix_merchants_name_bigram "
               "ON merchants USING gin (sz_bigrams(name))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_dishes_name_bigram "
               "ON dishes USING gin (sz_bigrams(name))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_dishes_name_bigram")
    op.execute("DROP INDEX IF EXISTS ix_merchants_name_bigram")
    op.execute("DROP FUNCTION IF EXISTS sz_bigrams(text)")
