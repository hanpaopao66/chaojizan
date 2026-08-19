import { Alert, Button, Empty, Result, Space, Table, Tag, Typography, message } from 'antd'
import { useState } from 'react'

import { ApiError, AuditProblem, runAudit } from '../api'

/**
 * 对账自检。
 *
 * ## 为什么值得单独一页
 *
 * `services/audit.py` 每天 04:00 自己跑一遍,把不平的账写进告警表 ——
 * **但没有任何界面看得到结果**。一个把"账目透明"当卖点的平台,
 * 自己的账不平了却要靠翻日志才知道,说不过去。
 *
 * ## 这页不改数据
 *
 * 只有一个「立刻跑一次」的按钮。发现问题之后的修复(补记账、退款)
 * 走各自的流程,不在这里一键改账 —— 能一键改账的对账工具,
 * 下一步就是有人用它把账"对平"。
 */
export default function AuditPage() {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<{ problems: number; detail: AuditProblem[] } | null>(null)

  async function run() {
    setRunning(true)
    try {
      setResult(await runAudit())
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="每天 04:00 自动跑一次;这里可以立刻再跑一次"
        description="核对完成订单和账本是否对得上。发现问题只报不改 —— 修复走各自的流程。"
      />
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" loading={running} onClick={run}>
          立刻跑一次
        </Button>
        {result && (
          <Typography.Text type={result.problems ? 'danger' : 'success'}>
            {result.problems ? `发现 ${result.problems} 个不平的地方` : '账目全平'}
          </Typography.Text>
        )}
      </Space>

      {result === null ? (
        <Empty description="还没跑过。点上面的按钮开始" />
      ) : result.problems === 0 ? (
        <Result status="success" title="账目全平"
                subTitle="核对窗口内的完成订单,账本都对得上" />
      ) : (
        <Table<AuditProblem>
          rowKey={(r, i) => `${r.check}-${i}`}
          dataSource={result.detail}
          size="middle"
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            {
              title: '检查项', dataIndex: 'check', width: 220,
              render: (v: string) => <Tag color="error">{v}</Tag>,
            },
            { title: '问题', dataIndex: 'detail' },
          ]}
        />
      )}
    </>
  )
}
