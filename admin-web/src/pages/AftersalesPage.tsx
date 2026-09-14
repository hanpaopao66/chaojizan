import { Alert, Button, Image, Input, Modal, Select, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  AfterSale, ApiError, listAfterSales, rejectErrandAfterSale, riderFault, yuan,
} from '../api'

/**
 * 售后仲裁。
 *
 * ## 判骑手责任是**动钱**的动作
 *
 * 点下去会全额退用户(含配送费),商家无责、净额不动;这单骑手收入冲回、平台这单佣金不收,
 * 商家那份餐钱先从骑手保障金池出,池子不够的从骑手收入里扣(server/app/services/rider_fault.py,
 * 平台不出钱)。这一单记为骑手责任,是骑手信用分的扣分项(server/app/services/credit.py),
 * 骑手 72 小时内可以申诉,成立的话扣的钱退回。所以确认框里要把金额和后果写清楚,
 * 不是弹一个「确定吗」。
 *
 * ## 跑腿单只有两个选项
 *
 * 跑腿没有商家,售后由平台处理。2026-09-14 起平台不再「同意 = 平台认赔」:是骑手的问题
 * 判骑手责任(钱同上),不是就驳回(顾客可以对驳回申诉)。
 */
export default function AftersalesPage() {
  const [days, setDays] = useState(7)
  const [rows, setRows] = useState<AfterSale[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try { setRows(await listAfterSales(days)) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [days])
  useEffect(() => { void load() }, [load])

  function judge(a: AfterSale) {
    let reason = ''
    Modal.confirm({
      title: '判骑手责任?',
      width: 560,
      content: (
        <>
          <Alert type="warning" showIcon style={{ margin: '8px 0' }}
                 message={`将全额退用户 ${yuan(a.total_cents)}(含配送费)`}
                 description={'商家无责,净额不动。这单骑手的收入不计、平台这单佣金不收;'
                   + '商家那份餐钱先由骑手保障金池出,池子不够的从骑手收入里扣(平台不出钱)。'
                   + '这一单记为骑手责任,扣骑手信用分;骑手会收到通知,72 小时内可以申诉,'
                   + '成立的话扣的钱退回。'} />
          <Input.TextArea rows={2} maxLength={200} placeholder="判责理由"
                          onChange={(e) => { reason = e.target.value }} />
        </>
      ),
      okText: '确认判骑手责任',
      okButtonProps: { danger: true },
      cancelText: '再看看',
      onOk: async () => {
        if (reason.trim().length < 2) {
          message.warning('请写清判责理由')
          throw new Error('理由太短')
        }
        setActing(true)
        try {
          const r = await riderFault(a.id, reason.trim())
          message.success(`已退顾客 ${yuan(r.refunded_cents)};保障金池出 ${yuan(r.fund_cents ?? 0)},`
            + `骑手另出 ${yuan(r.rider_charge_cents ?? 0)}`)
          await load()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          throw e
        } finally { setActing(false) }
      },
    })
  }

  function reject(a: AfterSale) {
    let reply = ''
    Modal.confirm({
      title: '驳回这条跑腿售后?',
      width: 520,
      content: (
        <>
          <Alert type="info" showIcon style={{ margin: '8px 0' }}
                 message="不是骑手的问题:不退款,顾客会收到驳回理由,72 小时内可以申诉"
                 description="平台不再替跑腿单认赔。顾客申诉成立的话,判的是骑手责任(扣骑手的钱)。" />
          <Input.TextArea rows={2} maxLength={200} placeholder="驳回理由(会展示给顾客)"
                          onChange={(e) => { reply = e.target.value }} />
        </>
      ),
      okText: '驳回',
      cancelText: '再看看',
      onOk: async () => {
        if (reply.trim().length < 2) {
          message.warning('请写清驳回理由')
          throw new Error('理由太短')
        }
        setActing(true)
        try {
          await rejectErrandAfterSale(a.id, reply.trim())
          message.success('已驳回')
          await load()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          throw e
        } finally { setActing(false) }
      },
    })
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Space style={{ marginBottom: 12 }}>
        <Select value={days} onChange={setDays} style={{ width: 120 }}
                options={[7, 14, 30].map((d) => ({ value: d, label: `近 ${d} 天` }))} />
      </Space>
      <Table<AfterSale>
        rowKey="id" loading={loading} dataSource={rows} size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 160,
            render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
          { title: '订单号', dataIndex: 'order_no', width: 190 },
          { title: '原因', dataIndex: 'reason', ellipsis: true },
          { title: '凭证', width: 120,
            render: (_, a) => a.images?.length ? (
              <Image.PreviewGroup>
                {a.images.slice(0, 3).map((u) => (
                  <Image key={u} src={u} width={32} height={32}
                         style={{ objectFit: 'cover', marginRight: 4 }} />
                ))}
              </Image.PreviewGroup>
            ) : '—' },
          { title: '订单额', dataIndex: 'total_cents', width: 100, align: 'right',
            render: (v: number) => yuan(v) },
          { title: '已退', dataIndex: 'refund_cents', width: 100, align: 'right',
            render: (v: number) => v ? yuan(v) : '—' },
          // fault 取值:merchant / rider / platform(商家或骑手申诉改判成立,冲的扣的钱由平台补回;
          // 也有历史上的食安垫付、跑腿认赔),空 = 还没判
          { title: '判责', dataIndex: 'fault', width: 110,
            render: (v: string, a) => ({
              platform: <Tag color="default">平台认(改判)</Tag>,
              rider: <Tag color="error">骑手</Tag>,
              merchant: <Tag color="warning">商家</Tag>,
            }[v] ?? (a.status === 'rejected'
              ? <Tag color="default">已驳回</Tag>
              : <Tag color="warning">未判</Tag>)) },
          { title: '操作', width: 170, fixed: 'right',
            render: (_, a) => !a.fault ? (
              <Space size={0}>
                <Button type="link" danger size="small" disabled={acting}
                        onClick={() => judge(a)}>判骑手责任</Button>
                {a.is_errand && a.status === 'pending' && (
                  <Button type="link" size="small" disabled={acting}
                          onClick={() => reject(a)}>驳回</Button>
                )}
              </Space>
            ) : null },
        ]}
      />
    </>
  )
}
