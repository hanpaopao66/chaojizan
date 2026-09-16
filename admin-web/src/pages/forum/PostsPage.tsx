import { Button, Card, Input, Modal, Radio, Space, Statistic, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ForumPostBrief, ForumStats, forumPosts, forumStats, removeForumPost, restoreForumPost,
} from '../../api_forum'
import { Muted, PostCell, ReasonPicker, fail, reasonProblem, t } from './shared'

/**
 * 帖子管理(巡查用,DEV-PROMPTS-41 #380)。
 *
 * 按正文关键词、作者、状态找帖子;**下架了的、作者自己删了的也找得到** —— 处理申诉、
 * 回查一条投诉的时候要看得到原文。下架要带 §5.11 的原因代码,作者收到通知并可申诉一次。
 */
export default function ForumPostsPage() {
  const [q, setQ] = useState('')
  const [author, setAuthor] = useState('')
  const [status, setStatus] = useState<'all' | 'visible' | 'removed' | 'deleted'>('all')
  const [rows, setRows] = useState<ForumPostBrief[]>([])
  const [stats, setStats] = useState<ForumStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [removing, setRemoving] = useState<ForumPostBrief | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const aid = Number(author)
      setRows((await forumPosts({
        q: q.trim() || undefined,
        author: author.trim() && Number.isFinite(aid) ? aid : undefined,
        status,
      })).items)
    } catch (e) { fail(e) } finally { setLoading(false) }
  }, [q, author, status])

  useEffect(() => { void load() }, [load])
  useEffect(() => { forumStats().then(setStats).catch(fail) }, [])

  const restore = async (p: ForumPostBrief) => {
    try {
      await restoreForumPost(p.pid, '运营复核后恢复')
      message.success('已恢复')
      void load()
    } catch (e) { fail(e) }
  }

  return (
    <Card title="帖子管理">
      {stats && (
        <Space size={32} wrap style={{ marginBottom: 16 }}>
          <Statistic title="近 7 天发帖" value={stats.posts_7d} />
          <Statistic title="近 7 天下架" value={stats.removed_7d} />
          <Statistic title="在架帖子" value={stats.visible_total} />
          <Statistic title="待处理举报" value={stats.reports_open} />
          <Statistic title="待复核申诉" value={stats.appeals_open} />
          <Statistic title="已隐藏话题" value={`${stats.tags_hidden} / ${stats.tags_total}`} />
        </Space>
      )}
      <Space style={{ marginBottom: 12 }} wrap>
        <Input.Search allowClear style={{ width: 260 }} placeholder="正文里的关键词"
                      defaultValue={q} onSearch={setQ} />
        <Input allowClear style={{ width: 160 }} placeholder="作者用户 id" value={author}
               onChange={(e) => setAuthor(e.target.value)} onPressEnter={() => void load()} />
        <Radio.Group value={status} onChange={(e) => setStatus(e.target.value)} optionType="button"
          options={[{ value: 'all', label: '全部' }, { value: 'visible', label: '正常' },
                    { value: 'removed', label: '已下架' }, { value: 'deleted', label: '作者已删' }]} />
        <Button onClick={() => void load()}>刷新</Button>
        <Muted>下架了的、作者自己删了的也找得到 —— 回查投诉要看得到原文</Muted>
      </Space>
      <Table<ForumPostBrief> rowKey="pid" size="small" loading={loading} dataSource={rows}
        locale={{ emptyText: '没有帖子' }} pagination={{ pageSize: 20 }} scroll={{ x: 1000 }}
        columns={[
          { title: '帖子', width: 460, render: (_, p) => <PostCell p={p} /> },
          { title: '待处理举报', width: 100, render: (_, p) => (p.reports_open
            ? <Tag color="error">{p.reports_open}</Tag> : <Muted>0</Muted>) },
          { title: '发布', width: 110, render: (_, p) => t(p.created_at) },
          { title: '', width: 110, fixed: 'right', render: (_, p) => (
            p.status === 'visible' ? <Button size="small" danger onClick={() => setRemoving(p)}>下架</Button>
              : p.status === 'removed' ? <Button size="small" onClick={() => void restore(p)}>恢复</Button>
                : <Muted>作者已删</Muted>) },
        ]} />
      {removing && <RemoveModal post={removing} onClose={(changed) => {
        setRemoving(null)
        if (changed) void load()
      }} />}
    </Card>
  )
}

function RemoveModal({ post, onClose }: { post: ForumPostBrief; onClose: (changed: boolean) => void }) {
  const [code, setCode] = useState('')
  const [note, setNote] = useState('')
  const [internal, setInternal] = useState('')
  const [busy, setBusy] = useState(false)
  const problem = reasonProblem(code, note)

  const submit = async () => {
    setBusy(true)
    try {
      await removeForumPost(post.pid, { reason_code: code, note, note_internal: internal || undefined })
      message.success('已下架,作者收到了通知')
      onClose(true)
    } catch (e) { fail(e) } finally { setBusy(false) }
  }

  return (
    <Modal open title={`下架 ${post.pid}`} onCancel={() => onClose(false)} okText="下架" okType="danger"
           onOk={submit} confirmLoading={busy} okButtonProps={{ disabled: !!problem }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <PostCell p={post} />
        <ReasonPicker code={code} note={note} onCode={setCode}>
          <Input.TextArea rows={2} maxLength={500} showCount value={note}
                          placeholder="给作者看的说明(系统通知、申诉页里都有)"
                          onChange={(e) => setNote(e.target.value)} />
        </ReasonPicker>
        <Input.TextArea rows={2} maxLength={500} value={internal}
                        placeholder="内部备注(只在后台看得到)"
                        onChange={(e) => setInternal(e.target.value)} />
        <Muted>作者会收到系统通知并知道原因,可以申诉一次;申诉由另一名审核员处理。</Muted>
      </Space>
    </Modal>
  )
}
