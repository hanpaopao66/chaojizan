import { StarFilled, StarOutlined } from '@ant-design/icons'
import { Button, Card, Empty, Input, Modal, Space, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, StayReview, merchantStayReviews, replyStayReview,
} from '../../api'

/** 住客点评:查看与回复(首评未回复→回复首评;有追评未回→回复追评;否则修改)。
 *  评分口径:近 180 天滚动均分,<3 条不出分。 */
export default function ReviewsPage() {
  const [list, setList] = useState<StayReview[]>([])

  const load = useCallback(async () => {
    try {
      setList(await merchantStayReviews())
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }, [])

  useEffect(() => { load() }, [load])

  function reply(review: StayReview) {
    let text = review.reply
    Modal.confirm({
      title: review.reply
        ? (review.append_content && !review.append_reply ? '回复追评' : '修改回复')
        : '回复点评',
      content: (
        <Input.TextArea
          defaultValue={review.reply && !(review.append_content && !review.append_reply)
            ? review.reply : ''}
          maxLength={300}
          rows={3}
          onChange={(e) => { text = e.target.value }}
        />
      ),
      okText: '发布',
      onOk: async () => {
        if (!text.trim()) {
          message.warning('回复内容不能为空')
          return Promise.reject()
        }
        try {
          await replyStayReview(review.id, text.trim())
          load()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          return Promise.reject()
        }
      },
    })
  }

  if (list.length === 0) {
    return <Empty description="还没有住客点评(评分取近 180 天滚动均分,<3 条不出分)" />
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <div style={{ color: '#888', fontSize: 12 }}>
        评分口径:近 180 天滚动均分,少于 3 条不出分——防一条差评定生死,也防刷分
      </div>
      {list.map((r) => (
        <Card key={r.id} size="small">
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <b>{r.reviewer_name}</b>
            <span>
              {[1, 2, 3, 4, 5].map((i) => i <= r.rating
                ? <StarFilled key={i} style={{ color: '#faad14', fontSize: 13 }} />
                : <StarOutlined key={i} style={{ color: '#ddd', fontSize: 13 }} />)}
            </span>
            {r.tags.map((t) => <Tag key={t}>{t}</Tag>)}
            <span style={{ flex: 1 }} />
            <span style={{ color: '#999', fontSize: 12 }}>单号 …{r.order_no.slice(-6)}</span>
          </div>
          {r.comment && <div style={{ marginTop: 4 }}>{r.comment}</div>}
          {r.reply && (
            <div style={{ fontSize: 13, color: '#FF5A1F', marginTop: 4 }}>
              我的回复:{r.reply}
            </div>
          )}
          {r.append_content && (
            <div style={{ marginTop: 4 }}>追评:{r.append_content}</div>
          )}
          {r.append_reply && (
            <div style={{ fontSize: 13, color: '#FF5A1F' }}>追评回复:{r.append_reply}</div>
          )}
          <div style={{ textAlign: 'right' }}>
            <Button size="small" onClick={() => reply(r)}>
              {r.reply
                ? (r.append_content && !r.append_reply ? '回复追评' : '修改回复')
                : '回复'}
            </Button>
          </div>
        </Card>
      ))}
    </Space>
  )
}
