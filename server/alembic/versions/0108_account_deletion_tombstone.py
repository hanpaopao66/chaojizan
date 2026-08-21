"""账号注销:真正的墓碑列 + 风控标记跟随表

## 在此之前"已注销"是怎么表达的

没有列。`DELETE /auth/me` 把 `users.phone` 改成 `del{id}_{6位hex}`,
靠**手机号长什么样**来表达"这个号注销了"。全库认得这个约定的只有
`security.py` 一处(`user.phone.startswith("del")`,用来让旧 token 失效)。

于是所有别的地方都把墓碑行当活人:

- `is_online` 不重置 —— 全库 8 处 `User.is_online.is_(True)` 把它算进在线骑手,
  包括 `services/push.py` 的派单广播;
- `ref_code` 不清空 —— 邀请码仍能被 `referrals.py` 解析,继续给已注销账号发券;
- `merchant_staff` 行不删 —— 人永远挂在店员名单上,而 `merchants.py` 的
  `phone[:3] + "****" + phone[-4:]` 把 13 个字符的哨兵渲染成 `del****9af0`;
- `orders.py` / `admin.py` 把 `del4213_9af0c1` 当电话号原样下发给对端做一键拨号。

这些都不是"决定这么做",是"没人想到还有这种行"。哨兵藏在业务列里,
读那些代码的人没有任何线索会想到 phone 可能不是个手机号。

所以加一列 `deleted_at`:判据只有一个,而且是个**没有别的含义**的列。

## 存量行的 deleted_at 填什么

真实的注销时刻已经不可考(注销只留了一行 logger.info,`app_events`
在注销时就被硬删了)。这里回填**迁移执行的时刻**,并明说:
这一列对迁移之后注销的行是准确时刻,对存量行只表示"已注销"。
不用 `created_at` —— 那是注册时刻,填进去是个看起来很像真的假数据,
以后按 deleted_at 做留存期统计的人会被它骗。

`security.py` 的手机号前缀判断在这次迁移之后仍然留着兜底:
万一有哪一行的 phone 是 `del` 开头而这里没盖到(比如迁移和
数据修复脚本之间又有人注销),少认一行墓碑的后果是旧 token 还能用。

## risk_carryovers

见 models.py 里那段:注销释放手机号,而风控标记留在旧行上,
等于给"恶意售后"黑名单做了个一键洗白按钮。这张表按
HMAC(手机号+角色) 的假名把标记留下,再注册时贴回去。
只装真的被处置过的账号 —— 干净账号注销后一条痕迹不留。

Revision ID: 0108
Revises: 0107
"""
import sqlalchemy as sa
from alembic import op

revision = '0108'
down_revision = '0107'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "deleted_at", sa.DateTime(timezone=True), nullable=True))
    # 存量墓碑行:唯一的判据就是那个手机号前缀。
    # 真手机号是纯数字,不可能以 'del' 开头,不会误伤活账号。
    op.execute("UPDATE users SET deleted_at = now() "
               "WHERE deleted_at IS NULL AND phone LIKE 'del%'")

    op.create_table(
        "risk_carryovers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone_key", sa.String(32), nullable=False),
        sa.Column("after_sale_banned", sa.Boolean(),
                  nullable=False, server_default=sa.text("false")),
        sa.Column("risk_level", sa.String(10),
                  nullable=False, server_default=""),
        sa.Column("risk_note", sa.String(200),
                  nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    # 唯一:同一个号注销两次(注销→再注册→再注销)覆盖同一行,不堆重复
    op.create_index("uq_risk_carryovers_phone_key", "risk_carryovers",
                    ["phone_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_risk_carryovers_phone_key",
                  table_name="risk_carryovers")
    op.drop_table("risk_carryovers")
    # **deleted_at 删掉之后,"已注销"重新只剩手机号前缀这一个判据。**
    # security.py 的前缀分支正是为这种情况留着的 —— 回滚之后旧 token
    # 照样失效,不会因为少了一列就把注销的账号放进来。
    op.drop_column("users", "deleted_at")
