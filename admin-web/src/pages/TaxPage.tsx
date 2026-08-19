import { Alert, Button, Card, DatePicker, Space, message } from 'antd'
import { useState } from 'react'

import { ApiError, downloadTax } from '../api'

/**
 * 税务导出。
 *
 * 三份 CSV,口径各不相同,所以每个按钮下面写清**这份是给谁用的** ——
 * 报错的税表比不报好不了多少。
 */
const KINDS: { kind: string; title: string; desc: string }[] = [
  { kind: 'merchant', title: '商家收入',
    desc: '按商家汇总的当期结算额与平台佣金。开发票和申报增值税用这份' },
  { kind: 'rider', title: '骑手收入',
    desc: '按骑手汇总的当期配送收入。代扣代缴个税用这份' },
  { kind: 'platform', title: '平台收入',
    desc: '平台自己的佣金收入。平台主体报税用这份' },
]

export default function TaxPage() {
  const [period, setPeriod] = useState('')
  const [busy, setBusy] = useState('')

  async function go(kind: string) {
    if (!period) { message.warning('先选账期'); return }
    setBusy(kind)
    try {
      await downloadTax(kind, period)
      message.success('已开始下载')
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally { setBusy('') }
  }

  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
             message="导出的是 CSV,带 token 下载 —— 地址里不含凭证,不会进浏览器历史。" />
      <Space style={{ marginBottom: 16 }}>
        <span>账期</span>
        <DatePicker picker="month" onChange={(_, s) => setPeriod(s as string)}
                    placeholder="选择月份" />
      </Space>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {KINDS.map((k) => (
          <Card key={k.kind} size="small">
            <Space align="start" style={{ width: '100%' }} wrap>
              <div style={{ minWidth: 260, flex: 1 }}>
                <div style={{ fontWeight: 600 }}>{k.title}</div>
                <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)',
                              lineHeight: 1.6 }}>{k.desc}</div>
              </div>
              <Button type="primary" loading={busy === k.kind}
                      disabled={!period} onClick={() => go(k.kind)}>
                导出 CSV
              </Button>
            </Space>
          </Card>
        ))}
      </Space>
    </>
  )
}
