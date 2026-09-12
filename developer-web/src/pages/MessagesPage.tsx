import { Alert, Card, List, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { Decision, api, time } from '../api'

/** 消息:审核结果、处罚、申诉结果(来自审核记录),以及接受之后又变过的开发者规则。 */
export default function MessagesPage() {
  const [data, setData] = useState<{ decisions: Decision[]; rule_updates: Array<{ revision: number; at: string }> } | null>(null)
  useEffect(() => { api.messages().then(setData).catch(() => setData({ decisions: [], rule_updates: [] })) }, [])
  return (
    <Card title="消息" loading={!data}>
      {data && data.rule_updates.length > 0 && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message={`开发者规则更新到了第 ${data.rule_updates[data.rule_updates.length - 1].revision} 版`}
          description={<>去「账号与认证」里阅读并接受;逐条变更见 <a href="/opensource" target="_blank" rel="noreferrer">规则变更留痕</a>。</>} />
      )}
      <List dataSource={data?.decisions || []} locale={{ emptyText: '没有消息' }} renderItem={(d) => (
        <List.Item>
          <List.Item.Meta
            title={<Space>{d.app_name || '账号'}<Tag>{d.action_label}</Tag>{d.reason_code && <Tag color="error">{d.reason_code}</Tag>}</Space>}
            description={<Space direction="vertical" size={0}>
              <Typography.Text type="secondary">{time(d.created_at)}</Typography.Text>
              {d.note_public && <span>{d.note_public}</span>}
            </Space>} />
        </List.Item>)} />
    </Card>
  )
}
