import { Alert, Button, Card, Input, Popconfirm, Space, Switch, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiError, CopyItem, getCopy, putCopy, resetCopy } from '../api'

/**
 * 文案:App 上每个可配置的位置都能**改字**,能藏的还能**显示 / 隐藏** —— 改一句话、藏一个入口都不用发版。
 *
 * 列的是服务端登记表(server/app/services/copy_registry.py)里的位置,没改过的也列(带默认值)。
 * 登记表之外的 key 在这里改不了:客户端不读的 key 改了也不会生效,只会让人以为改了。
 *
 * 什么时候生效:App 启动时拉一次配置,拉到就换(底部菜单当场变);已经装着的老版本 App
 * 如果还不认识某个位置,照旧显示写死在老版本里的字。
 */
export default function CopyPage() {
  const [items, setItems] = useState<CopyItem[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await getCopy())
      setErr('')
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const groups = useMemo(() => {
    const out: [string, CopyItem[]][] = []
    for (const it of items) {
      const g = out.find(([name]) => name === it.group)
      if (g) g[1].push(it)
      else out.push([it.group, [it]])
    }
    return out
  }, [items])

  async function run(key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(key)
    try {
      await fn()
      message.success(ok)
      setDrafts((d) => {
        const next = { ...d }
        delete next[key]
        return next
      })
      await load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  function card(it: CopyItem) {
    const current = it.text ?? ''
    const draft = drafts[it.key]
    const value = draft ?? current
    const changed = draft !== undefined && draft.trim() !== current
    const long = it.max_len > 20
    return (
      <Card key={it.key} size="small" loading={loading}>
        <Space align="start" style={{ width: '100%' }} wrap>
          <div style={{ minWidth: 220, flex: 1 }}>
            <div style={{ fontWeight: 600 }}>
              {it.where}
              {it.hidden && <Tag color="warning" style={{ marginLeft: 6 }}>已隐藏</Tag>}
              {it.text && !it.hidden && <Tag color="processing" style={{ marginLeft: 6 }}>改过</Tag>}
            </div>
            <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)', lineHeight: 1.6 }}>
              <Typography.Text code style={{ fontSize: 11 }}>{it.key}</Typography.Text>
              {it.locked ? ' 按平台配置的真实费率生成,这里改不了 —— 改费率,文案会自动跟着变'
                : !it.known ? ' 没有客户端读这个 key,改了也不会生效,删掉即可'
                  : <> 默认:<span style={{ whiteSpace: 'pre-wrap' }}>{it.default}</span>(最多 {it.max_len} 个字)</>}
            </div>
            {!it.locked && it.known && !it.hideable && it.hide_note && (
              <div style={{ fontSize: 12, color: 'var(--sz-ink-faint)', marginTop: 2 }}>
                显示 / 隐藏:{it.hide_note}
              </div>
            )}
          </div>
          {it.locked ? (
            <Typography.Text style={{ whiteSpace: 'pre-wrap', maxWidth: 360 }}>{it.text}</Typography.Text>
          ) : !it.known ? (
            <Popconfirm title="删掉这条老文案?" onConfirm={() => run(it.key, () => resetCopy(it.key), '已删除')}>
              <Button danger loading={busy === it.key}>删除</Button>
            </Popconfirm>
          ) : (
            <Space direction="vertical" size={6} style={{ minWidth: 280 }}>
              <Space.Compact style={{ width: '100%' }}>
                {long ? (
                  <Input.TextArea
                    autoSize={{ minRows: 2, maxRows: 5 }}
                    maxLength={it.max_len} showCount
                    value={value} placeholder={it.default}
                    onChange={(e) => setDrafts((d) => ({ ...d, [it.key]: e.target.value }))}
                  />
                ) : (
                  <Input
                    maxLength={it.max_len} showCount style={{ width: 200 }}
                    value={value} placeholder={it.default}
                    onChange={(e) => setDrafts((d) => ({ ...d, [it.key]: e.target.value }))}
                  />
                )}
              </Space.Compact>
              <Space wrap>
                <Button
                  type="primary" disabled={!changed || !value.trim()} loading={busy === it.key}
                  onClick={() => run(it.key, () => putCopy(it.key, { text: value.trim() }), '已保存,App 下次拉配置时换上')}
                >
                  保存
                </Button>
                {it.hideable && (
                  <span>
                    <Switch
                      checked={!it.hidden} loading={busy === it.key}
                      onChange={(show) => run(it.key, () => putCopy(it.key, { hidden: !show }),
                        show ? '已显示' : '已隐藏')}
                    />
                    <span style={{ marginLeft: 6, fontSize: 12 }}>{it.hidden ? '隐藏中' : '显示中'}</span>
                  </span>
                )}
                {(it.text || it.hidden) && (
                  <Popconfirm
                    title="恢复默认?"
                    description="字回到 App 自带的默认值,藏起来的也重新显示"
                    onConfirm={() => run(it.key, () => resetCopy(it.key), '已恢复默认')}
                  >
                    <Button loading={busy === it.key}>恢复默认</Button>
                  </Popconfirm>
                )}
              </Space>
            </Space>
          )}
        </Space>
      </Card>
    )
  }

  return (
    <>
      <Alert
        type="info" showIcon style={{ marginBottom: 12 }}
        message="改字、显示 / 隐藏都不用发版"
        description={'App 启动时拉一次配置,拉到就换(底部菜单当场变)。「首页」「我的」两格不能藏:'
          + '藏了用户就进不去设置、登录不了。首页业务入口的显示 / 隐藏在「平台开关」页。'}
      />
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {groups.map(([name, list]) => (
          <div key={name}>
            <Typography.Title level={5} style={{ marginBottom: 8 }}>{name}</Typography.Title>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {list.map(card)}
            </Space>
          </div>
        ))}
      </Space>
    </>
  )
}
