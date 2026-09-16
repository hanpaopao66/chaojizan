import { Button, Card, Input, Modal, Radio, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ForumReportItem, forumReports, handleForumReport } from '../../api_forum'
import { Muted, PostCell, REPORT_STATUS, ReasonPicker, fail, reasonProblem, t } from './shared'

/**
 * 论坛举报(DEV-PROMPTS-41 #380)。
 *
 * 举报人是谁这里一律不给 —— 举报人对被举报的一方永远匿名。
 * 处置只有两种:下架(要带 §5.11 的原因代码,X999 要写说明)和不成立。
 * 下架之后作者收到系统通知、知道是哪条原因,**能申诉一次,而且由另一个人复核**。
 * 同一条帖子上没处理的举报会一起结案。
 */
export default function ForumReportsPage() {
  const [status, setStatus] = useState<'open' | 'handled' | 'all'>('open')
  const [rows, setRows] = useState<ForumReportItem[]>([])
  const [loading, setLoading] = useState(false)
  const [acting, setActing] = useState<ForumReportItem | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { setRows((await forumReports(status)).items) } catch (e) { fail(e) } finally { setLoading(false) }
  }, [status])
  useEffect(() => { void load() }, [load])

  return (
    <Card title="论坛举报">
      <Space style={{ marginBottom: 12 }} wrap>
        <Radio.Group value={status} onChange={(e) => setStatus(e.target.value)} optionType="button"
          options={[{ value: 'open', label: '待处理' }, { value: 'handled', label: '已处理' },
                    { value: 'all', label: '全部' }]} />
        <Muted>举报人是谁不显示;下架要带原因代码,作者会收到通知并可以申诉一次(换人复核)</Muted>
      </Space>
      <Table<ForumReportItem> rowKey="id" size="small" loading={loading} dataSource={rows}
        locale={{ emptyText: '没有举报' }} pagination={{ pageSize: 20 }} scroll={{ x: 1100 }}
        columns={[
          { title: '#', dataIndex: 'id', width: 64 },
          { title: '状态', width: 100, render: (_, r) => (
            <Tag color={REPORT_STATUS[r.status]?.color}>{REPORT_STATUS[r.status]?.label ?? r.status}</Tag>) },
          { title: '被举报的帖子', width: 440, render: (_, r) => <PostCell p={r.post} /> },
          { title: '原因', width: 180, render: (_, r) => (
            <Space direction="vertical" size={0}>
              <span>{r.reason_code} {r.reason_label}</span>
              {r.note && <Muted>{r.note}</Muted>}
            </Space>) },
          { title: '提交', width: 100, render: (_, r) => t(r.created_at) },
          { title: '结果', width: 200, render: (_, r) => r.resolution || '—' },
          { title: '', width: 90, fixed: 'right', render: (_, r) => (r.status === 'open'
            ? <Button size="small" type="primary" onClick={() => setActing(r)}>处理</Button>
            : <Muted>{t(r.handled_at)}</Muted>) },
        ]} />
      {acting && <HandleModal report={acting} onClose={(changed) => {
        setActing(null)
        if (changed) void load()
      }} />}
    </Card>
  )
}

function HandleModal({ report, onClose }: { report: ForumReportItem; onClose: (changed: boolean) => void }) {
  const [action, setAction] = useState<'remove' | 'dismiss'>('remove')
  const [code, setCode] = useState('')
  const [note, setNote] = useState('')
  const [internal, setInternal] = useState('')
  const [busy, setBusy] = useState(false)
  const problem = action === 'remove' ? reasonProblem(code, note) : null

  const submit = async () => {
    setBusy(true)
    try {
      const out = await handleForumReport(report.id, {
        action,
        reason_code: action === 'remove' ? code : undefined,
        note: action === 'remove' ? note : undefined,
        note_internal: internal || undefined,
      })
      message.success(out.resolution)
      onClose(true)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  return (
    <Modal open title={`处理举报 #${report.id}`} onCancel={() => onClose(false)} okText="确认"
           onOk={submit} confirmLoading={busy} okButtonProps={{ disabled: !!problem }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <PostCell p={report.post} />
        <Radio.Group value={action} optionType="button" buttonStyle="solid"
                     onChange={(e) => setAction(e.target.value)}
                     options={[{ value: 'remove', label: '下架这条帖子' },
                               { value: 'dismiss', label: '举报不成立' }]} />
        {action === 'remove' && (
          <ReasonPicker code={code} note={note} onCode={setCode}>
            <Input.TextArea rows={2} maxLength={500} showCount value={note}
                            placeholder="给作者看的说明(系统通知、申诉页里都有)"
                            onChange={(e) => setNote(e.target.value)} />
          </ReasonPicker>
        )}
        <Input.TextArea rows={2} maxLength={500} value={internal}
                        placeholder="内部备注(只在后台看得到)"
                        onChange={(e) => setInternal(e.target.value)} />
        <Muted>
          同一条帖子上没处理的举报会一起结案。
          {action === 'remove' && '下架后作者收到系统通知,可以申诉一次,由另一名审核员复核。'}
        </Muted>
      </Space>
    </Modal>
  )
}
