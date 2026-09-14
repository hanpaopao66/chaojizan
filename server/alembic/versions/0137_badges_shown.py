"""勋章「选了显示」的名单:social_profiles.badges_shown

「实名认证」这枚勋章改成默认不显示,本人可以自己打开(2026-09-14 用户拍板)。
原来只有 badges_hidden(本人选了隐藏的),「没选过」和「选了显示」分不开 —— 缺省是隐藏的那一枚,
本人打开之后没地方记。加这一列存「选了显示的」,两列合起来:选过的按他选的,没选过的按每一枚的缺省
(services/badges.hidden_keys)。

**不回填**:badges_hidden 里的本来就是「选了隐藏」,照旧算数;在这之前没有「选了显示」这回事
(显示是缺省,点显示只是把它从隐藏名单里拿掉),所以所有人的 badges_shown 都从空开始 ——
没选过的人,实名认证这一枚一律变成不显示,要看得见得本人去打开。勋章还没上生产,
受影响的只有本地和测试库里的数据。

带服务端缺省值 '[]':加列只改表结构、不重写整张表;不写这一列的老 INSERT 照常能插。

Revision ID: 0137
Revises: 0135
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0137'
# 0136 可能被同时进行的另一批改动占了:合并时按实际顺序把这里改成它的号
down_revision = '0135'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('social_profiles',
                  sa.Column('badges_shown', JSONB, nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('social_profiles', 'badges_shown')
