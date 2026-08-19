import { Alert, Input, Select, Space, Table, Tag, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ActionLog, ApiError, listActionLogs } from '../api'

/**
 * 操作留痕。
 *
 * 这页是**只读**的,而且后端也没有删除接口 —— 能删的留痕等于没有留痕。
 *
 * 手机号是打码的:留痕列表是运营日常看的,不需要完整号码。
 * 要精确到人有 `admin_id`。
 */

const ACTIONS: Record<string, string> = {
  'merchant.approve': '商家通过',
  'merchant.reject': '商家驳回',
  'rider_profile.approve': '骑手通过',
  'rider_profile.reject': '骑手驳回',
  'withdrawal.paid': '标记打款',
  'withdrawal.batch_paid': '批量打款',
  'withdrawal.reject': '提现驳回',
  'withdrawal.failed': '打款退票',
  'flag.set': '改平台开关',
}

export default function LogsPage() {
  const [rows, setRows] = useState<ActionLog[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [action, setAction] = useState<string>('')
  const [targetId, setTargetId] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      setRows(await listActionLogs({
        action: action || undefined,
        target_id: targetId.trim() || undefined,
        limit: 200,
      }))
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [action, targetId])

  useEffect(() => { void load() }, [load])

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          style={{ width: 180 }}
          value={action}
          onChange={setAction}
          options={[
            { value: '', label: '全部操作' },
            ...Object.entries(ACTIONS).map(([v, l]) => ({ value: v, label: l })),
          ]}
        />
        <Input.Search
          style={{ width: 220 }}
          placeholder="按对象 id 查(店 id / 骑手 id)"
          allowClear
          value={targetId}
          onChange={(e) => setTargetId(e.target.value)}
          onSearch={() => void load()}
        />
      </Space>
      <Table<ActionLog>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 30, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 170,
            render: (v: string) => v?.replace('T', ' ').slice(0, 19) },
          {
            title: '操作', dataIndex: 'action', width: 130,
            render: (v: string) => <Tag>{ACTIONS[v] ?? v}</Tag>,
          },
          {
            title: '管理员', width: 170,
            render: (_, r) => (
              <>
                {r.admin_phone}
                <Typography.Text type="secondary" style={{ marginLeft: 6 }}>
                  #{r.admin_id}
                </Typography.Text>
              </>
            ),
          },
          {
            title: '对象', width: 160,
            render: (_, r) => r.target_type
              ? `${r.target_type} ${r.target_id}` : '—',
          },
          {
            title: '细节',
            render: (_, r) => {
              const d = r.detail || {}
              const parts = Object.entries(d)
                .filter(([, v]) => v !== '' && v !== null && v !== undefined)
                .map(([k, v]) => `${k}=${
                  typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
              return parts.length
                ? <span style={{ fontSize: 12 }}>{parts.join(' · ')}</span>
                : '—'
            },
          },
        ]}
      />
    </>
  )
}
