import { StarFilled, StarOutlined } from '@ant-design/icons'
import {
  Button, Card, Empty, Image, Input, Modal, Progress, Segmented, Space,
  Statistic, Tag, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, FoodReview, RatingOverview, myFoodReviews, ratingOverview,
  replyFoodAppend, replyFoodReview,
} from '../../api'

/** 外卖顾客评价:筛选(全部/差评/待回复)+ 回复 + 追评回复。
 *  差评(≤3 星)排查优先:回应越快挽回余地越大。 */
export default function ReviewsPage() {
  const [filter, setFilter] = useState<string | number>('all')
  const [list, setList] = useState<FoodReview[]>([])
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async () => {
    try {
      setList(await myFoodReviews({
        maxRating: filter === 'bad' ? 3 : undefined,
        unreplied: filter === 'unreplied',
      }))
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoaded(true)
    }
  }, [filter])

  useEffect(() => { load() }, [load])

  function reply(review: FoodReview, append: boolean) {
    let text = append ? review.append_reply : review.reply
    Modal.confirm({
      title: append
        ? (review.append_reply ? '修改追评回复' : '回复追评')
        : (review.reply ? '修改回复' : '回复评价'),
      content: (
        <Input.TextArea
          defaultValue={text}
          maxLength={300}
          rows={3}
          placeholder="先道歉再给方案,别争对错"
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
          await (append
            ? replyFoodAppend(review.id, text.trim())
            : replyFoodReview(review.id, text.trim()))
          load()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          return Promise.reject()
        }
      },
    })
  }

  const stars = (n: number) => (
    <span>
      {[1, 2, 3, 4, 5].map((i) => i <= n
        ? <StarFilled key={i} style={{ color: n <= 3 ? 'var(--sz-danger)' : 'var(--sz-hold)', fontSize: 13 }} />
        : <StarOutlined key={i} style={{ color: 'var(--sz-ink-faint)', fontSize: 13 }} />)}
    </span>
  )

  const photos = (urls: string[]) => urls.length > 0 && (
    <Image.PreviewGroup>
      <Space style={{ marginTop: 6 }} wrap>
        {urls.map((u) => (
          <Image key={u} src={u} width={72} height={72}
            style={{ objectFit: 'cover', borderRadius: 6 }} />
        ))}
      </Space>
    </Image.PreviewGroup>
  )

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <OverviewCard />
      <Segmented
        value={filter}
        onChange={setFilter}
        options={[
          { label: '全部', value: 'all' },
          { label: '差评(≤3星)', value: 'bad' },
          { label: '待回复', value: 'unreplied' },
        ]}
      />
      {loaded && list.length === 0 && <Empty description="这一栏没有评价" />}
      {list.map((r) => (
        <Card key={r.id} size="small">
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <b>{r.customer_name}</b>
            {stars(r.merchant_rating)}
            {r.tags.map((t) => <Tag key={t}>{t}</Tag>)}
            <span style={{ flex: 1 }} />
            <span style={{ color: 'var(--sz-ink-muted)', fontSize: 12 }}>
              {r.created_at.slice(0, 10)}
            </span>
          </div>
          {r.comment && <div style={{ marginTop: 4 }}>{r.comment}</div>}
          {photos(r.image_urls)}
          {r.reply && (
            <div style={{ fontSize: 13, color: 'var(--sz-clay)', marginTop: 4 }}>
              我的回复:{r.reply}
            </div>
          )}
          {r.append_at && (
            <div style={{ marginTop: 6, paddingLeft: 8, borderLeft: '2px solid var(--sz-line)' }}>
              <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)' }}>用户追评</div>
              {r.append_content && <div>{r.append_content}</div>}
              {photos(r.append_images)}
              {r.append_reply && (
                <div style={{ fontSize: 13, color: 'var(--sz-clay)' }}>
                  追评回复:{r.append_reply}
                </div>
              )}
            </div>
          )}
          <div style={{ textAlign: 'right' }}>
            <Space>
              {r.append_at && (
                <Button size="small" onClick={() => reply(r, true)}>
                  {r.append_reply ? '改追评回复' : '回复追评'}
                </Button>
              )}
              <Button size="small" type={r.reply ? 'default' : 'primary'}
                onClick={() => reply(r, false)}>
                {r.reply ? '修改回复' : '回复'}
              </Button>
            </Space>
          </div>
        </Card>
      ))}
    </Space>
  )
}

/** 评分概览:总分不够用 —— 商家要知道是被几条差评拉的、最近在变好还是变坏。 */
function OverviewCard() {
  const [data, setData] = useState<RatingOverview | null>(null)

  useEffect(() => {
    ratingOverview().then(setData).catch(() => { /* 不打断列表 */ })
  }, [])

  if (!data?.all_time.avg) return null
  const { all_time: all, last_30d: d30 } = data
  const trend = data.trend_30d_vs_earlier

  return (
    <Card size="small">
      <Space size="large" align="start" wrap>
        <Statistic title={`店铺评分(${all.count} 条)`} value={all.avg ?? 0}
          precision={2} />
        <div style={{ minWidth: 220 }}>
          {[5, 4, 3, 2, 1].map((star) => (
            <div key={star} style={{
              display: 'flex', alignItems: 'center', gap: 6, fontSize: 12,
            }}>
              <span style={{ width: 24 }}>{star}★</span>
              <Progress
                percent={all.count ? Math.round(
                  ((all.dist[String(star)] ?? 0) / all.count) * 100) : 0}
                size="small"
                showInfo={false}
                strokeColor={star <= 3 ? 'var(--sz-danger)' : 'var(--sz-hold)'}
                style={{ flex: 1, margin: 0 }}
              />
              <span style={{ width: 28, textAlign: 'right', color: 'var(--sz-ink-muted)' }}>
                {all.dist[String(star)] ?? 0}
              </span>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 12, lineHeight: 2 }}>
          {trend != null && (
            <div style={{ color: trend > 0 ? 'var(--sz-earn)' : trend < 0 ? 'var(--sz-danger)' : 'var(--sz-ink-muted)' }}>
              近 30 天 {trend > 0 ? `↑${trend}` : trend < 0 ? `↓${-trend}` : '持平'}
              <span style={{ color: 'var(--sz-ink-muted)' }}>（对比更早)</span>
            </div>
          )}
          <div>近 30 天 {d30.count} 条,均分 {d30.avg ?? '—'}</div>
          {d30.bad_unreplied > 0 && (
            <div style={{ color: 'var(--sz-danger)' }}>
              还有 {d30.bad_unreplied} 条差评没回
            </div>
          )}
        </div>
      </Space>
    </Card>
  )
}
