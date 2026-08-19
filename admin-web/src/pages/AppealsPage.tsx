import { Alert, Button, Image, Input, Modal, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { Appeal, ApiError, listAppeals, resolveAppeal } from '../api'

/** 申诉对象类型。实测取值:review / after_sale / delivery_issue */
const TARGETS: Record<string, string> = {
  review: '差评',
  after_sale: '售后判责',
  delivery_issue: '配送异常判责',
}

/**
 * 判责申诉。
 *
 * 骑手/商家对某次判责不服,在这里申诉。**改判是要花钱的** ——
 * 之前扣的罚款或收回的收入要退回去,所以两个按钮的后果不对称:
 * 「维持原判」什么都不变,「改判」会动账。
 */
export default function AppealsPage() {
  const [rows, setRows] = useState<Appeal[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try { setRows(await listAppeals()) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  function decide(a: Appeal, result: 'overturned' | 'upheld') {
    let note = ''
    const overturn = result === 'overturned'
    Modal.confirm({
      title: overturn ? '改判(撤销原判责)?' : '维持原判?',
      content: (
        <>
          <Alert
            type={overturn ? 'warning' : 'info'} showIcon style={{ margin: '8px 0' }}
            message={overturn
              ? '撤销原判责,之前扣的会退回去'
              : '原判责不变,申诉人会收到这条说明'}
          />
          <Input.TextArea rows={2} maxLength={300}
                          placeholder="处理说明(会展示给申诉人)"
                          onChange={(e) => { note = e.target.value }} />
        </>
      ),
      okText: overturn ? '确认改判' : '维持原判',
      okButtonProps: { danger: overturn },
      cancelText: '取消',
      onOk: async () => {
        if (note.trim().length < 2) {
          message.warning('请写清处理说明'); throw new Error('太短')
        }
        try {
          await resolveAppeal(a.id, result, note.trim())
          message.success(overturn ? '已改判' : '已维持原判')
          await load()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e)); throw e
        }
      },
    })
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Table<Appeal>
        rowKey="id" loading={loading} dataSource={rows} size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 150,
            render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
          { title: '申诉人', width: 170,
            render: (_, a) => (
              <>
                <Tag color={a.role === 'merchant' ? 'orange' : 'blue'}>
                  {a.role === 'merchant' ? '商家' : '骑手'}
                </Tag>
                {a.name} {a.phone}
              </>
            ) },
          { title: '针对', width: 200,
            render: (_, a) => (
              <>
                <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)' }}>
                  {TARGETS[a.target_type] ?? a.target_type}
                </div>
                {a.target_summary}
              </>
            ) },
          { title: '申诉理由', dataIndex: 'reason', ellipsis: true },
          { title: '凭证', width: 110,
            render: (_, a) => a.images?.length ? (
              <Image.PreviewGroup>
                {a.images.slice(0, 3).map((u) => (
                  <Image key={u} src={u} width={30} height={30}
                         style={{ objectFit: 'cover', marginRight: 3 }} />
                ))}
              </Image.PreviewGroup>
            ) : '—' },
          {
            title: '处理', width: 190, fixed: 'right',
            render: (_, a) => (
              <Space size={4}>
                <Button size="small" danger onClick={() => decide(a, 'overturned')}>
                  改判
                </Button>
                <Button size="small" onClick={() => decide(a, 'upheld')}>
                  维持原判
                </Button>
              </Space>
            ),
          },
        ]}
      />
    </>
  )
}
