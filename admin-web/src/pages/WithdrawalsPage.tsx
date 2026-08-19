import {
  Alert, Button, Input, Modal, Space, Statistic, Table, Tabs, Tag, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  AdminWithdrawal, ApiError, batchPaid, listWithdrawals, markPaid,
  markWithdrawalFailed, rejectWithdrawal, t1BatchPaid, yuan,
} from '../api'

/**
 * 提现打款。
 *
 * ## 这页最要小心
 *
 * 点一下「已打款」并**不会真的转账** —— 它只是把状态改成 paid,表示
 * "线下已经打过了"。所以顺序永远是:先在银行/微信侧把钱打出去,
 * 回来再点这里。反过来点了却没打,骑手看到的是"已到账"而钱没到。
 *
 * ## 为什么突出「账户近期改过」
 *
 * 改收款账户 + 立刻提现是典型的盗号套路。后端已经把
 * `account_recently_changed` 算好了,界面要让它**扎眼**,
 * 而不是塞在第八列里等人自己发现。
 */
export default function WithdrawalsPage() {
  const [status, setStatus] = useState('pending')
  const [rows, setRows] = useState<AdminWithdrawal[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [selected, setSelected] = useState<number[]>([])
  const [note, setNote] = useState('')
  const [batchOpen, setBatchOpen] = useState(false)
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      setRows(await listWithdrawals(status))
      setSelected([])
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [status])

  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, ok: string) {
    setActing(true)
    try {
      await fn()
      message.success(ok)
      await load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setActing(false)
    }
  }

  const chosen = rows.filter((r) => selected.includes(r.id))
  const chosenTotal = chosen.reduce((s, r) => s + r.amount_cents, 0)
  const chosenRisky = chosen.filter((r) => r.account_recently_changed)

  function confirmOne(w: AdminWithdrawal) {
    Modal.confirm({
      title: `确认已经打款 ${yuan(w.amount_cents)}?`,
      content: (
        <>
          <p>收款人:{w.name || '—'} · {w.account_bank} {w.account_no}</p>
          <p style={{ color: 'var(--sz-hold)' }}>
            这一步<b>不会真的转账</b>。请先在银行侧打款,再回来点确认。
          </p>
          {w.account_recently_changed && (
            <Alert type="error" showIcon
                   message="这个账户近期改过 —— 打款前请另行核实本人" />
          )}
        </>
      ),
      okText: '确认已打款',
      cancelText: '再看看',
      onOk: () => act(() => markPaid(w.id, note.trim()), '已标记打款'),
    })
  }

  function doReject(w: AdminWithdrawal) {
    let reason = ''
    Modal.confirm({
      title: `驳回 ${w.name || w.id} 的提现?`,
      content: (
        <>
          <p style={{ color: 'var(--sz-ink-muted)' }}>
            驳回后冻结的余额自动退回,对方可以重新申请。
          </p>
          <Input.TextArea rows={2} maxLength={200} placeholder="驳回理由(会告知对方)"
                          onChange={(e) => { reason = e.target.value }} />
        </>
      ),
      okText: '驳回',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => {
        if (reason.trim().length < 2) {
          message.warning('请写清驳回理由')
          return Promise.reject(new Error('理由太短'))
        }
        return act(() => rejectWithdrawal(w.id, reason.trim()), '已驳回')
      },
    })
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12 }}
        message="「已打款」只是记账,不会真的转账 —— 先在银行侧打出去,再回来点。"
      />
      {status === 'pending' && (
        <Space style={{ marginBottom: 12 }}>
          <Button onClick={() => Modal.confirm({
            title: 'T+1 批量打款?',
            content: '把昨天(北京时间)及更早申请的待打款一次全标成已打款。'
              + '同样不会真的转账 —— 确认银行侧那一批已经打完了再点。',
            okText: '确认', cancelText: '取消',
            onOk: () => act(async () => {
              const r = await t1BatchPaid()
              message.success(`已标记 ${r.done} 笔`)
            }, 'T+1 批量完成'),
          })}>T+1 批量打款</Button>
        </Space>
      )}
      <Tabs
        activeKey={status}
        onChange={setStatus}
        items={[
          { key: 'pending', label: '待打款' },
          { key: 'paid', label: '已打款' },
          { key: 'rejected', label: '已驳回' },
          { key: 'failed', label: '退票' },
        ]}
      />

      {status === 'pending' && selected.length > 0 && (
        <Space style={{ marginBottom: 12 }} wrap>
          <Statistic title="已选" value={selected.length} suffix="笔"
                     valueStyle={{ fontSize: 18 }} />
          <Statistic title="合计" value={yuan(chosenTotal)}
                     valueStyle={{ fontSize: 18 }} />
          <Button type="primary" onClick={() => setBatchOpen(true)}>
            批量标记已打款
          </Button>
          {chosenRisky.length > 0 && (
            <Tag color="error">
              其中 {chosenRisky.length} 笔账户近期改过
            </Tag>
          )}
        </Space>
      )}

      <Table<AdminWithdrawal>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        rowSelection={status === 'pending' ? {
          selectedRowKeys: selected,
          onChange: (keys) => setSelected(keys as number[]),
        } : undefined}
        // 账户近期改过的整行标出来,不指望人去看某一列
        rowClassName={(r) => r.account_recently_changed ? 'row-risky' : ''}
        columns={[
          {
            title: '对象', width: 150,
            render: (_, r) => (
              <>
                <Tag color={r.role === 'merchant' ? 'orange' : 'blue'}>
                  {r.role === 'merchant' ? '商家' : '骑手'}
                </Tag>
                {r.name || `#${r.id}`}
              </>
            ),
          },
          { title: '手机号', dataIndex: 'phone', width: 130 },
          {
            title: '金额', dataIndex: 'amount_cents', width: 110,
            align: 'right',
            render: (v: number) => (
              <b style={{ fontVariantNumeric: 'tabular-nums' }}>{yuan(v)}</b>
            ),
          },
          {
            title: '收款账户', width: 240,
            render: (_, r) => (
              <>
                <div>{r.account_bank} {r.account_no}</div>
                <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)' }}>
                  {r.account_holder}
                </div>
                {r.account_recently_changed && (
                  <Tag color="error" style={{ marginTop: 2 }}>近期改过账户</Tag>
                )}
              </>
            ),
          },
          { title: '申请时间', dataIndex: 'created_at', width: 170,
            render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
          {
            title: '状态', dataIndex: 'status', width: 90,
            render: (v: string) => ({
              pending: <Tag>待打款</Tag>,
              paid: <Tag color="success">已打款</Tag>,
              rejected: <Tag color="default">已驳回</Tag>,
              failed: <Tag color="error">退票</Tag>,
            }[v] ?? <Tag>{v}</Tag>),
          },
          {
            title: '备注', width: 160, ellipsis: true,
            render: (_, r) => r.paid_note || r.reject_reason || '—',
          },
          {
            title: '操作', width: 150, fixed: 'right',
            render: (_, r) => r.status === 'pending' ? (
              <Space size={4}>
                <Button type="link" size="small" disabled={acting}
                        onClick={() => confirmOne(r)}>已打款</Button>
                <Button type="link" size="small" danger disabled={acting}
                        onClick={() => doReject(r)}>驳回</Button>
              </Space>
            ) : r.status === 'paid' ? (
              // 退票只能从「已打款」进:银行退回/收款信息有误。
              // 余额自动退回,自动开工单跟进,申请人可重新发起
              <Button type="link" size="small" danger disabled={acting}
                      onClick={() => {
                        let reason = '银行卡信息有误,款项被退回'
                        Modal.confirm({
                          title: '标记这笔退票?',
                          content: (
                            <>
                              <p style={{ color: 'var(--sz-ink-muted)' }}>
                                余额自动退回,会推送申请人并自动开工单跟进。
                              </p>
                              <Input.TextArea rows={2} maxLength={200}
                                              defaultValue={reason}
                                              onChange={(e) => { reason = e.target.value }} />
                            </>
                          ),
                          okText: '确认退票', okButtonProps: { danger: true },
                          cancelText: '取消',
                          onOk: () => act(
                            () => markWithdrawalFailed(r.id, reason.trim()),
                            '已标记退票,余额已退回'),
                        })
                      }}>标记退票</Button>
            ) : null,
          },
        ]}
      />

      <Modal
        open={batchOpen}
        title={`批量标记已打款:${selected.length} 笔,合计 ${yuan(chosenTotal)}`}
        okText="确认这些都已经打出去了"
        cancelText="再看看"
        confirmLoading={acting}
        onCancel={() => setBatchOpen(false)}
        onOk={() => act(async () => {
          await batchPaid(selected, note.trim())
          setBatchOpen(false)
          setNote('')
        }, `已标记 ${selected.length} 笔`)}
      >
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
               message="同样不会真的转账。确认银行侧那一批已经打完了再点。" />
        {chosenRisky.length > 0 && (
          <Alert type="error" showIcon style={{ marginBottom: 12 }}
                 message={`其中 ${chosenRisky.length} 笔的收款账户近期改过`}
                 description={chosenRisky.map((r) =>
                   `${r.name || r.id} ${yuan(r.amount_cents)}`).join('、')} />
        )}
        <Input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={200}
          placeholder="打款批次号 / 凭证号(会同步给对方看)"
        />
      </Modal>

      <style>{`.row-risky td { background: var(--sz-danger-soft) !important; }`}</style>
    </>
  )
}
