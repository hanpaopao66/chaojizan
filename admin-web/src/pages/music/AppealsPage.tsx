import { Alert, Button, Card, Input, List, Modal, Space, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { MusicAppealItem, musicAppeals, resolveMusicAppeal } from '../../api_music'
import { Muted, fail, t } from '../community/shared'
import { ReviewDrawer } from './ReviewPage'
import { RELEASE_STATUS_COLORS } from './shared'

/**
 * 音乐申诉(DEV-PROMPTS-41 §5.3)。
 *
 * **必须换人**:原结论是你作出的,这里不给按钮(接口也会 403)——
 * 自己复核自己等于没有申诉。每个驳回 / 下架只能申诉一次。
 * 改判 = 真的改:作品立刻上线、封面回到公开桶,音乐人收到「申诉结果」。
 *
 * 判之前先听歌:每条申诉旁边的「看作品」直接打开审核抽屉,里面每首歌都能播。
 */
export default function MusicAppealsPage() {
  const [rows, setRows] = useState<MusicAppealItem[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { setRows((await musicAppeals()).items) } catch (e) { fail(e) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  function ask(a: MusicAppealItem, overturn: boolean) {
    let note = ''
    Modal.confirm({
      title: overturn ? `改判:${a.release.title}` : `维持原结论:${a.release.title}`,
      width: 560,
      content: (
        <Space direction="vertical" style={{ width: '100%' }}>
          {overturn && <Alert type="warning" showIcon
                              message="改判后作品立刻上线、封面回到公开桶,音乐人收到通知。" />}
          <Input.TextArea rows={3} maxLength={500}
                          placeholder="复核结论(给音乐人看,必填,至少 2 个字)"
                          onChange={(e) => { note = e.target.value }} />
        </Space>),
      okButtonProps: { danger: overturn },
      onOk: async () => {
        try {
          await resolveMusicAppeal(a.decision_id, { result: overturn ? 'overturned' : 'upheld', note })
          message.success(overturn ? '已改判' : '已维持原结论')
          await load()
        } catch (e) { fail(e); throw e }
      },
    })
  }

  return (
    <Card title="音乐申诉" loading={loading}>
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
             message="申诉必须由另一名审核员处理:你自己作出的结论,这里没有处理按钮,接口也会拒绝。" />
      <List dataSource={rows} locale={{ emptyText: '没有待处理的申诉' }} renderItem={(a) => (
        <List.Item actions={a.you_decided_original
          ? [<Tag key="self" color="default">你作出的结论,换人处理</Tag>]
          : [
            <Button key="v" size="small" onClick={() => setOpen(a.release.rid)}>看作品</Button>,
            <Button key="u" size="small" onClick={() => ask(a, false)}>维持</Button>,
            <Button key="o" size="small" danger onClick={() => ask(a, true)}>改判上线</Button>,
          ]}>
          <List.Item.Meta
            avatar={a.release.cover
              ? <img src={a.release.cover} alt="" style={{ width: 56, height: 56, objectFit: 'cover', borderRadius: 4 }} />
              : undefined}
            title={<Space wrap>
              <span>{a.release.title}</span>
              <Muted>{a.release.rid}</Muted>
              <Tag color={RELEASE_STATUS_COLORS[a.release.status]}>{a.release.status}</Tag>
              {a.artist && <Muted>{a.artist.name}</Muted>}
            </Space>}
            description={
              <Space direction="vertical" size={2} style={{ width: '100%' }}>
                <Muted>
                  原结论({t(a.original.created_at)}):
                  {a.original.action === 'reject' ? '驳回' : '平台下架'}
                  {a.original.reason_code && ` · ${a.original.reason_code} ${a.original.reason_label}`}
                  {a.original.note && ` · ${a.original.note}`}
                </Muted>
                <Typography.Paragraph style={{ margin: 0 }}>
                  申诉({t(a.appeal.at)}):{a.appeal.text}
                </Typography.Paragraph>
              </Space>}
          />
        </List.Item>
      )} />
      {open && <ReviewDrawer rid={open} onClose={() => setOpen(null)}
                             onDone={() => { setOpen(null); void load() }} />}
    </Card>
  )
}
