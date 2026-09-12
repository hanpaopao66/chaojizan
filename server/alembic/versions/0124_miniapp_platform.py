"""小程序开放平台:开发者、版本、open_id、云存储、审核记录(#320,DEV-PROMPTS-39)

把 #277 那张「自家清单」表扩成开放平台:

- mini_apps 加归属(developer_id)、公开标识(appid)、托管方式、当前/体验版本、AppSecret 密文;
  状态从 on/off 改成生命周期 draft/online/offline/suspended/removed;
- 新表:developers、developer_invites、mini_app_versions(对象只写一次)、testers、
  capabilities、openids(按应用隔离、表映射)、grants、kv + kv_usage(云存储与配额)、
  user_prefs(最近使用/我的)、daily_users + usage_daily(日活聚合)、
  decisions(审核/处罚/申诉全记录)、reports、curation。

用户角色是 VARCHAR(24) 非原生枚举、没有 CHECK 约束,加 developer 不用改库。

**回填**:建一条「官方开发者」(没有账号,is_official),存量条目挂到它名下,
hosting=external(存量都是官网自己的页面),生成 appid。

Revision ID: 0124
Revises: 0123
"""
import secrets

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = '0124'
down_revision = '0123'
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _created():
    return sa.Column('created_at', sa.DateTime(timezone=True),
                     server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        'developers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True, unique=True),
        sa.Column('kind', sa.String(16), nullable=False, server_default='individual'),
        sa.Column('display_name', sa.String(40), nullable=False, server_default=''),
        sa.Column('status', sa.String(16), nullable=False, server_default='unverified'),
        sa.Column('real_name_enc', sa.Text(), nullable=False, server_default=''),
        sa.Column('id_no_enc', sa.Text(), nullable=False, server_default=''),
        sa.Column('id_no_tail', sa.String(4), nullable=False, server_default=''),
        sa.Column('company_name', sa.String(100), nullable=False, server_default=''),
        sa.Column('uscc', sa.String(18), nullable=False, server_default=''),
        sa.Column('license_key', sa.String(200), nullable=False, server_default=''),
        sa.Column('contact_name', sa.String(40), nullable=False, server_default=''),
        sa.Column('contact_email', sa.String(120), nullable=False, server_default=''),
        sa.Column('agreement_version', sa.Integer(), nullable=False, server_default='0'),
        _ts('agreement_accepted_at'), _ts('submitted_at'), _ts('verified_at'),
        sa.Column('reviewed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reject_reason', sa.String(300), nullable=False, server_default=''),
        sa.Column('is_official', sa.Boolean(), nullable=False, server_default='false'),
        _created(),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_developers_status', 'developers', ['status'])

    op.create_table(
        'developer_invites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('phone_pseudonym', sa.String(64), nullable=False, unique=True),
        sa.Column('phone_tail', sa.String(4), nullable=False, server_default=''),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        _created(), _ts('used_at'),
    )

    # ---- mini_apps 扩展 ----
    op.add_column('mini_apps', sa.Column('appid', sa.String(18), nullable=True))
    op.add_column('mini_apps', sa.Column(
        'developer_id', sa.Integer(), sa.ForeignKey('developers.id'), nullable=True))
    op.add_column('mini_apps', sa.Column('kind', sa.String(8), nullable=False, server_default='app'))
    op.add_column('mini_apps', sa.Column('category', sa.String(16), nullable=False, server_default='tools'))
    op.add_column('mini_apps', sa.Column('description', sa.Text(), nullable=False, server_default=''))
    op.add_column('mini_apps', sa.Column('screenshots', JSONB(), nullable=False, server_default='[]'))
    op.add_column('mini_apps', sa.Column('privacy_policy', sa.Text(), nullable=False, server_default=''))
    op.add_column('mini_apps', sa.Column('data_declaration', JSONB(), nullable=False, server_default='[]'))
    op.add_column('mini_apps', sa.Column('hosting', sa.String(10), nullable=False, server_default='hosted'))
    op.add_column('mini_apps', sa.Column('request_domains', JSONB(), nullable=False, server_default='[]'))
    op.add_column('mini_apps', sa.Column('domain_changes_month', sa.String(7), nullable=False, server_default=''))
    op.add_column('mini_apps', sa.Column('domain_changes_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('mini_apps', sa.Column('current_version_id', sa.Integer(), nullable=True))
    op.add_column('mini_apps', sa.Column('trial_version_id', sa.Integer(), nullable=True))
    op.add_column('mini_apps', sa.Column('auto_release', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('mini_apps', sa.Column('secret_enc', sa.Text(), nullable=False, server_default=''))
    op.add_column('mini_apps', sa.Column('secret_pending_enc', sa.Text(), nullable=False, server_default=''))
    op.add_column('mini_apps', _ts('secret_rotated_at'))
    op.add_column('mini_apps', _ts('first_released_at'))
    op.add_column('mini_apps', sa.Column('is_official', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('mini_apps', sa.Column('listing_draft', JSONB(), nullable=True))
    op.add_column('mini_apps', _ts('removed_at'))
    op.alter_column('mini_apps', 'status', server_default='draft')

    # ---- 回填存量条目 ----
    conn = op.get_bind()
    official_id = conn.execute(sa.text(
        "INSERT INTO developers (kind, display_name, status, company_name, is_official, verified_at) "
        "VALUES ('company', '超级赞官方', 'verified', '陕西爱卡斯科技有限公司', true, now()) "
        "RETURNING id")).scalar()
    rows = conn.execute(sa.text("SELECT id, status FROM mini_apps")).fetchall()
    for row_id, status in rows:
        conn.execute(sa.text(
            "UPDATE mini_apps SET appid = :appid, developer_id = :dev, hosting = 'external', "
            "is_official = true, status = :st, "
            "first_released_at = COALESCE(first_released_at, created_at) WHERE id = :id"),
            {"appid": "sz" + secrets.token_hex(8), "dev": official_id,
             "st": "online" if status == "on" else "offline", "id": row_id})
    op.alter_column('mini_apps', 'appid', nullable=False)
    op.create_unique_constraint('uq_mini_apps_appid', 'mini_apps', ['appid'])
    op.create_index('ix_mini_apps_developer', 'mini_apps', ['developer_id'])

    op.create_table(
        'mini_app_versions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), nullable=False),
        sa.Column('version', sa.String(32), nullable=False, server_default=''),
        sa.Column('build', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('package_key', sa.String(200), nullable=False, server_default=''),
        sa.Column('sha256', sa.String(64), nullable=False, server_default=''),
        sa.Column('size', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('file_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('manifest', JSONB(), nullable=False, server_default='{}'),
        sa.Column('entry_url', sa.String(500), nullable=False, server_default=''),
        sa.Column('changelog', sa.String(1000), nullable=False, server_default=''),
        sa.Column('review_note', sa.String(1000), nullable=False, server_default=''),
        sa.Column('status', sa.String(16), nullable=False, server_default='uploaded'),
        sa.Column('quarantined', sa.Boolean(), nullable=False, server_default='false'),
        _ts('submitted_at'), _ts('reviewed_at'),
        sa.Column('reviewed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reject_code', sa.String(8), nullable=False, server_default=''),
        sa.Column('reject_note', sa.String(500), nullable=False, server_default=''),
        _ts('released_at'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        _created(),
        sa.UniqueConstraint('app_id', 'build', name='uq_miniapp_version_build'),
    )
    op.create_index('ix_miniapp_versions_app', 'mini_app_versions', ['app_id'])
    op.create_index('ix_miniapp_versions_status', 'mini_app_versions', ['status'])

    op.create_table(
        'mini_app_testers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), nullable=False, index=True),
        sa.Column('phone_pseudonym', sa.String(64), nullable=False),
        sa.Column('phone_tail', sa.String(4), nullable=False, server_default=''),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('app_id', 'phone_pseudonym', name='uq_miniapp_tester'),
    )
    op.create_table(
        'mini_app_capabilities',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), nullable=False, index=True),
        sa.Column('capability', sa.String(24), nullable=False),
        sa.Column('status', sa.String(12), nullable=False, server_default='requested', index=True),
        sa.Column('justification', sa.String(300), nullable=False, server_default=''),
        sa.Column('decided_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        _ts('decided_at'),
        sa.Column('note', sa.String(300), nullable=False, server_default=''),
        _created(),
        sa.UniqueConstraint('app_id', 'capability', name='uq_miniapp_capability'),
    )
    op.create_table(
        'mini_app_openids',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), primary_key=True),
        sa.Column('open_id', sa.String(32), nullable=False, unique=True),
        _created(),
    )
    op.create_table(
        'mini_app_grants',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), nullable=False, index=True),
        sa.Column('scope', sa.String(24), nullable=False),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        _ts('revoked_at'),
        sa.UniqueConstraint('user_id', 'app_id', 'scope', name='uq_miniapp_grant'),
    )
    op.create_table(
        'mini_app_kv',
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('key', sa.String(128), primary_key=True),
        sa.Column('value', sa.Text(), nullable=False, server_default=''),
        sa.Column('bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rev', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'mini_app_kv_usage',
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('keys', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('bytes', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_table(
        'mini_app_user_prefs',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), primary_key=True),
        sa.Column('starred', sa.Boolean(), nullable=False, server_default='false'),
        _ts('last_opened_at'),
        sa.Column('open_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_table(
        'mini_app_daily_users',
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), primary_key=True),
        sa.Column('day', sa.Date(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
    )
    op.create_table(
        'mini_app_usage_daily',
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), primary_key=True),
        sa.Column('day', sa.Date(), primary_key=True),
        sa.Column('opens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('users', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_table(
        'mini_app_decisions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('target_type', sa.String(16), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('app_id', sa.Integer(), nullable=True, index=True),
        sa.Column('developer_id', sa.Integer(), nullable=True, index=True),
        sa.Column('action', sa.String(24), nullable=False),
        sa.Column('reason_code', sa.String(8), nullable=False, server_default=''),
        sa.Column('note_public', sa.String(500), nullable=False, server_default=''),
        sa.Column('note_internal', sa.String(500), nullable=False, server_default=''),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('appeal_of', sa.Integer(), nullable=True, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False, index=True),
    )
    op.create_table(
        'mini_app_reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), nullable=False, index=True),
        sa.Column('reporter_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reason_code', sa.String(8), nullable=False),
        sa.Column('detail', sa.String(500), nullable=False, server_default=''),
        sa.Column('evidence_keys', JSONB(), nullable=False, server_default='[]'),
        sa.Column('status', sa.String(12), nullable=False, server_default='open', index=True),
        sa.Column('handled_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        _ts('handled_at'),
        sa.Column('resolution', sa.String(300), nullable=False, server_default=''),
        _created(),
    )
    op.create_table(
        'mini_app_curation',
        sa.Column('app_id', sa.Integer(), sa.ForeignKey('mini_apps.id'), primary_key=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reason', sa.String(200), nullable=False, server_default=''),
        sa.Column('added_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    for t in ('mini_app_curation', 'mini_app_reports', 'mini_app_decisions',
              'mini_app_usage_daily', 'mini_app_daily_users', 'mini_app_user_prefs',
              'mini_app_kv_usage', 'mini_app_kv', 'mini_app_grants', 'mini_app_openids',
              'mini_app_capabilities', 'mini_app_testers', 'mini_app_versions'):
        op.drop_table(t)
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE mini_apps SET status = CASE WHEN status = 'online' THEN 'on' ELSE 'off' END"))
    # 回退时只保留 0104 认得的列;平台期新建的托管条目在老结构里没有意义,删掉
    conn.execute(sa.text("DELETE FROM mini_apps WHERE hosting <> 'external'"))
    op.drop_index('ix_mini_apps_developer', table_name='mini_apps')
    op.drop_constraint('uq_mini_apps_appid', 'mini_apps', type_='unique')
    for col in ('removed_at', 'listing_draft', 'is_official', 'first_released_at', 'secret_rotated_at', 'secret_pending_enc',
                'secret_enc', 'auto_release', 'trial_version_id', 'current_version_id',
                'domain_changes_count', 'domain_changes_month', 'request_domains', 'hosting',
                'data_declaration', 'privacy_policy', 'screenshots', 'description',
                'category', 'kind', 'developer_id', 'appid'):
        op.drop_column('mini_apps', col)
    op.alter_column('mini_apps', 'status', server_default='on')
    op.drop_table('developer_invites')
    op.drop_table('developers')
