import { Alert, Button, Card, Input, Modal, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { MusicArtistRow, musicArtists, restoreArtist, suspendArtist } from '../../api_music'
import { Muted, PersonName, fail, t } from '../community/shared'
import { ARTIST_STATUS_LABELS } from './shared'

/**
 * 音乐人(DEV-PROMPTS-41 M2)。
 *
 * 开通不要求实名、不审主页 —— 冒充走举报(M305)。这里能做的只有两件事:
 * **停用**(主页和全部作品从公开的地方消失,本人还能登录、还能申诉、数据还在)和**恢复**。
 * 没有「删号」:那是用户自己在客户端注销的事,平台不替他决定。
 */
export default function MusicArtistsPage() {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<MusicArtistRow[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (keyword = q) => {
    setLoading(true)
    try { setRows((await musicArtists(keyword)).items) } catch (e) { fail(e) } finally { setLoading(false) }
  }, [q])
  useEffect(() => { void load('') }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  function suspend(a: MusicArtistRow) {
    let note = ''
    Modal.confirm({
      title: `停用音乐人:${a.name}`,
      content: (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert type="warning" showIcon
                 message="停用后他的主页和全部作品对外消失,也不能再发新作品;本人还能登录,数据都在。" />
          <Input.TextArea rows={2} maxLength={500} placeholder="留痕用的说明(会进操作留痕)"
                          onChange={(e) => { note = e.target.value }} />
        </Space>),
      okButtonProps: { danger: true },
      onOk: async () => {
        try { await suspendArtist(a.aid, note); message.success('已停用'); await load() } catch (e) { fail(e); throw e }
      },
    })
  }

  async function restore(a: MusicArtistRow) {
    try { await restoreArtist(a.aid); message.success('已恢复'); await load() } catch (e) { fail(e) }
  }

  return (
    <Card title="音乐人" extra={
      <Space>
        <Input.Search allowClear placeholder="按艺名搜" style={{ width: 220 }} value={q}
                      onChange={(e) => setQ(e.target.value)} onSearch={(v) => void load(v)} />
      </Space>
    }>
      <Table<MusicArtistRow> rowKey="aid" size="small" loading={loading} dataSource={rows}
        locale={{ emptyText: '没有音乐人' }} pagination={{ pageSize: 20 }} scroll={{ x: 900 }}
        columns={[
          { title: '艺名', render: (_, r) => (
            <Space>
              {r.avatar && <img src={r.avatar} alt="" style={{ width: 32, height: 32, borderRadius: '50%', objectFit: 'cover' }} />}
              <Space direction="vertical" size={0}>
                <span>{r.name}</span>
                <Muted>{r.aid}</Muted>
              </Space>
            </Space>) },
          { title: '账号', width: 200, render: (_, r) => <PersonName p={r.user} /> },
          { title: '曲风', width: 160, render: (_, r) => (r.genres || []).map((g) => <Tag key={g}>{g}</Tag>) },
          { title: '作品', width: 100, render: (_, r) => `${r.track_count} 首` },
          { title: '粉丝', width: 90, render: (_, r) => r.fans },
          { title: '开通于', width: 110, render: (_, r) => t(r.created_at) },
          { title: '状态', width: 100, render: (_, r) => (
            <Tag color={r.status === 'active' ? 'green' : r.status === 'suspended' ? 'red' : undefined}>
              {ARTIST_STATUS_LABELS[r.status] ?? r.status}
            </Tag>) },
          { title: '', width: 100, render: (_, r) => (r.status === 'suspended'
            ? <Button size="small" onClick={() => void restore(r)}>恢复</Button>
            : <Button size="small" danger onClick={() => suspend(r)}>停用</Button>) },
        ]} />
    </Card>
  )
}
