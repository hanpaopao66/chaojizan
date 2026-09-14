import { Alert, Button, Image, Input, Modal, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { Appeal, ApiError, listAppeals, resolveAppeal } from '../api'

/** 申诉对象类型的兜底名字。**以服务端给的 target_label 为准**(appeals._TYPE_LABELS),
 *  这里只给老服务端没带那个字段时用 */
const TARGETS: Record<string, string> = {
  review: '差评',
  after_sale: '售后判责',
  after_sale_rider: '售后判骑手责任',
  delivery_issue: '配送异常判责',
}

/** 谁提的申诉:三种角色都能提(顾客申诉按送达处理、售后被拒、取消分摊……) */
const ROLE_TAGS: Record<string, [string, string]> = {
  merchant: ['商家', 'orange'],
  rider: ['骑手', 'blue'],
  customer: ['顾客', 'green'],
}

/** 改判成立会发生什么,按申诉的是哪一类说(对着服务端 routers/appeals.py 的 _overturn 各支写)。
 *  2026-09-14「平台没有钱」之后各支的钱不一样:确认框里得照实写,不能一句「退回去」盖过 */
function overturnEffect(a: Appeal): string {
  switch (a.target_type) {
    case 'after_sale':
      return '撤销商家责任,信用分那一条不再计分;被冲掉的净额不补回(平台不出这笔钱,顾客拿到的退款也不追回)'
    case 'after_sale_rider':
      return '撤销骑手责任,判责时扣骑手的钱退回、保障金池出的回池(这笔由平台认)'
    case 'delivery_issue':
      return a.role === 'customer'
        ? '撤销「顾客原因」,顾客付的餐费由平台原路退回'
        : '撤销骑手责任,判责时扣骑手的钱退回、保障金池出的回池(这笔由平台认)'
    case 'cancel_split':
      return '顾客在取消分摊里承担的部分,由平台原路退回'
    case 'after_sale_rejected':
      return '按商家同意的口径:顾客全额退款(含配送费和小费),商家这单净额冲回、骑手那份另出,判商家责任;'
        + '跑腿单没有商家,判的是骑手责任(扣骑手的钱)'
    case 'review':
      return '差评隐藏,店铺评分扣回;写评价的人会收到通知、可以申诉'
    case 'review_hidden':
      return '评价恢复显示,重新计入评分'
    case 'risk_flag':
      return '当场解除限制'
    case 'queue_pass':
      return '队还在就还原位置;队散了位置补不回来,这次判决计入商家的排队记录'
    default:
      return '撤销原判责'
  }
}

/**
 * 判责申诉。
 *
 * 三种角色对某次判责不服,在这里申诉。「维持原判」什么都不变,「改判」按申诉的是哪一类
 * 动不同的东西(见 [overturnEffect]):骑手的钱退回、顾客的钱由平台退,而商家售后判责改判
 * 只撤销判责、不补钱 —— 确认框里照实写。
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
              ? overturnEffect(a)
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
                <Tag color={ROLE_TAGS[a.role]?.[1] ?? 'default'}>
                  {ROLE_TAGS[a.role]?.[0] ?? a.role}
                </Tag>
                {a.name} {a.phone}
              </>
            ) },
          { title: '针对', width: 200,
            render: (_, a) => (
              <>
                <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)' }}>
                  {a.target_label || TARGETS[a.target_type] || a.target_type}
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
