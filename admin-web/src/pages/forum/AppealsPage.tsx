import { Alert, Button, Card, Descriptions, Input, Modal, Radio, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ForumAppealItem, forumAppeals, resolveForumAppeal } from '../../api_forum'
import { APPEAL_RESULT, Muted, PostCell, fail, t } from './shared'

/**
 * 论坛申诉(DEV-PROMPTS-41 #380、§3.6)。
 *
 * **原审核人不能复核自己的决定** —— 列表里标着「你下架的」的那几条,按钮是灰的,
 * 服务端也会 403。每个下架决定只能申诉一次;改判(overturned)会自动把帖子恢复,
 * 维持(upheld)照样给作者发一条系统通知,让他知道复核过了。
 */
export default function ForumAppealsPage() {
  const [status, setStatus] = useState<'open' | 'resolved' | 'all'>('open')
  const [rows, setRows] = useState<ForumAppealItem[]>([])
  const [loading, setLoading] = useState(false)
  const [acting, setActing] = useState<ForumAppealItem | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { setRows((await forumAppeals(status)).items) } catch (e) { fail(e) } finally { setLoading(false) }
  }, [status])
  useEffect(() => { void load() }, [load])

  return (
    <Card title="论坛申诉">
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
        message="申诉必须换人复核"
        description="标着「你下架的」的那几条你处理不了 —— 自己复核自己等于没有申诉。每个下架决定只能申诉一次。" />
      <Space style={{ marginBottom: 12 }} wrap>
        <Radio.Group value={status} onChange={(e) => setStatus(e.target.value)} optionType="button"
          options={[{ value: 'open', label: '待复核' }, { value: 'resolved', label: '已复核' },
                    { value: 'all', label: '全部' }]} />
      </Space>
      <Table<ForumAppealItem> rowKey="decision_id" size="small" loading={loading} dataSource={rows}
        locale={{ emptyText: '没有申诉' }} pagination={{ pageSize: 20 }} scroll={{ x: 1200 }}
        columns={[
          { title: '#', dataIndex: 'decision_id', width: 64 },
          { title: '状态', width: 120, render: (_, r) => (
            <Space direction="vertical" size={0}>
              <Tag color={APPEAL_RESULT[r.appeal.result]?.color}>
                {APPEAL_RESULT[r.appeal.result]?.label ?? r.appeal.result}
              </Tag>
              {r.you_decided_original && <Tag color="warning">你下架的</Tag>}
            </Space>) },
          { title: '被下架的帖子', width: 420, render: (_, r) => <PostCell p={r.post} /> },
          { title: '下架原因', width: 200, render: (_, r) => (
            <Space direction="vertical" size={0}>
              <span>{r.original.reason_code} {r.original.reason_label}</span>
              {r.original.note && <Muted>{r.original.note}</Muted>}
              <Muted>{t(r.original.created_at)}</Muted>
            </Space>) },
          { title: '申诉理由', width: 260, render: (_, r) => (
            <Space direction="vertical" size={0}>
              <span>{r.appeal.text}</span>
              <Muted>{t(r.appeal.at)}</Muted>
            </Space>) },
          { title: '', width: 100, fixed: 'right', render: (_, r) => (r.appeal.result === 'open'
            ? <Button size="small" type="primary" disabled={r.you_decided_original}
                      onClick={() => setActing(r)}>复核</Button>
            : <Muted>{r.appeal.note || '—'}</Muted>) },
        ]} />
      {acting && <ResolveModal item={acting} onClose={(changed) => {
        setActing(null)
        if (changed) void load()
      }} />}
    </Card>
  )
}

function ResolveModal({ item, onClose }: { item: ForumAppealItem; onClose: (changed: boolean) => void }) {
  const [result, setResult] = useState<'overturned' | 'upheld'>('overturned')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    try {
      await resolveForumAppeal(item.decision_id, { result, note })
      message.success(result === 'overturned' ? '已改判,帖子恢复了' : '维持原处理,已通知作者')
      onClose(true)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  return (
    <Modal open title={`复核申诉 #${item.decision_id}`} onCancel={() => onClose(false)} okText="提交结论"
           onOk={submit} confirmLoading={busy}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <PostCell p={item.post} />
        <Descriptions size="small" column={1} bordered items={[
          { key: 'r', label: '下架原因',
            children: `${item.original.reason_code} ${item.original.reason_label}${item.original.note ? ` · ${item.original.note}` : ''}` },
          { key: 'i', label: '内部备注', children: item.original.note_internal || '—' },
          { key: 'a', label: '申诉理由', children: item.appeal.text },
        ]} />
        <Radio.Group value={result} optionType="button" buttonStyle="solid"
                     onChange={(e) => setResult(e.target.value)}
                     options={[{ value: 'overturned', label: '改判:恢复这条帖子' },
                               { value: 'upheld', label: '维持原处理' }]} />
        <Input.TextArea rows={3} maxLength={500} showCount value={note}
                        placeholder="复核结论(作者看得到)"
                        onChange={(e) => setNote(e.target.value)} />
        <Muted>作者会收到一条系统通知,不管改判还是维持。</Muted>
      </Space>
    </Modal>
  )
}
