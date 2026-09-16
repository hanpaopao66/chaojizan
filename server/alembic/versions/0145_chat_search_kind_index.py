"""搜索分类:chat_messages 按 (会话, 类型, id) 建索引

全局搜索加了「多媒体 / 链接 / 文件 / 音乐 / 语音」几个分类(对齐 Telegram 的搜索页),
判据是 `kind`,而且是**跨会话**找 —— 在此之前 chat_messages 上只有
`(chat_id, seq)` 这个唯一索引,按类型翻要把我每个会话的消息都扫一遍再过滤。

一个人在几十个会话里、每个会话几千条的时候还不明显;群上限刚提到 20 万(D7),
一个活跃大群自己就有几十万条 —— 那时候点一下「文件」就是几十万行的顺序扫。

`id` 放在末位是因为跨会话翻页用的是消息自增 id(seq 是会话内的号,跨会话排不出先后)。

不回填任何数据。

Revision ID: 0145
Revises: 0144
"""
from alembic import op

revision = '0145'
down_revision = '0144'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_chat_messages_kind', 'chat_messages',
                    ['chat_id', 'kind', 'id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_chat_messages_kind', table_name='chat_messages')
