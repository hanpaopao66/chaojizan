"""骑手实名:证号加密落库 + 培训记录带内容版本(#165-#167)

两件事:

1. **证号从明文改加密。** 骑手侧此前明文存 18 位并直接出接口,
   而用户侧(UserIdentity)早就是 Fernet 加密的 —— 同一个项目两套标准,
   这里对齐到严的那个。存量数据在本迁移里就地加密,不留明文。

2. **培训记录加 content_version。** 123 号令第二十九条要的是"培训记录",
   光有分数证明不了培训了什么。

⚠️ 加密用的是 app.services.crypto 的 Fernet 密钥。密钥丢了就解不回来 ——
但这里只解出生日期用于年龄核验,而生日在迁移时已单独落到 birth_date,
所以即便解不回证号也不影响业务(合规追溯时可走人工)。

Revision ID: 0068
Revises: 0067
"""
import sqlalchemy as sa
from alembic import op

revision = '0068'
down_revision = '0067'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rider_profiles", sa.Column(
        "id_no_encrypted", sa.String(500), nullable=False,
        server_default=sa.text("''")))
    op.add_column("rider_profiles", sa.Column(
        "birth_date", sa.Date(), nullable=True))
    op.add_column("rider_profiles", sa.Column(
        "id_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("rider_exams", sa.Column(
        "content_version", sa.String(20), nullable=False,
        server_default=sa.text("''")))

    # ---- 存量明文证号:就地加密 + 解出生日,然后清掉明文列 ----
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, id_card_no FROM rider_profiles "
        "WHERE id_card_no <> ''")).fetchall()
    if rows:
        from datetime import datetime

        from app.services.crypto import encrypt

        for pid, id_no in rows:
            id_no = (id_no or "").strip().upper()
            birth = None
            if len(id_no) == 18:
                try:
                    birth = datetime.strptime(id_no[6:14], "%Y%m%d").date()
                except ValueError:
                    birth = None
            conn.execute(sa.text(
                "UPDATE rider_profiles SET id_no_encrypted = :e, "
                "birth_date = :b WHERE id = :i"),
                {"e": encrypt(id_no), "b": birth, "i": pid})

    # 明文列直接删掉 —— 留着就是留了一份泄露面
    op.drop_column("rider_profiles", "id_card_no")


def downgrade() -> None:
    # 回滚只恢复列结构,**不恢复明文** —— 解密回写等于把风险又放回去
    op.add_column("rider_profiles", sa.Column(
        "id_card_no", sa.String(18), nullable=False,
        server_default=sa.text("''")))
    op.drop_column("rider_exams", "content_version")
    op.drop_column("rider_profiles", "id_verified_at")
    op.drop_column("rider_profiles", "birth_date")
    op.drop_column("rider_profiles", "id_no_encrypted")
