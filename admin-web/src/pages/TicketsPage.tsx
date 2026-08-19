import { Alert, Button, Input, Modal, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, Ticket, closeTicket, listTickets, replyTicket } from '../api'

/** 客服工单。回复会推给提单人,关闭之后就不再接受追问。 */
export default function TicketsPage() {
  const [rows, setRows] = useState<Ticket[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [cur, setCur] = useState<Ticket | null>(null)
  const [reply, setReply] = useState('')
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try { setRows(await listTickets()) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, ok: string) {
    setActing(true)
    try { await fn(); message.success(ok); setCur(null); setReply(''); await load() }
    catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
    finally { setActing(false) }
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Table<Ticket>
        rowKey="id" loading={loading} dataSource={rows} size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 160,
            render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
          { title: '来自', dataIndex: 'role', width: 90,
            render: (v: string) => <Tag>{
              { customer: '用户', merchant: '商家', rider: '骑手' }[v] ?? v}</Tag> },
          { title: '联系方式', width: 140,
            render: (_, t) => t.contact || t.user_phone || '—' },
          { title: '内容', dataIndex: 'content', ellipsis: true },
          // status 实测只有 open / closed 两种,没有 replied ——
          // 「回过但没关」表现为 status=open 且 reply 非空
          { title: '状态', dataIndex: 'status', width: 100,
            render: (_: string, t) => t.status === 'closed'
              ? <Tag>已关闭</Tag>
              : t.reply
                ? <Tag color="processing">已回待关</Tag>
                : <Tag color="warning">待处理</Tag> },
          { title: '操作', width: 100, fixed: 'right',
            render: (_, t) => (
              <Button type="link" onClick={() => { setCur(t); setReply(t.reply || '') }}>
                {t.status === 'closed' ? '看详情' : '处理'}
              </Button>
            ) },
        ]}
      />
      <Modal
        open={!!cur} title={`工单 #${cur?.id ?? ''}`} width={620}
        onCancel={() => setCur(null)}
        footer={cur?.status !== 'closed' ? [
          <Button key="close" loading={acting}
                  onClick={() => cur && act(() => closeTicket(cur.id), '已关闭')}>
            关闭工单
          </Button>,
          <Button key="reply" type="primary" loading={acting}
                  onClick={() => {
                    if (reply.trim().length < 1) {
                      message.warning('回复不能为空'); return
                    }
                    void act(() => replyTicket(cur!.id, reply.trim()), '已回复')
                  }}>
            回复
          </Button>,
        ] : null}
      >
        {cur && (
          <>
            <div style={{
              background: 'var(--sz-surface-alt)', padding: 12, borderRadius: 8,
              whiteSpace: 'pre-wrap', marginBottom: 12,
            }}>{cur.content}</div>
            {cur.reply && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)' }}>已有回复</div>
                <div style={{ whiteSpace: 'pre-wrap' }}>{cur.reply}</div>
              </div>
            )}
            {cur.status !== 'closed' && (
              <Input.TextArea rows={4} value={reply} maxLength={500} showCount
                              onChange={(e) => setReply(e.target.value)}
                              placeholder="回复内容(会推送给提单人)" />
            )}
          </>
        )}
      </Modal>
    </>
  )
}
