"""微信特约商户进件资料 + 外卖订单落微信交易号

服务商资质到位,但类目(普通服务商 / 电商平台)未定,两套进件 API 不通用。
这次只加**两套都要**的东西:

1. Merchant 上的进件资料。要商家交的材料两套 API 是一样的
   (营业执照照片、法人身份证、结算账户、超管联系人),先把数据模型和
   采集流程做起来 —— 这是整条链路里最耗时的一环,没有商家配合
   一家特约商户都开不出来。

2. Order.wx_transaction_id。分账接口的必传入参,而外卖订单一直没存,
   支付回调拿到就丢了。**存量已支付订单补不回来**,加字段之前的订单
   永远分不了账。

敏感字段(身份证号、银行账号)密文落库,列宽按 Fernet 密文留 300。
applyment_status 带索引:平台侧要按状态筛出「谁填齐了、谁被驳回了」当工作队列。

Revision ID: 0102
Revises: 0101
"""
import sqlalchemy as sa
from alembic import op

revision = '0102'
down_revision = '0101'
branch_labels = None
depends_on = None

# (列名, 类型, 默认值)
_MERCHANT_COLS = [
    ("subject_type", sa.String(12), ""),
    ("business_license_image_url", sa.String(300), ""),
    ("legal_person_name", sa.String(50), ""),
    ("legal_person_id_encrypted", sa.String(300), ""),
    ("legal_person_id_tail", sa.String(4), ""),
    ("legal_person_id_front_url", sa.String(300), ""),
    ("legal_person_id_back_url", sa.String(300), ""),
    ("admin_contact_name", sa.String(50), ""),
    ("admin_contact_phone", sa.String(20), ""),
    ("admin_contact_email", sa.String(100), ""),
    ("settle_account_type", sa.String(12), ""),
    ("settle_account_name", sa.String(80), ""),
    ("settle_bank_name", sa.String(80), ""),
    ("settle_bank_branch", sa.String(120), ""),
    ("settle_account_no_encrypted", sa.String(300), ""),
    ("settle_account_tail", sa.String(4), ""),
    ("applyment_no", sa.String(64), ""),
    ("applyment_reject_reason", sa.String(500), ""),
]


def upgrade() -> None:
    for name, type_, default in _MERCHANT_COLS:
        op.add_column("merchants", sa.Column(
            name, type_, nullable=False, server_default=default))
    op.add_column("merchants", sa.Column(
        "applyment_status", sa.String(24), nullable=False,
        server_default="not_submitted"))
    op.create_index("ix_merchants_applyment_status", "merchants",
                    ["applyment_status"])
    op.add_column("merchants", sa.Column(
        "applyment_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column(
        "wx_transaction_id", sa.String(64), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("orders", "wx_transaction_id")
    op.drop_index("ix_merchants_applyment_status", table_name="merchants")
    op.drop_column("merchants", "applyment_updated_at")
    op.drop_column("merchants", "applyment_status")
    for name, _type, _default in reversed(_MERCHANT_COLS):
        op.drop_column("merchants", name)
