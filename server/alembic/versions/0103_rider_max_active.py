"""骑手接单偏好三件套:同时接单上限、新手半径只设一次、收工方向

`rider_max_active_orders` 一直是全平台一个常数(config.py,默认 3),
骑手改不了。3 单对新手会超时、对老手嫌少,而这个数**只影响他自己** ——
没道理由平台替他定死。

美团众包和蜂鸟众包都让骑手自调,两边的新手攻略都写「先设成 1 单」。

空 = 用平台默认。**只能往下调不能往上**:平台常数留作硬上限,
理由不是不信任骑手,是同时 8 单必然有人超时,而超时的赔付平台出、
差评他背。

Revision ID: 0103
Revises: 0102
"""
import sqlalchemy as sa
from alembic import op

revision = '0103'
down_revision = '0102'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable 且无默认值:存量骑手一律为空,行为和加字段前完全一致。
    # 不给默认 3 —— 那会让"我没设过"和"我设成 3"变得没法区分,
    # 而这两件事在界面上要说不同的话
    op.add_column('users',
                  sa.Column('rider_max_active', sa.Integer(), nullable=True))

    # grab_radius_touched:区分「没设过半径」和「设成了不限」。
    #
    # 两者的 grab_radius_km 都是 null,但含义相反 —— 前者是新手还没碰过
    # 这个设置,后者是他明确要看全城。新手首次上线自动设 3 公里只对前者做。
    #
    # ⚠️ **存量骑手一律置 true**(下面那条 UPDATE):他们已经跑了很久,
    # 不该在某天早上上线时被平台悄悄改成 3 公里 —— 那是替老手做决定,
    # 而且他会以为"今天怎么单少了"。
    op.add_column('users',
                  sa.Column('grab_radius_touched', sa.Boolean(),
                            nullable=False, server_default=sa.false()))
    op.execute("UPDATE users SET grab_radius_touched = true "
               "WHERE role = 'rider'")

    # 收工方向:开着的时候顺路参照点从「手上单的送达点」换成这里。
    #
    # ⚠️ **只存街道级**(服务端 round_coarse 截到小数点后 2 位,约 1km)。
    # 骑手的收工方向多半就是他家附近,存得越准越接近"我们知道他住哪"。
    # 而「往这个方向」这个用途只需要街道级 —— 判顺路比的是绕路增量的
    # 相对大小,差一公里不影响谁排前面。
    op.add_column('users', sa.Column('go_home_lat', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('go_home_lng', sa.Float(), nullable=True))
    op.add_column('users',
                  sa.Column('go_home_on', sa.Boolean(),
                            nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('users', 'go_home_on')
    op.drop_column('users', 'go_home_lng')
    op.drop_column('users', 'go_home_lat')
    op.drop_column('users', 'grab_radius_touched')
    op.drop_column('users', 'rider_max_active')
