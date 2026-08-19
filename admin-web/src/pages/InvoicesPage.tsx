import { Alert, Button, Input, Modal, Table, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, Invoice, issueInvoice, listInvoices, rejectInvoice, yuan } from '../api'

/** 发票申请。开票是把 PDF 地址回填给商家,平台这边不生成发票。 */
export default function InvoicesPage() {
  const [rows, setRows] = useState<Invoice[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try { setRows(await listInvoices()) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, ok: string) {
    try { await fn(); message.success(ok); await load() }
    catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }

  function issue(inv: Invoice) {
    let url = ''
    Modal.confirm({
      title: `给 ${inv.merchant_name} 开票 ${yuan(inv.amount_cents)}`,
      content: (
        <>
          <p style={{ color: 'var(--sz-ink-muted)', fontSize: 13 }}>
            抬头 {inv.title} · 税号 {inv.tax_no}<br />
            收件邮箱 {inv.email}
          </p>
          <Input placeholder="发票 PDF 地址(会发给商家)"
                 onChange={(e) => { url = e.target.value }} />
        </>
      ),
      okText: '确认已开', cancelText: '取消',
      onOk: () => {
        if (!url.trim()) { message.warning('请填发票地址'); throw new Error('空') }
        return act(() => issueInvoice(inv.id, url.trim()), '已开票')
      },
    })
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Table<Invoice>
        rowKey="id" loading={loading} dataSource={rows} size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '申请时间', dataIndex: 'created_at', width: 150,
            render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
          { title: '商家', dataIndex: 'merchant_name', width: 150 },
          { title: '联系电话', dataIndex: 'owner_phone', width: 130 },
          { title: '抬头', dataIndex: 'title', ellipsis: true },
          { title: '税号', dataIndex: 'tax_no', width: 180 },
          { title: '账期', dataIndex: 'period', width: 100 },
          { title: '金额', dataIndex: 'amount_cents', width: 100, align: 'right',
            render: (v: number) => yuan(v) },
          { title: '操作', width: 140, fixed: 'right',
            render: (_, inv) => (
              <>
                <Button type="link" size="small" onClick={() => issue(inv)}>开票</Button>
                <Button type="link" size="small" danger onClick={() => {
                  let reason = ''
                  Modal.confirm({
                    title: '驳回开票申请?',
                    content: <Input.TextArea rows={2} placeholder="驳回理由(告知商家)"
                                             onChange={(e) => { reason = e.target.value }} />,
                    okText: '驳回', okButtonProps: { danger: true }, cancelText: '取消',
                    onOk: () => {
                      if (reason.trim().length < 2) {
                        message.warning('请写清理由'); throw new Error('太短')
                      }
                      return act(() => rejectInvoice(inv.id, reason.trim()), '已驳回')
                    },
                  })
                }}>驳回</Button>
              </>
            ) },
        ]}
      />
    </>
  )
}
