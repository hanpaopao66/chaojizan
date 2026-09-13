import { Alert, Col, Row } from 'antd'

import { ModerationWordsCard } from '../ModerationPage'

/**
 * 屏蔽词:和「内容审核」页同一张表、同一个组件(#369 services/moderation.guard_text)。
 * 聊天消息、改消息、群名 / 简介、签名、用户名、评论、弹幕、视频标题都过它;命中就拒,告诉用户「包含不允许的内容」。
 */
export default function WordsPage() {
  return (
    <Row gutter={[12, 12]}>
      <Col xs={24} lg={16}>
        <Alert type="info" showIcon style={{ marginBottom: 12 }}
               message="这张词表全站共用:聊天消息、群名、签名、用户名、评论、弹幕、视频标题,以及外卖的评价、昵称。改动立刻生效。" />
        <ModerationWordsCard pageSize={20} />
      </Col>
    </Row>
  )
}
