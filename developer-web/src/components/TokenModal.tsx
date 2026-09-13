import { Alert, Button, Modal, Typography } from 'antd'

/**
 * 机器人 token 只显示这一次(建机器人、重置 token 之后)。
 * 关不掉、点遮罩也不关:必须点「我已保存」—— 平台只存哈希,这个窗口一关就再也看不到了。
 */
export default function TokenModal({ token, title = 'token 只显示这一次', onDone }: {
  token: string | null
  title?: string
  onDone: () => void
}) {
  return (
    <Modal title={title} open={!!token} closable={false} maskClosable={false} keyboard={false}
      footer={<Button type="primary" onClick={onDone}>我已保存,继续</Button>}>
      <Alert type="warning" showIcon style={{ marginBottom: 12 }}
        message="只显示这一次,请立刻保存到你的服务端配置里"
        description="平台只存它的哈希,关掉这个窗口就再也看不到了;丢了只能在详情页「重置 token」(旧的当场失效)。别把它提交进代码仓库。" />
      <Typography.Paragraph>
        <Typography.Text code copyable={{ text: token || '' }} style={{ wordBreak: 'break-all' }}>{token}</Typography.Text>
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 0 }}>
        调用地址:<Typography.Text code>{`${location.origin}/bot/<token>/getMe`}</Typography.Text>。
        Telegram 的机器人框架把 base url 换成 <Typography.Text code>{`${location.origin}/bot/`}</Typography.Text> 就能用。
      </Typography.Paragraph>
    </Modal>
  )
}
