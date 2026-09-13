"""社区治理:处罚表、聊天举报的对象与可见下限、S8 留痕不随举报单级联、审核时长的提交时间
(#368 聊天部分、#370、#371,DEV-PROMPTS-40 §3 S6 / S8)

- social_sanctions:对人和会话的处罚(删消息、禁言、封群 / 频道、封号、警告),申诉记在同一行;
- chat_reports 加 subject_type / subject_id(被举报的是谁,「7 天 3 人」按它数)和 context_floor
  (举报人当时的可见下限,S8 的上下文不越过它);已有的举报按 target_type 回填对象;
- admin_chat_views.report_id 从 ON DELETE CASCADE 改成 SET NULL:留痕和透明中心公示的
  查看次数不能因为举报单被删而变少;
- video_decisions 加 submitted_at:审核时长中位数要「这次结论对应的那次提交」,稿件行上的
  submitted_at 会被下一次提交覆盖。已有的结论留空,不参与计算(不编造)。

Revision ID: 0130
Revises: 0128(和 0129 并行开发,合并时接到 0129 后面)
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0130'
down_revision = '0128'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'social_sanctions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('target_type', sa.String(8), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(16), nullable=False),
        sa.Column('reason_code', sa.String(8), nullable=False),
        sa.Column('note', sa.String(500), nullable=False, server_default=''),
        sa.Column('note_internal', sa.String(500), nullable=False, server_default=''),
        sa.Column('until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('chat_id', sa.Integer(), nullable=True),
        sa.Column('seqs', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('admin_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('report_kind', sa.String(8), nullable=False, server_default=''),
        sa.Column('report_id', sa.Integer(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by', sa.Integer(), nullable=True),
        sa.Column('revoke_note', sa.String(300), nullable=False, server_default=''),
        sa.Column('appeal_status', sa.String(12), nullable=False, server_default=''),
        sa.Column('appeal_text', sa.String(500), nullable=False, server_default=''),
        sa.Column('appealed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('appeal_admin_id', sa.Integer(), nullable=True),
        sa.Column('appeal_note', sa.String(500), nullable=False, server_default=''),
        sa.Column('appeal_note_internal', sa.String(500), nullable=False, server_default=''),
        sa.Column('appeal_resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('carry_key', sa.String(32), nullable=True),
        sa.Column('carried_from', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index('ix_social_sanctions_target', 'social_sanctions',
                    ['target_type', 'target_id', 'created_at'])
    op.create_index('ix_social_sanctions_live', 'social_sanctions',
                    ['target_type', 'target_id', 'action'],
                    postgresql_where=sa.text(
                        "revoked_at IS NULL AND action IN ('mute', 'ban_chat', 'ban_account')"))
    op.create_index('ix_social_sanctions_appeal_open', 'social_sanctions', ['id'],
                    postgresql_where=sa.text("appeal_status = 'open'"))
    op.create_index('ix_social_sanctions_carry_key', 'social_sanctions', ['carry_key'])
    op.create_index('ix_social_sanctions_created_at', 'social_sanctions', ['created_at'])

    # ---- 聊天举报:对象 + 可见下限 ----
    op.add_column('chat_reports', sa.Column('subject_type', sa.String(8), nullable=False,
                                            server_default=''))
    op.add_column('chat_reports', sa.Column('subject_id', sa.Integer(), nullable=True))
    op.add_column('chat_reports', sa.Column('context_floor', sa.BigInteger(), nullable=False,
                                            server_default='0'))
    op.execute("UPDATE chat_reports SET subject_type = 'user', subject_id = user_id "
               "WHERE target_type = 'user' AND user_id IS NOT NULL")
    op.execute("UPDATE chat_reports SET subject_type = 'chat', subject_id = chat_id "
               "WHERE target_type = 'chat' AND chat_id IS NOT NULL")
    # 举报消息:对象是第一条被举报的消息的发送人;频道帖子 / 匿名发言算会话本身
    op.execute("""
        UPDATE chat_reports r
           SET subject_type = CASE WHEN m.as_chat OR m.sender_id IS NULL THEN 'chat' ELSE 'user' END,
               subject_id = CASE WHEN m.as_chat OR m.sender_id IS NULL THEN r.chat_id
                                 ELSE m.sender_id END
          FROM chat_messages m
         WHERE r.target_type = 'message' AND jsonb_array_length(r.seqs) > 0
           AND m.chat_id = r.chat_id AND m.seq = (r.seqs->>0)::bigint
    """)
    op.create_index('ix_chat_reports_subject', 'chat_reports',
                    ['subject_type', 'subject_id', 'created_at'])
    op.create_index('ix_chat_reports_status', 'chat_reports', ['status', 'id'])

    # ---- S8 留痕不随举报单级联 ----
    op.drop_constraint('admin_chat_views_report_id_fkey', 'admin_chat_views',
                       type_='foreignkey')
    op.alter_column('admin_chat_views', 'report_id', existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key('admin_chat_views_report_id_fkey', 'admin_chat_views', 'chat_reports',
                          ['report_id'], ['id'], ondelete='SET NULL')

    # ---- 审核时长:结论对应的那次提交 ----
    op.add_column('video_decisions', sa.Column('submitted_at', sa.DateTime(timezone=True),
                                               nullable=True))


def downgrade() -> None:
    op.drop_column('video_decisions', 'submitted_at')
    op.drop_constraint('admin_chat_views_report_id_fkey', 'admin_chat_views',
                       type_='foreignkey')
    op.execute("DELETE FROM admin_chat_views WHERE report_id IS NULL")
    op.alter_column('admin_chat_views', 'report_id', existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key('admin_chat_views_report_id_fkey', 'admin_chat_views', 'chat_reports',
                          ['report_id'], ['id'], ondelete='CASCADE')
    op.drop_index('ix_chat_reports_status', table_name='chat_reports')
    op.drop_index('ix_chat_reports_subject', table_name='chat_reports')
    op.drop_column('chat_reports', 'context_floor')
    op.drop_column('chat_reports', 'subject_id')
    op.drop_column('chat_reports', 'subject_type')
    op.drop_table('social_sanctions')
