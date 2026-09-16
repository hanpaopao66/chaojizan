import {
  Alert, Button, Card, Descriptions, Drawer, Empty, Image, Input, List, Select, Space, Table, Tag,
  Typography, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  decideRelease, MusicReleaseForAdmin, MusicStats, MusicTrackForAdmin, musicQueue, musicRelease,
  musicStats,
} from '../../api_music'
import { Muted, PersonName, fail, t } from '../community/shared'
import { useMusicReasonCodes } from './shared'

/**
 * 音乐审核(DEV-PROMPTS-41 §5.3,先审后发)。
 *
 * - **审核的单位是作品**(M3):一张专辑连里面的全部歌曲一起审,过审后歌曲不能改;
 * - 作品详情里**每首歌直接能播**:`<audio>` 放的是按审核员签名的地址(网页 audio 带不了
 *   Authorization 头),封面也是给审核员的签名地址 —— 没过审的东西只在私密桶里;
 * - 歌词、词曲编制作署名、原创 / 授权声明都摆出来:M301(侵权)、M303(署名不符)、
 *   M304(歌词违规)这几条原因代码,不看这些就判不了;
 * - 驳回必须选原因代码,X999 要写说明;音乐人能申诉一次,申诉由另一名审核员处理。
 */
export default function MusicReviewPage() {
  const [rows, setRows] = useState<MusicReleaseForAdmin[]>([])
  const [stats, setStats] = useState<MusicStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [q, s] = await Promise.all([musicQueue(), musicStats()])
      setRows(q.items); setStats(s)
    } catch (e) { fail(e) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  return (
    <Card title="音乐审核" extra={stats && (
      <Space wrap>
        <Tag color="processing">待审 {stats.reviewing}</Tag>
        <Tag>近 7 天通过 {stats.approved_7d} · 驳回 {stats.rejected_7d}(驳回率 {(stats.reject_rate_7d * 100).toFixed(1)}%)</Tag>
        <Tag>近 7 天下架 {stats.removed_7d}</Tag>
        <Tag color={stats.appeals_open ? 'error' : undefined}>待处理申诉 {stats.appeals_open}</Tag>
        <Tag color={stats.reports_open ? 'warning' : undefined}>未处理举报 {stats.reports_open}</Tag>
        <Tag>已上线作品 {stats.published_releases} · 音乐人 {stats.artists}</Tag>
      </Space>
    )}>
      <Table<MusicReleaseForAdmin> rowKey="rid" size="small" loading={loading} dataSource={rows}
        locale={{ emptyText: '没有待审的作品' }} pagination={{ pageSize: 20 }} scroll={{ x: 900 }}
        onRow={(r) => ({ onClick: () => setOpen(r.rid), style: { cursor: 'pointer' } })}
        columns={[
          { title: '封面', width: 96, render: (_, r) => (r.cover
            ? <img src={r.cover} alt="" style={{ width: 64, height: 64, objectFit: 'cover', borderRadius: 4 }} />
            : <Muted>没有封面</Muted>) },
          { title: '作品', render: (_, r) => (
            <Space direction="vertical" size={0}>
              <span>{r.title}</span>
              <Muted>{r.rid} · {KIND_LABELS[r.kind] ?? r.kind} · {r.tracks.length} 首 · {r.genre_name || '未填曲风'}</Muted>
            </Space>) },
          { title: '音乐人', width: 200, render: (_, r) => (r.artist
            ? <Space direction="vertical" size={0}>
                <span>{r.artist.name}</span>
                <PersonName p={r.artist.user} />
              </Space>
            : '—') },
          { title: '提交', width: 110, render: (_, r) => t(r.submitted_at) },
          { title: '', width: 60, render: (_, r) => <a onClick={() => setOpen(r.rid)}>审核</a> },
        ]} />
      {open && <ReviewDrawer rid={open} onClose={() => setOpen(null)}
                             onDone={() => { setOpen(null); void load() }} />}
    </Card>
  )
}

export const KIND_LABELS: Record<string, string> = { single: '单曲', ep: 'EP', album: '专辑' }

const CREDIT_LABELS: Record<string, string> = {
  lyricist: '作词', composer: '作曲', arranger: '编曲', producer: '制作人',
}

function TrackCard({ tk }: { tk: MusicTrackForAdmin }) {
  const [q, setQ] = useState<'std' | 'hq'>(tk.stream.std ? 'std' : 'hq')
  const url = q === 'hq' ? tk.stream.hq : tk.stream.std
  const credits = Object.entries(tk.credits || {}).filter(([, v]) => (v || []).length > 0)
  return (
    <Card size="small" title={<Space>{tk.track_no}. {tk.title}
      {tk.explicit && <Tag color="red">显式内容</Tag>}
      <Tag color={tk.declaration === 'original' ? 'blue' : 'purple'}>
        {tk.declaration === 'original' ? '原创声明' : '已获授权声明'}</Tag>
      {tk.transcode_status !== 'ready' && <Tag color="warning">{tk.transcode_status}</Tag>}</Space>}
      extra={tk.stream.hq && (
        <Select size="small" value={q} onChange={setQ} style={{ width: 96 }}
                options={[{ value: 'std', label: '标准 128k' }, { value: 'hq', label: '高品 256k' }]} />)}>
      {url
        // 审核员签名的播放地址:能拖进度(Range),换音质就换一个地址
        ? <audio key={url} src={url} controls preload="metadata" style={{ width: '100%' }} />
        : <Muted>这首歌还没有可播放的档位</Muted>}
      <div><Muted>{Math.round(tk.duration_ms / 1000)} 秒</Muted></div>
      {credits.length > 0 && (
        <div style={{ marginTop: 6 }}>
          {credits.map(([k, v]) => (
            <Tag key={k}>{CREDIT_LABELS[k] ?? k}:{v.join('、')}</Tag>
          ))}
        </div>
      )}
      {tk.lyrics
        ? <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0, whiteSpace: 'pre-wrap', maxHeight: 240, overflow: 'auto' }}>
            {tk.lyrics}
          </Typography.Paragraph>
        : <div style={{ marginTop: 8 }}><Muted>没有歌词</Muted></div>}
    </Card>
  )
}

export function ReviewDrawer({ rid, onClose, onDone }: {
  rid: string; onClose: () => void; onDone: () => void
}) {
  const codes = useMusicReasonCodes()
  const [d, setD] = useState<MusicReleaseForAdmin | null>(null)
  const [rej, setRej] = useState({ code: '', note: '' })
  const [busy, setBusy] = useState(false)
  useEffect(() => { musicRelease(rid).then(setD).catch(fail) }, [rid])

  async function decide(approve: boolean) {
    setBusy(true)
    try {
      await decideRelease(rid, approve
        ? { action: 'approve' }
        : { action: 'reject', reason_code: rej.code, note: rej.note })
      message.success(approve ? '已通过,作品已上线' : '已驳回')
      onDone()
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  const rejProblem = !rej.code ? '选原因代码'
    : rej.code === 'X999' && rej.note.trim().length < 5 ? 'X999 要写明原因(至少 5 个字)'
      : !rej.note.trim() ? '写一句给音乐人看的说明' : null

  return (
    <Drawer open width={920} onClose={onClose} title={d ? `审核:${d.title}` : '审核'}>
      {!d ? <Card loading /> : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {d.reports_open > 0 && <Alert type="warning" showIcon message={`这个作品有 ${d.reports_open} 条没处理的举报`} />}
          {d.status !== 'reviewing' && (
            <Alert type="info" showIcon message={`这个作品现在是「${d.status_label}」,不在审核中`} />
          )}
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="音乐人" span={2}>
              {d.artist ? <Space><span>{d.artist.name}</span><Muted>{d.artist.aid}</Muted>
                <PersonName p={d.artist.user} /></Space> : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="作品名" span={2}>{d.title}</Descriptions.Item>
            <Descriptions.Item label="类型">{KIND_LABELS[d.kind] ?? d.kind}</Descriptions.Item>
            <Descriptions.Item label="曲风">{d.genre_name || d.genre || '—'}</Descriptions.Item>
            <Descriptions.Item label="语种">{d.language_name || d.language || '—'}</Descriptions.Item>
            <Descriptions.Item label="发行日期">{d.release_date || '—'}</Descriptions.Item>
            <Descriptions.Item label="简介" span={2}>
              <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{d.description || '—'}</Typography.Paragraph>
            </Descriptions.Item>
            <Descriptions.Item label="封面" span={2}>
              {d.cover ? <Image src={d.cover} width={240} /> : <Muted>没有封面(提交时应该拦住,这里出现说明有 bug)</Muted>}
            </Descriptions.Item>
          </Descriptions>
          <Card size="small" title={`歌曲(共 ${d.tracks.length} 首)`}>
            {d.tracks.length === 0 ? <Empty description="没有歌曲" /> : (
              <Space direction="vertical" style={{ width: '100%' }}>
                {d.tracks.map((tk) => <TrackCard key={tk.tid} tk={tk} />)}
              </Space>
            )}
          </Card>
          {d.status === 'reviewing' && (
            <Card size="small" title="结论">
              <Space direction="vertical" style={{ width: '100%' }}>
                <Button type="primary" loading={busy} onClick={() => decide(true)}>通过</Button>
                <Select placeholder="驳回原因(必选,§5.11)" showSearch optionFilterProp="label" style={{ width: '100%' }}
                        value={rej.code || undefined} onChange={(v) => setRej({ ...rej, code: v })}
                        options={codes.map((c) => ({ value: c.code, label: `${c.code} ${c.label}` }))} />
                <Input.TextArea rows={2} maxLength={500} showCount placeholder="给音乐人看的说明(哪里不行、怎么改)"
                                value={rej.note} onChange={(e) => setRej({ ...rej, note: e.target.value })} />
                <Button danger disabled={!!rejProblem} loading={busy} onClick={() => decide(false)}>
                  驳回{rejProblem ? `(${rejProblem})` : ''}
                </Button>
              </Space>
            </Card>
          )}
          <Card size="small" title="审核记录">
            <List size="small" dataSource={d.decisions ?? []} locale={{ emptyText: '还没有记录' }}
              renderItem={(x) => (
                <List.Item>
                  <Space direction="vertical" size={0} style={{ width: '100%' }}>
                    <span>
                      {t(x.created_at)} · {ACTION_LABELS[x.action] ?? x.action}
                      {x.reason_code && <Tag style={{ marginLeft: 6 }}>{x.reason_code} {x.reason_label}</Tag>}
                      {x.note}
                    </span>
                    {x.appeal_at && (
                      <Muted>
                        申诉({t(x.appeal_at)}):{x.appeal_text}
                        {x.appeal_result
                          ? ` → ${x.appeal_result === 'overturned' ? '改判' : '维持'}:${x.appeal_note}`
                          : ' → 待处理'}
                      </Muted>
                    )}
                  </Space>
                </List.Item>)} />
          </Card>
        </Space>
      )}
    </Drawer>
  )
}

export const ACTION_LABELS: Record<string, string> = {
  approve: '通过', reject: '驳回', remove: '平台下架', restore: '恢复',
}
