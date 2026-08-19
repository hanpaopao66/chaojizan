import { Alert, Button, Card, Col, Image, Input, Popconfirm, Row, Select, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  addModerationWord, ApiError, approveContent, ContentReview, delModerationWord,
  listContentReviews, listModerationWords, ModerationWord, rejectContent,
} from '../api'

/** 内容审核:待审图片 + 敏感词表。两件事都在这一页,因为它们服务同一个目的。 */
export default function ModerationPage() {
  const [reviews, setReviews] = useState<ContentReview[]>([])
  const [words, setWords] = useState<ModerationWord[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [word, setWord] = useState('')
  const [cat, setCat] = useState('other')

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try {
      const [r, w] = await Promise.all([listContentReviews(), listModerationWords()])
      setReviews(r); setWords(w)
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, ok: string) {
    try { await fn(); message.success(ok); await load() }
    catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={14}>
          <Card size="small" title={`待审内容 ${reviews.length}`} loading={loading}>
            {reviews.length === 0 ? (
              <span style={{ color: 'var(--sz-ink-muted)' }}>没有待审的内容</span>
            ) : (
              <Space wrap size={12}>
                {reviews.map((r) => (
                  <div key={r.id} style={{
                    border: '1px solid var(--sz-line)', borderRadius: 8, padding: 8,
                    width: 160, textAlign: 'center',
                  }}>
                    <Image src={r.url} width={140} height={110}
                           style={{ objectFit: 'cover' }} />
                    <div style={{ fontSize: 11, color: 'var(--sz-ink-muted)',
                                  margin: '4px 0' }}>
                      {r.kind} · {r.created_at?.slice(5, 16).replace('T', ' ')}
                    </div>
                    <Space size={4}>
                      <Button size="small" type="primary"
                              onClick={() => act(() => approveContent(r.id), '已通过')}>
                        通过
                      </Button>
                      <Button size="small" danger
                              onClick={() => act(() => rejectContent(r.id), '已驳回')}>
                        驳回
                      </Button>
                    </Space>
                  </div>
                ))}
              </Space>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card size="small" title={`敏感词 ${words.length}`} loading={loading}>
            <Space.Compact style={{ width: '100%', marginBottom: 10 }}>
              <Input value={word} placeholder="新增敏感词" maxLength={30}
                     onChange={(e) => setWord(e.target.value)} />
              <Select value={cat} onChange={setCat} style={{ width: 110 }}
                      options={[
                        { value: 'porn', label: '色情' },
                        { value: 'politics', label: '政治' },
                        { value: 'ad', label: '广告' },
                        { value: 'abuse', label: '辱骂' },
                        { value: 'other', label: '其他' },
                      ]} />
              <Button type="primary" disabled={!word.trim()}
                      onClick={() => act(async () => {
                        await addModerationWord(word.trim(), cat)
                        setWord('')
                      }, '已加入')}>
                加
              </Button>
            </Space.Compact>
            <Table<ModerationWord>
              rowKey="id" dataSource={words} size="small"
              pagination={{ pageSize: 10, showSizeChanger: false }}
              columns={[
                { title: '词', dataIndex: 'word' },
                { title: '分类', dataIndex: 'category', width: 80,
                  render: (v: string) => <Tag>{v}</Tag> },
                { title: '', width: 50,
                  render: (_, w) => (
                    <Popconfirm title="删掉这个词?"
                                onConfirm={() => act(() => delModerationWord(w.id), '已删')}>
                      <Button type="link" size="small" danger>删</Button>
                    </Popconfirm>
                  ) },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </>
  )
}
