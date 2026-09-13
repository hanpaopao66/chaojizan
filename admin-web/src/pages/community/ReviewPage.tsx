import {
  Alert, Button, Card, Descriptions, Drawer, Empty, Image, Input, List, Select, Space, Table, Tag, Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  decideVideo, VideoAdminDetail, VideoCard, VideoPartOut, videoDetail, videoQueue, VideosStats, videosStats,
} from '../../api_community'
import { Muted, PersonName, fail, reasonOptions, t, useReasonCodes } from './shared'

/**
 * 视频审核(DEV-PROMPTS-40 #368 视频部分,D10 先审后发)。
 *
 * - 队列:从没发布过的新稿件 + 已发布稿件的改动,按提交时间先后;
 * - 稿件详情里**直接能播**:`<video>` 放的是按审核员签名的地址(网页 video 带不了 Authorization 头);
 * - 改动审核看的是「送审的这一版」:改了哪些字段(线上 → 改成)、这一版有哪几 P;
 * - 驳回必须选原因代码,X999 要写说明;UP 主能申诉,申诉由另一名审核员处理。
 */
export default function ReviewPage() {
  const [rows, setRows] = useState<VideoCard[]>([])
  const [stats, setStats] = useState<VideosStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [q, s] = await Promise.all([videoQueue(), videosStats()])
      setRows(q.items); setStats(s)
    } catch (e) { fail(e) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  return (
    <Card title="视频审核" extra={stats && (
      <Space wrap>
        <Tag color="processing">待审 {stats.reviewing}</Tag>
        <Tag>近 7 天通过 {stats.approved_7d} · 驳回 {stats.rejected_7d}(驳回率 {(stats.reject_rate_7d * 100).toFixed(1)}%)</Tag>
        <Tag>近 7 天下架 {stats.removed_7d}</Tag>
        <Tag color={stats.appeals_open ? 'error' : undefined}>待处理申诉 {stats.appeals_open}</Tag>
        <Tag color={stats.reports_open ? 'warning' : undefined}>未处理举报 {stats.reports_open}</Tag>
      </Space>
    )}>
      <Table<VideoCard> rowKey="vid" size="small" loading={loading} dataSource={rows}
        locale={{ emptyText: '没有待审的稿件' }} pagination={{ pageSize: 20 }} scroll={{ x: 900 }}
        onRow={(r) => ({ onClick: () => setOpen(r.vid), style: { cursor: 'pointer' } })}
        columns={[
          { title: '封面', width: 96, render: (_, r) => (r.cover
            ? <img src={r.cover} alt="" style={{ width: 80, height: 45, objectFit: 'cover', borderRadius: 4 }} />
            : <Muted>待审封面</Muted>) },
          { title: '标题', render: (_, r) => (
            <Space direction="vertical" size={0}>
              <span>{r.pending?.fields?.title ? String(r.pending.fields.title) : r.title}</span>
              <Muted>{r.vid} · {r.zone_name} · {r.is_vertical ? '竖屏' : '横屏'}</Muted>
            </Space>) },
          { title: '类型', width: 110, render: (_, r) => (r.review === 'changes'
            ? <Tag color="purple">已发布稿件的改动</Tag> : <Tag color="blue">新稿件</Tag>) },
          { title: 'UP 主', width: 180, render: (_, r) => <PersonName p={r.uploader} /> },
          { title: '提交', width: 110, render: (_, r) => t(r.pending?.submitted_at ?? r.submitted_at) },
          { title: '', width: 60, render: (_, r) => <a onClick={() => setOpen(r.vid)}>审核</a> },
        ]} />
      {open && <ReviewDrawer vid={open} onClose={() => setOpen(null)}
                             onDone={() => { setOpen(null); void load() }} />}
    </Card>
  )
}

function bestRendition(p: VideoPartOut) {
  const rs = [...p.renditions].sort((a, b) => a.q - b.q)
  return rs.filter((r) => r.q <= 720).pop() ?? rs[0]
}

function PartPlayer({ p, isNew }: { p: VideoPartOut; isNew: boolean }) {
  const [q, setQ] = useState<number | undefined>(bestRendition(p)?.q)
  const r = p.renditions.find((x) => x.q === q)
  return (
    <Card size="small" title={<Space>P{p.idx + 1} {p.title}{isNew && <Tag color="purple">这次新加的</Tag>}
      {p.status !== 'ready' && <Tag color="warning">{p.status}</Tag>}</Space>}
      extra={p.renditions.length > 0 && (
        <Select size="small" value={q} onChange={setQ} style={{ width: 96 }}
                options={p.renditions.map((x) => ({ value: x.q, label: `${x.q}P` }))} />)}>
      {r ? (
        // 审核员签名的播放地址:能拖进度(Range),换清晰度就换一个地址
        <video key={r.url} src={r.url} controls preload="metadata"
               style={{ width: '100%', maxHeight: 420, background: '#000', borderRadius: 6 }} />
      ) : <Muted>{p.error || '这一 P 还没有可播放的档位'}</Muted>}
      <Muted>{Math.round(p.duration_ms / 1000)} 秒 · {p.w}×{p.h}</Muted>
    </Card>
  )
}

const FIELD_LABELS: Record<string, string> = {
  title: '标题', description: '简介', zone: '分区', tags: '标签', copyright: '自制 / 转载', source_url: '转载来源',
  shop_id: '挂的店铺', shop_collab: '与商家有无合作', cover_media_id: '封面',
}

function show(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.join('、') || '—'
  if (typeof v === 'boolean') return v ? '是' : '否'
  return String(v)
}

function ReviewDrawer({ vid, onClose, onDone }: { vid: string; onClose: () => void; onDone: () => void }) {
  const codes = useReasonCodes()
  const [d, setD] = useState<VideoAdminDetail | null>(null)
  const [rej, setRej] = useState({ code: '', note: '', internal: '' })
  const [busy, setBusy] = useState(false)
  useEffect(() => { videoDetail(vid).then(setD).catch(fail) }, [vid])

  const changes = d?.review === 'changes'
  const parts = useMemo(() => {
    if (!d) return []
    const ids = new Set(d.version_part_ids)
    return d.parts.filter((p) => ids.has(p.id))
  }, [d])

  async function decide(approve: boolean) {
    setBusy(true)
    try {
      await decideVideo(vid, approve ? { approve: true }
        : { approve: false, reason_code: rej.code, note: rej.note, note_internal: rej.internal })
      message.success(approve ? '已通过' : '已驳回')
      onDone()
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  const rejProblem = !rej.code ? '选原因代码'
    : rej.code === 'X999' && rej.note.trim().length < 5 ? 'X999 要写明原因(至少 5 个字)'
      : !rej.note.trim() ? '写一句给 UP 主看的说明' : null

  return (
    <Drawer open width={920} onClose={onClose}
            title={d ? `审核:${d.title}${changes ? '(改动)' : ''}` : '审核'}>
      {!d ? <Card loading /> : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {d.reports_open > 0 && <Alert type="warning" showIcon message={`这个稿件有 ${d.reports_open} 条没处理的举报`} />}
          {changes && d.pending && (
            <Card size="small" title="这次改了什么(线上仍是左边那一版,通过了才换)">
              {Object.keys(d.pending.fields || {}).length === 0 ? <Muted>只改了分 P</Muted> : (
                <Table size="small" pagination={false} rowKey="k"
                  dataSource={Object.entries(d.pending.fields).map(([k, v]) => ({ k, v }))}
                  columns={[
                    { title: '字段', width: 120, render: (_, r) => FIELD_LABELS[r.k] ?? r.k },
                    { title: '线上', render: (_, r) => (r.k === 'cover_media_id'
                      ? (d.cover ? <Image src={d.cover} width={160} /> : '—')
                      : <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{show((d as unknown as Record<string, unknown>)[r.k])}</Typography.Paragraph>) },
                    { title: '改成', render: (_, r) => (r.k === 'cover_media_id'
                      ? (d.pending?.cover_preview ? <Image src={d.pending.cover_preview} width={160} /> : '—')
                      : <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{show(r.v)}</Typography.Paragraph>) },
                  ]} />
              )}
            </Card>
          )}
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="UP 主" span={2}><PersonName p={d.uploader} /></Descriptions.Item>
            <Descriptions.Item label="标题" span={2}>{d.title}</Descriptions.Item>
            <Descriptions.Item label="分区">{d.zone_name || d.zone}</Descriptions.Item>
            <Descriptions.Item label="标签">{(d.tags || []).map((x) => <Tag key={x}>{x}</Tag>)}</Descriptions.Item>
            <Descriptions.Item label="自制 / 转载">{d.copyright === 'repost' ? '转载' : '自制'}</Descriptions.Item>
            <Descriptions.Item label="转载来源">{d.source_url
              ? <a href={d.source_url} target="_blank" rel="noreferrer noopener">{d.source_url}</a> : '—'}</Descriptions.Item>
            <Descriptions.Item label="挂店铺">{d.shop ? `${d.shop.name}(${d.shop_collab ? '有合作' : '无合作'})` : '—'}</Descriptions.Item>
            <Descriptions.Item label="可见性">{d.visibility}</Descriptions.Item>
            <Descriptions.Item label="简介" span={2}>
              <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{d.description || '—'}</Typography.Paragraph>
            </Descriptions.Item>
            <Descriptions.Item label="封面" span={2}>
              {d.cover_preview ? <Image src={d.cover_preview} width={240} /> : <Muted>没有封面(通过时自动用第一 P 的截帧)</Muted>}
            </Descriptions.Item>
          </Descriptions>
          <Card size="small" title={`分 P(送审的这一版,共 ${parts.length} P)`}>
            {parts.length === 0 ? <Empty description="没有分 P" /> : (
              <Space direction="vertical" style={{ width: '100%' }}>
                {parts.map((p) => <PartPlayer key={p.id} p={p} isNew={changes && !p.live} />)}
              </Space>
            )}
          </Card>
          <Card size="small" title="结论">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button type="primary" loading={busy} onClick={() => decide(true)}>通过</Button>
              <Select placeholder="驳回原因(必选,§5.11)" showSearch optionFilterProp="label" style={{ width: '100%' }}
                      value={rej.code || undefined} onChange={(v) => setRej({ ...rej, code: v })}
                      options={reasonOptions(codes)} />
              <Input.TextArea rows={2} maxLength={500} showCount placeholder="给 UP 主看的说明(哪里不行、怎么改)"
                              value={rej.note} onChange={(e) => setRej({ ...rej, note: e.target.value })} />
              <Input.TextArea rows={2} maxLength={500} placeholder="内部备注(只在后台看得到)"
                              value={rej.internal} onChange={(e) => setRej({ ...rej, internal: e.target.value })} />
              <Button danger disabled={!!rejProblem} loading={busy} onClick={() => decide(false)}>
                驳回{rejProblem ? `(${rejProblem})` : ''}
              </Button>
            </Space>
          </Card>
          <Card size="small" title="审核记录">
            <List size="small" dataSource={d.decisions} locale={{ emptyText: '还没有记录' }}
              renderItem={(x) => (
                <List.Item>
                  {t(x.created_at)} · {x.action_label} {x.reason_code && <Tag>{x.reason_code} {x.reason_label}</Tag>}
                  {x.note}{x.note_internal && <Muted>(内部:{x.note_internal})</Muted>}
                </List.Item>)} />
          </Card>
        </Space>
      )}
    </Drawer>
  )
}
