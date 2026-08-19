import { Alert, Button, Card, Image, Input, Modal, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, issueGear, listAccidents, listEmergencies, listGear,
  RiderAccident, RiderEmergency, RiderGear, updateAccident, updateEmergency,
} from '../api'

/**
 * 骑手关怀:一键求助、事故、装备申领。
 *
 * ## 求助排在最上面
 *
 * 骑手按的是 SOS —— 人可能正在出事。这一页里它排第一,红底,
 * 而且带经纬度(点得开地图)。事故是事后跟进,装备是行政事务,
 * 这两个晚半天不要紧,SOS 晚半天可能就是另一回事。
 */
export default function RiderCarePage() {
  const [sos, setSos] = useState<RiderEmergency[]>([])
  const [acc, setAcc] = useState<RiderAccident[]>([])
  const [gear, setGear] = useState<RiderGear[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try {
      const [s, a, g] = await Promise.all([
        listEmergencies('open'), listAccidents('open'), listGear(),
      ])
      setSos(s); setAcc(a); setGear(g)
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, ok: string) {
    try { await fn(); message.success(ok); await load() }
    catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }

  function follow(title: string, run: (status: string, note: string) => Promise<unknown>) {
    let note = ''
    Modal.confirm({
      title,
      content: <Input.TextArea rows={3} maxLength={300} placeholder="跟进记录"
                               onChange={(e) => { note = e.target.value }} />,
      okText: '标记跟进中', cancelText: '取消',
      onOk: () => act(() => run('following', note.trim()), '已标记跟进'),
    })
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}

      <Card size="small" loading={loading} style={{ marginBottom: 12 }}
            title={<span style={{ color: 'var(--sz-danger)' }}>
              一键求助 {sos.length}(人可能正在出事)
            </span>}>
        <Table<RiderEmergency>
          rowKey="id" dataSource={sos} size="middle" pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: '当前没有求助' }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 150,
              render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
            { title: '骑手', dataIndex: 'rider_phone', width: 130 },
            { title: '位置', width: 200,
              render: (_, e) => e.lat && e.lng ? (
                <a href={`https://uri.amap.com/marker?position=${e.lng},${e.lat}`}
                   target="_blank" rel="noreferrer">
                  {e.lat.toFixed(5)}, {e.lng.toFixed(5)}
                </a>
              ) : '—' },
            { title: '说明', dataIndex: 'note', ellipsis: true },
            { title: '', width: 110, fixed: 'right',
              render: (_, e) => (
                <Button size="small" danger onClick={() => follow(
                  `跟进求助 · ${e.rider_phone}`,
                  (st, n) => updateEmergency(e.id, st, n))}>跟进</Button>
              ) },
          ]}
        />
      </Card>

      <Card size="small" title={`事故上报 ${acc.length}`} loading={loading}
            style={{ marginBottom: 12 }}>
        <Table<RiderAccident>
          rowKey="id" dataSource={acc} size="middle"
          pagination={{ pageSize: 10, showSizeChanger: false }}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: '没有待跟进的事故' }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 150,
              render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
            { title: '骑手', dataIndex: 'rider_phone', width: 130 },
            { title: '严重程度', dataIndex: 'severity', width: 100,
              render: (v: string) => <Tag color="warning">{v}</Tag> },
            { title: '描述', dataIndex: 'description', ellipsis: true },
            { title: '照片', width: 120,
              render: (_, a) => a.photos?.length ? (
                <Image.PreviewGroup>
                  {a.photos.slice(0, 3).map((u) => (
                    <Image key={u} src={u} width={30} height={30}
                           style={{ objectFit: 'cover', marginRight: 3 }} />
                  ))}
                </Image.PreviewGroup>
              ) : '—' },
            { title: '', width: 110, fixed: 'right',
              render: (_, a) => (
                <Button size="small" onClick={() => follow(
                  `跟进事故 · ${a.rider_phone}`,
                  (st, n) => updateAccident(a.id, st, n))}>跟进</Button>
              ) },
          ]}
        />
      </Card>

      <Card size="small" title={`装备申领 ${gear.length}`} loading={loading}>
        <Table<RiderGear>
          rowKey="id" dataSource={gear} size="middle"
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: '没有待发放的申领' }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 150,
              render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
            { title: '骑手', dataIndex: 'rider_phone', width: 130 },
            { title: '申领物品', dataIndex: 'item_label' },
            { title: '', width: 110,
              render: (_, g) => (
                <Button size="small" type="link"
                        onClick={() => act(() => issueGear(g.id), '已发放')}>
                  标记已发
                </Button>
              ) },
          ]}
        />
      </Card>
    </>
  )
}
