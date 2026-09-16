import { Alert, Button, Card, Input, Modal, Radio, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ForumTagItem, forumTags, hideForumTag, unhideForumTag } from '../../api_forum'
import { Muted, ReasonPicker, fail, reasonProblem, t } from './shared'

/**
 * 热门话题(DEV-PROMPTS-41 #380、§2.2)。
 *
 * **运营能隐藏一个话题,但要写原因、留痕**(进 forum_decisions),而且隐藏**只是不上热门榜** ——
 * 话题页照样能打开,里面的帖子照样在。这条是刻意的:不偷偷压话题。
 *
 * 热门榜怎么算是公开的(§5.7):近 24 小时用过这个话题的**人数** + 2 × 近 3 小时的人数,
 * 24 小时内至少 2 个人用过才上榜 —— 一个人自己刷不出热门话题。
 */
export default function ForumTagsPage() {
  const [filter, setFilter] = useState<'all' | 'hidden' | 'shown'>('all')
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<ForumTagItem[]>([])
  const [loading, setLoading] = useState(false)
  const [hiding, setHiding] = useState<ForumTagItem | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows((await forumTags({
        hidden: filter === 'all' ? undefined : filter === 'hidden',
        q: q.trim() || undefined,
      })).items)
    } catch (e) { fail(e) } finally { setLoading(false) }
  }, [filter, q])
  useEffect(() => { void load() }, [load])

  const unhide = async (t0: ForumTagItem) => {
    try {
      await unhideForumTag(t0.tag)
      message.success(`「${t0.display}」重新参与热门榜`)
      void load()
    } catch (e) { fail(e) }
  }

  return (
    <Card title="热门话题">
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
        message="隐藏只是不上热门榜"
        description={'话题页照样能打开、帖子照样在。隐藏必须写原因,每一次都记进 forum_decisions —— '
          + '热门榜的算法是公开的(近 24 小时用过的人数 + 2 × 近 3 小时的人数,至少 2 个人),'
          + '运营的每一次干预也要留得下痕迹。'} />
      <Space style={{ marginBottom: 12 }} wrap>
        <Radio.Group value={filter} onChange={(e) => setFilter(e.target.value)} optionType="button"
          options={[{ value: 'all', label: '全部' }, { value: 'shown', label: '正常' },
                    { value: 'hidden', label: '已隐藏' }]} />
        <Input.Search allowClear style={{ width: 240 }} placeholder="话题关键词"
                      defaultValue={q} onSearch={setQ} />
        <Button onClick={() => void load()}>刷新</Button>
      </Space>
      <Table<ForumTagItem> rowKey="tag" size="small" loading={loading} dataSource={rows}
        locale={{ emptyText: '还没有话题' }} pagination={{ pageSize: 30 }}
        columns={[
          { title: '话题', width: 220, render: (_, r) => (
            <Space direction="vertical" size={0}>
              <span>#{r.display}</span>
              {r.display !== r.tag && <Muted>规范化:{r.tag}</Muted>}
            </Space>) },
          { title: '帖子数', dataIndex: 'posts', width: 90 },
          { title: '状态', width: 200, render: (_, r) => (r.hidden
            ? <Space direction="vertical" size={0}>
                <Tag color="red">已隐藏</Tag>
                <Muted>{r.hidden_code} {r.hidden_label}</Muted>
              </Space>
            : <Tag color="green">正常</Tag>) },
          { title: '最近用过', width: 120, render: (_, r) => t(r.last_used_at) },
          { title: '', width: 120, fixed: 'right', render: (_, r) => (r.hidden
            ? <Button size="small" onClick={() => void unhide(r)}>取消隐藏</Button>
            : <Button size="small" danger onClick={() => setHiding(r)}>从热门榜移除</Button>) },
        ]} />
      {hiding && <HideModal tag={hiding} onClose={(changed) => {
        setHiding(null)
        if (changed) void load()
      }} />}
    </Card>
  )
}

function HideModal({ tag, onClose }: { tag: ForumTagItem; onClose: (changed: boolean) => void }) {
  const [code, setCode] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const problem = reasonProblem(code, note)

  const submit = async () => {
    setBusy(true)
    try {
      await hideForumTag(tag.tag, { reason_code: code, note })
      message.success(`「${tag.display}」不再上热门榜`)
      onClose(true)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  return (
    <Modal open title={`把 #${tag.display} 从热门榜移除`} onCancel={() => onClose(false)}
           okText="移除" okType="danger" onOk={submit} confirmLoading={busy}
           okButtonProps={{ disabled: !!problem }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <ReasonPicker code={code} note={note} onCode={setCode}>
          <Input.TextArea rows={3} maxLength={500} showCount value={note}
                          placeholder="为什么把它从热门榜上撤下来(会记进 forum_decisions)"
                          onChange={(e) => setNote(e.target.value)} />
        </ReasonPicker>
        <Muted>
          移除之后这个话题不再出现在热门榜上,但**话题页照样能打开、帖子照样在**。
          这一次操作会记进 forum_decisions,谁在什么时候用什么理由撤的都留得下。
        </Muted>
      </Space>
    </Modal>
  )
}
