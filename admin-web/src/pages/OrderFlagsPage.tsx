import { Alert, Button, Space, Switch, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, listOrderFlags, OrderFlagDetail, OrderFlagPerson,
  resolveOrderFlag,
} from '../api'

/**
 * 异常订单标记(商家上报,平台跨店核查)。
 *
 * ## 这一页存在的理由
 *
 * 平台**不给商家拉黑顾客的权力** —— 给了它会变成报复工具(差评了就拉黑)。
 * 作为交换,平台承诺了一件单店做不到的事:把多家店的标记放在一起看。
 *
 * 真正的职业索赔是**跨店行为**:同一个人在十家店用同样的话术要退款,
 * 每个老板各自只看到"一个难缠的客人",只有平台看得到那是同一个人。
 *
 * 这一页以前不存在,商家标了 45 条一条都没人看 —— 那等于收下举报
 * 然后扔进抽屉,比不做更坏:商家端写着「平台会核查」。
 *
 * ## 默认只看跨店的
 *
 * 单店标记噪音很多(一次不愉快的退款就可能被标)。被两家以上不同的店
 * 标记过才是这个功能真正要找的信号。
 *
 * ## 下结论 ≠ 处罚
 *
 * 这里的「属实/不成立」只改标记状态。**要限制账号请走「风控」那一页** ——
 * 那条路径有留痕、有申诉通道,而这里没有。两件事合并的话,
 * 「商家标记」就成了一条绕过申诉的处罚路径。
 */
const KIND_LABEL: Record<string, string> = {
  claim: '疑似职业索赔',
  review: '疑似恶意差评',
  other: '其他异常',
}

const STATUS_LABEL: Record<string, { text: string; color?: string }> = {
  pending: { text: '待核查', color: 'gold' },
  reviewed: { text: '核查属实', color: 'red' },
  dismissed: { text: '不成立' },
}

export default function OrderFlagsPage() {
  const [rows, setRows] = useState<OrderFlagPerson[]>([])
  const [note, setNote] = useState('')
  const [crossOnly, setCrossOnly] = useState(true)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try {
      const r = await listOrderFlags(crossOnly)
      setRows(r.items)
      setNote(r.how_to_read)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [crossOnly])
  useEffect(() => { void load() }, [load])

  async function resolve(id: number, result: 'reviewed' | 'dismissed') {
    try {
      await resolveOrderFlag(id, result)
      message.success('已记录结论;顾客账号不受影响')
      await load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {err && <Alert type="error" showIcon message={err} />}
      {note && <Alert type="info" showIcon message={note} />}
      <Space>
        <Switch
          checked={crossOnly}
          onChange={setCrossOnly}
          checkedChildren="只看跨店"
          unCheckedChildren="全部"
        />
        <span style={{ color: 'var(--sz-ink-muted, #666)' }}>
          被两家以上不同的店标记过,才是这个功能要找的信号
        </span>
        <Button onClick={() => void load()}>刷新</Button>
      </Space>
      <Table<OrderFlagPerson>
        rowKey="user_id"
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        expandable={{
          expandedRowRender: (p) => (
            <Table<OrderFlagDetail>
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={p.details}
              columns={[
                { title: '店铺', dataIndex: 'shop' },
                {
                  title: '订单', dataIndex: 'order_no',
                  render: (v: string) => v.slice(-6),
                },
                {
                  title: '类型', dataIndex: 'kind',
                  render: (v: string) => KIND_LABEL[v] ?? v,
                },
                { title: '商家写的理由', dataIndex: 'reason' },
                {
                  title: '状态', dataIndex: 'status',
                  render: (v: string) => {
                    const s = STATUS_LABEL[v] ?? { text: v }
                    return <Tag color={s.color}>{s.text}</Tag>
                  },
                },
                {
                  title: '结论', key: 'act',
                  render: (_: unknown, d: OrderFlagDetail) =>
                    d.status !== 'pending' ? null : (
                      <Space>
                        <Button
                          size="small" danger
                          onClick={() => void resolve(d.id, 'reviewed')}
                        >
                          属实
                        </Button>
                        <Button
                          size="small"
                          onClick={() => void resolve(d.id, 'dismissed')}
                        >
                          不成立
                        </Button>
                      </Space>
                    ),
                },
              ]}
            />
          ),
        }}
        columns={[
          { title: '顾客', dataIndex: 'name' },
          { title: '手机号', dataIndex: 'phone' },
          {
            // 排在第一位的排序依据 —— 这一列就是这个功能要找的东西
            title: '被几家店标过', dataIndex: 'shop_count',
            render: (v: number) => (
              <Tag color={v >= 3 ? 'red' : v >= 2 ? 'orange' : undefined}>
                {v} 家
              </Tag>
            ),
          },
          { title: '标记次数', dataIndex: 'flags' },
          {
            title: '待核查', dataIndex: 'pending',
            render: (v: number) => (v ? <Tag color="gold">{v}</Tag> : '—'),
          },
          {
            title: '类型分布', dataIndex: 'kinds',
            render: (k: Record<string, number>) => (
              <Space size={4}>
                {Object.entries(k).map(([kind, n]) => (
                  <Tag key={kind}>{(KIND_LABEL[kind] ?? kind)} ×{n}</Tag>
                ))}
              </Space>
            ),
          },
        ]}
      />
      <Alert
        type="warning"
        showIcon
        message="下结论不等于处罚"
        description={
          '这里的「属实/不成立」只改标记状态,不会对顾客账号做任何事。' +
          '要限制账号请走「风控」那一页 —— 那条路径有留痕、也有申诉通道。' +
          '两件事合并的话,「商家标记」就成了一条绕过申诉的处罚路径。'
        }
      />
    </Space>
  )
}
