import {
  Alert, Button, Card, Input, Modal, Radio, Select, Space, Table, Tag, Typography, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { MusicReportItem, handleMusicReport, musicReports } from '../../api_music'
import { Muted, STATUS_COLORS, fail, t } from '../community/shared'
import { TARGET_LABELS, useMusicReasonCodes } from './shared'

/**
 * 音乐举报(DEV-PROMPTS-41 §5.11)。
 *
 * - **举报人不出现在这里**:举报人对被举报的一方永远匿名(接口也不下发 reporter_id);
 * - **版权投诉(M301)带联系方式**:侵权要联系得上投诉人才能核实,所以那一栏单独标出来、
 *   能一键复制。它只给审核员看,不给被举报的音乐人;
 * - 「按举报处置」按对象类型分别处理:歌 / 作品 → 下架所在的**作品**(审核单位是作品)、
 *   评论 → 删除、歌单 → 改成私密(是用户自己的东西,不删)、音乐人 → 停用;
 * - 7 天内 3 个不同的人举报同一个对象自动进复审(escalated),排在最前。
 */
export default function MusicReportsPage() {
  const codes = useMusicReasonCodes()
  const [status, setStatus] = useState<'open' | 'handled' | 'all'>('open')
  const [rows, setRows] = useState<MusicReportItem[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try { setRows((await musicReports(status)).items) } catch (e) { fail(e) } finally { setLoading(false) }
  }, [status])
  useEffect(() => { void load() }, [load])

  function handle(r: MusicReportItem, action: 'dismiss' | 'remove_target') {
    let code = ''
    let note = ''
    Modal.confirm({
      title: action === 'dismiss' ? '举报不成立' : `处置:${TARGET_LABELS[r.target_type]}`,
      width: 560,
      content: (
        <Space direction="vertical" style={{ width: '100%' }}>
          {action === 'remove_target' && (
            <>
              <Alert type="warning" showIcon message={REMOVE_HINTS[r.target_type]} />
              <Select placeholder="原因代码(必选,§5.11)" showSearch optionFilterProp="label"
                      style={{ width: '100%' }} onChange={(v) => { code = v }}
                      options={codes.map((c) => ({ value: c.code, label: `${c.code} ${c.label}` }))} />
            </>
          )}
          <Input.TextArea rows={2} maxLength={500}
                          placeholder={action === 'dismiss' ? '备注(可选)' : '说明(选 X999 时必填,至少 5 个字)'}
                          onChange={(e) => { note = e.target.value }} />
        </Space>),
      okButtonProps: { danger: action === 'remove_target' },
      onOk: async () => {
        try {
          const out = await handleMusicReport(r.id, { action, reason_code: code, note })
          message.success(out.resolution)
          await load()
        } catch (e) { fail(e); throw e }
      },
    })
  }

  return (
    <Card title="音乐举报" extra={
      <Radio.Group value={status} onChange={(e) => setStatus(e.target.value)} optionType="button"
        options={[{ value: 'open', label: '待处理' }, { value: 'handled', label: '已处理' },
                  { value: 'all', label: '全部' }]} />
    }>
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
             message="举报人对被举报的一方永远匿名;版权投诉的联系方式只给审核员看,不要转给被举报的音乐人。" />
      <Table<MusicReportItem> rowKey="id" size="small" loading={loading} dataSource={rows}
        locale={{ emptyText: '没有举报' }} pagination={{ pageSize: 20 }} scroll={{ x: 1000 }}
        columns={[
          { title: '对象', width: 260, render: (_, r) => <TargetCell r={r} /> },
          { title: '原因', width: 200, render: (_, r) => (
            <Space direction="vertical" size={0}>
              <Space>
                <Tag color={r.is_copyright ? 'red' : undefined}>{r.reason_code} {r.reason_label}</Tag>
                {r.status === 'escalated' && <Tag color="error">已有 3 人举报</Tag>}
              </Space>
              {r.note && <Muted>{r.note}</Muted>}
            </Space>) },
          { title: '联系方式', width: 200, render: (_, r) => (r.contact
            ? <Typography.Text copyable style={{ fontSize: 12 }}>{r.contact}</Typography.Text>
            : <Muted>{r.is_copyright ? '(没留,按规则不该出现)' : '—'}</Muted>) },
          { title: '时间', width: 110, render: (_, r) => t(r.created_at) },
          { title: '状态', width: 120, render: (_, r) => (
            <Space direction="vertical" size={0}>
              <Tag color={STATUS_COLORS[r.status]}>{r.status}</Tag>
              {r.resolution && <Muted>{r.resolution}</Muted>}
            </Space>) },
          { title: '', width: 160, render: (_, r) => (
            ['open', 'escalated'].includes(r.status) ? (
              <Space>
                <Button size="small" onClick={() => handle(r, 'dismiss')}>不成立</Button>
                <Button size="small" danger onClick={() => handle(r, 'remove_target')}>处置</Button>
              </Space>
            ) : <Muted>已处理</Muted>) },
        ]} />
    </Card>
  )
}

const REMOVE_HINTS: Record<string, string> = {
  track: '举报的是一首歌:下架的是它所在的整个作品(审核单位是作品)。音乐人会收到通知,可以申诉。',
  release: '下架这个作品。音乐人会收到通知,可以申诉。',
  comment: '删除这条评论。',
  playlist: '歌单改成私密(不删 —— 是用户自己的东西),别人就看不到了。',
  artist: '停用这位音乐人:主页和全部作品从公开的地方消失,本人还能登录。',
}

function TargetCell({ r }: { r: MusicReportItem }) {
  const label = <Tag>{TARGET_LABELS[r.target_type]}</Tag>
  if (r.track) {
    return (
      <Space direction="vertical" size={0}>
        <Space>{label}<span>{r.track.title}</span></Space>
        <Muted>{r.track.tid} · {r.track.release?.title ?? '—'} · {r.track.artist?.name ?? '—'}</Muted>
      </Space>
    )
  }
  if (r.release) {
    return (
      <Space direction="vertical" size={0}>
        <Space>{label}<span>{r.release.title}</span></Space>
        <Muted>{r.release.rid} · {r.release.status} · {r.release.artist?.name ?? '—'}</Muted>
      </Space>
    )
  }
  if (r.comment) {
    return (
      <Space direction="vertical" size={0}>
        <Space>{label}<Muted>#{r.comment.id} · {r.comment.status}</Muted></Space>
        <Typography.Paragraph style={{ margin: 0 }} ellipsis={{ rows: 2 }}>{r.comment.text}</Typography.Paragraph>
      </Space>
    )
  }
  if (r.playlist) {
    return (
      <Space direction="vertical" size={0}>
        <Space>{label}<span>{r.playlist.title}</span></Space>
        <Muted>{r.playlist.pid} · {r.playlist.is_public ? '公开' : '私密'}</Muted>
      </Space>
    )
  }
  if (r.artist) {
    return (
      <Space direction="vertical" size={0}>
        <Space>{label}<span>{r.artist.name}</span></Space>
        <Muted>{r.artist.aid} · {r.artist.status}</Muted>
      </Space>
    )
  }
  return <Space>{label}<Muted>对象已不存在</Muted></Space>
}
