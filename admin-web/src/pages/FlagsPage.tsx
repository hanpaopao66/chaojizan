import { Alert, Button, Card, Input, Modal, Space, Switch, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, Flags, getFlags, setFlag } from '../api'

/**
 * 平台开关。
 *
 * ## 这页是给"出事那天"用的
 *
 * 极端天气要停运、某个城市要临时关掉、酒类禁售时段要调 —— 这些是
 * **当天就得改**的东西,不能等发版。所以每个开关旁边写的不是字段名,
 * 是"打开会发生什么"。
 *
 * ## 为什么改动要填原因
 *
 * 白名单开关的变更会进透明中心的公开时间线(`FlagHistory`),
 * 原因会一起展示给用户看。空着也能改,但那条时间线上就只有
 * "某年某月某日,极端天气停运打开了" —— 用户不知道为什么。
 */

interface FlagMeta {
  key: string
  title: string
  /** 打开(或填上)之后会发生什么。写后果,不写字段含义 */
  effect: string
  kind: 'switch' | 'text'
  placeholder?: string
  danger?: boolean
}

const METAS: FlagMeta[] = [
  {
    key: 'weather_shutdown', title: '极端天气停运', kind: 'switch', danger: true,
    effect: '立刻停止接新单,已接的单兜底取消线缩短,三端挂横幅,在线骑手收到安全提醒',
  },
  {
    key: 'weather_surcharge', title: '恶劣天气配送加价', kind: 'switch',
    effect: '配送费上浮,加价部分全额归骑手,平台不抽',
  },
  {
    key: 'night_curfew', title: '深夜保护窗', kind: 'switch',
    effect: '窗口时段内停止接新单(保护骑手夜间安全)',
  },
  {
    key: 'night_curfew_hours', title: '保护窗时段', kind: 'text',
    placeholder: '01:00-06:00', effect: '留空按 01:00-06:00',
  },
  {
    key: 'alcohol_curfew', title: '酒类禁售时段', kind: 'switch',
    effect: '窗口时段内含酒订单直接拒单',
  },
  {
    key: 'alcohol_curfew_hours', title: '酒类禁售时段', kind: 'text',
    placeholder: '22:00-08:00', effect: '留空按 22:00-08:00',
  },
  {
    key: 'open_cities', title: '开城清单', kind: 'text', danger: true,
    placeholder: '成都,绵阳,德阳(留空 = 全部开放)',
    effect: '只有清单里的城市能营业。填错会让在营城市整个停摆',
  },
  {
    key: 'health_cert_cities', title: '要求健康证的城市', kind: 'text',
    placeholder: '留空 = 都不要求',
    effect: '国家层面不要求送餐员持健康证,只把查到本地条文的城市加进来',
  },
  {
    key: 'rider_training_grace_until', title: '食安培训宽限截止日', kind: 'text',
    placeholder: 'YYYY-MM-DD(留空 = 立即生效)',
    effect: '截止日之前未完成培训的存量骑手照常上线但带提醒;过期或写错都硬卡',
  },
  {
    key: 'marketing', title: '营销总开关', kind: 'switch',
    effect: '新客券、邀请、生日、复购、上新一起开关',
  },
  {
    key: 'screen_show_gmv', title: '公开大屏展示交易额', kind: 'switch',
    effect: '关掉后 /screen 接口不下发金额',
  },
]

export default function FlagsPage() {
  const [flags, setFlags] = useState<Flags>({})
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      const f = await getFlags()
      setFlags(f)
      setDrafts({})
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  /** 改一个开关。**一律先问原因** —— 它会进公开时间线 */
  function change(meta: FlagMeta, value: string) {
    let reason = ''
    Modal.confirm({
      title: `${meta.title}:${flags[meta.key] || '(空)'} → ${value || '(空)'}`,
      width: 520,
      content: (
        <>
          <Alert type={meta.danger ? 'error' : 'info'} showIcon
                 style={{ margin: '8px 0' }} message={meta.effect} />
          <Input.TextArea
            rows={2} maxLength={200}
            placeholder="改动原因(会进透明中心的公开时间线,用户看得到)"
            onChange={(e) => { reason = e.target.value }}
          />
        </>
      ),
      okText: '确认改',
      okButtonProps: { danger: meta.danger },
      cancelText: '取消',
      onOk: async () => {
        try {
          setFlags(await setFlag(meta.key, value, reason.trim()))
          setDrafts((d) => ({ ...d, [meta.key]: '' }))
          message.success('已生效')
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          throw e
        }
      },
    })
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {METAS.map((m) => {
          const cur = flags[m.key] ?? ''
          const draft = drafts[m.key]
          return (
            <Card key={m.key} size="small" loading={loading}>
              <Space align="start" style={{ width: '100%' }} wrap>
                <div style={{ minWidth: 200, flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>
                    {m.title}
                    {m.danger && <Tag color="error" style={{ marginLeft: 6 }}>影响大</Tag>}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)',
                                lineHeight: 1.6 }}>
                    {m.effect}
                  </div>
                </div>
                {m.kind === 'switch' ? (
                  <Switch
                    checked={cur === 'on'}
                    onChange={(v) => change(m, v ? 'on' : 'off')}
                  />
                ) : (
                  <Space.Compact>
                    <Input
                      style={{ width: 260 }}
                      value={draft ?? cur}
                      placeholder={m.placeholder}
                      onChange={(e) => setDrafts(
                        (d) => ({ ...d, [m.key]: e.target.value }))}
                    />
                    <Button
                      type="primary"
                      disabled={draft === undefined || draft === cur}
                      onClick={() => change(m, (draft ?? cur).trim())}
                    >
                      保存
                    </Button>
                  </Space.Compact>
                )}
              </Space>
            </Card>
          )
        })}
      </Space>
    </>
  )
}
