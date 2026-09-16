import { Alert, Button, Card, Input, Modal, Space, Switch, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, CitiesOut, Flags, getCities, getFlags, setFlag } from '../api'

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
  kind: 'switch' | 'text' | 'channels'
  placeholder?: string
  danger?: boolean
  /** 密钥类:后端只回「set / 空」,不回明文。输入框留空 = 不改,填了才覆盖 */
  secret?: boolean
}

/** 频道注册表 —— 和 packages/shared/lib/src/channels.dart 的 kChannels 对应。
 *
 * 这里只列 key 和名字,**不复制那边的色板和副标题** —— 抄一份就会有一天
 * 后台写的名字和用户看到的对不上。要加频道时两边都要加,而两边都加
 * 好过一边悄悄漂移。 */
const CHANNELS: { key: string; name: string }[] = [
  { key: 'food', name: '点外卖' },
  { key: 'retail', name: '买菜买水果' },
  { key: 'stay', name: '住宿' },
  { key: 'voucher', name: '超值团购' },
  { key: 'errand', name: '帮我送(跑腿)' },
  { key: 'music', name: '音乐' },
  { key: 'forum', name: '论坛' },
]

const METAS: FlagMeta[] = [
  {
    key: 'channels_enabled', title: '首页显示哪些业务', kind: 'channels',
    danger: true,
    effect: '用户端首页金刚区只显示勾上的;去掉的业务用户进不去(服务端接口仍在,'
      + '已有订单不受影响)。改完立即生效,不用发版',
  },
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
  // 小程序急停闸(缺省开):出了问题先拉这里,再查原因。语义见 services/miniapp_platform.py 的 SWITCHES
  {
    key: 'miniapp_hosted', title: '托管小程序', kind: 'switch', danger: true,
    effect: '关掉后所有托管小程序立刻打不开(已开着的一分钟内被宿主关掉),托管文件一律 404,'
      + '目录里消失;透明中心、公开账本这类外部地址条目不受影响',
  },
  {
    key: 'miniapp_catalog', title: '小程序目录(第三方应用)', kind: 'switch',
    effect: '关掉后公开目录和 App 的「全部小程序」只列官方小程序;第三方应用只能从直达链接和用户自己的「最近使用」进',
  },
  {
    key: 'miniapp_profile', title: '小程序读取昵称头像', kind: 'switch',
    effect: '关掉后所有小程序的 profile 能力当场收回,requestProfile 一律回 4001(用户已给过的授权记录保留)',
  },
  // 消息与视频的闸(docs/LAUNCH-40.md 第 1 节):没写过时生产缺省是「消息开,其余关」。
  // 服务端每次现查、不缓存,拨了立刻生效;/config 同时告诉客户端收起对应入口
  {
    key: 'chat_enabled', title: '消息', kind: 'switch', danger: true,
    effect: '关掉后整个「消息」(私聊、群、频道、贴纸、通话记录)停用,接口回「消息功能暂停中」;'
      + '订单群和订单通知不受影响。出事时的急停用',
  },
  {
    key: 'video_enabled', title: '视频功能', kind: 'switch', danger: true,
    effect: '打开后用户端「视频」页签可以看、搜、评论、弹幕;关掉后整个视频接口回「视频功能暂未开放」。'
      + '需要《信息网络传播视听节目许可证》',
  },
  {
    key: 'video_upload_enabled', title: '视频投稿', kind: 'switch', danger: true,
    effect: '打开后实名用户可以投稿(建稿、传原片、提交审核);要视频功能也开着才生效。'
      + '打开前先确认对象存储的容量和审核人手(上线手册第 6 节)',
  },
  {
    key: 'calls_enabled', title: '语音 / 视频通话', kind: 'switch', danger: true,
    effect: '打开后消息里可以打语音、视频电话;关掉后呼叫直接回「通话功能暂未开放」。'
      + '打开前要部署好 coturn(上线手册第 5 节)',
  },
  {
    key: 'av_license_no', title: '视听许可证编号', kind: 'text',
    placeholder: '《信息网络传播视听节目许可证》编号(留空 = 不显示)',
    effect: '填上后官网每一页页脚、用户端「关于我们」照原样公示这个编号(开视频要公示);换证时在这里改,不用发版',
  },
  {
    key: 'bots_enabled', title: '机器人', kind: 'switch', danger: true,
    effect: '打开后开发者可以建机器人、用 Bot API;关掉后 Bot API 全部停用、webhook 暂停、不能建新机器人',
  },
  // 音乐与论坛(DEV-PROMPTS-41):服务端早就认这四个键,这一页却一直没列 ——
  // 于是只能拿 curl 拨。合规清单第 17、18 条的结论还没回来,拨之前先看一眼那两条
  {
    key: 'music_enabled', title: '音乐', kind: 'switch', danger: true,
    effect: '打开后用户端能进音乐:听歌、歌单、榜单、评论;关掉后 /music/v1 全部回「音乐暂未开放」。'
      + '金刚区要不要有这一格,另看上面「首页显示哪些业务」有没有勾「音乐」',
  },
  {
    key: 'music_upload_enabled', title: '音乐投稿', kind: 'switch', danger: true,
    effect: '打开后用户可以开通音乐人、建作品、传音频、提交审核;要音乐功能也开着才生效。'
      + '只收原创或已获授权的作品、先审后发 —— 打开前先确认审核人手(合规清单第 17 条)',
  },
  {
    key: 'forum_enabled', title: '论坛', kind: 'switch', danger: true,
    effect: '打开后用户端能进论坛:看帖、话题、搜索、投票;关掉后 /forum/v1 全部回「论坛暂未开放」。'
      + '金刚区那一格同样看「首页显示哪些业务」里有没有勾「论坛」',
  },
  {
    key: 'forum_post_enabled', title: '论坛发帖', kind: 'switch', danger: true,
    effect: '关掉是「停笔不关站」:发帖、回复、引用、编辑回 503,看还是能看。'
      + '出事时先拨这一个,不必把整个论坛关掉',
  },
  // AI 机器人(#385、#386)。**平台不做大模型级别的机器人** —— 所有接入都是用户级别的,
  // 模型地址和密钥跟着每个机器人自己走(「AI 机器人」那一页),不在这里。
  // 这几项管的是**秩序**:多少人能建、能占多少地方、一条帖下面能站几个
  {
    key: 'ai_bots_enabled', title: 'AI 机器人', kind: 'switch', danger: true,
    effect: '总闸。关着时所有 AI 号一个字都不发。'
      + '每个机器人用的是**它主人自己的模型**,平台不出算力也不存模型',
  },
  {
    key: 'ai_bots_per_user', title: '每人最多几个机器人', kind: 'text', placeholder: '20',
    effect: '超过就建不了新的。已经建好的不受影响 —— 调小是拦住新增,不是把现有的关掉',
  },
  {
    key: 'ai_timeline_share', title: '机器人内容占公共时间线的上限(%)', kind: 'text',
    placeholder: '80', danger: true,
    effect: '超过这个比例就不再往公共时间线里放机器人的帖。'
      + '**这个数是整页最该盯着调的** —— 满屏机器人比空着更糟:'
      + '空着是「还没人来」,机器人互相寒暄是「这地方是假的」',
  },
  {
    key: 'ai_replies_per_post', title: '一条帖下面最多几个机器人', kind: 'text',
    placeholder: '100',
    effect: '站满了就不再有机器人来回这一条。防的是一条真人帖底下排一长队机器人',
  },
  {
    key: 'ai_posts_per_day_max', title: '单个机器人每天最多发几条', kind: 'text',
    placeholder: '48',
    effect: '主人在这个数以内自己填。调小之后,已有的机器人下次保存时会被夹到这个数',
  },
  {
    key: 'ai_replies_per_day_max', title: '单个机器人每天最多回几条', kind: 'text',
    placeholder: '96',
    effect: '同上。回帖是让社区显得有人的那部分,所以给得比发帖宽',
  },
]

export default function FlagsPage() {
  const [flags, setFlags] = useState<Flags>({})
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [cities, setCities] = useState<CitiesOut | null>(null)
  const load = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      const [f, c] = await Promise.all([getFlags(), getCities()])
      setFlags(f)
      // 开城清单手敲一个字错了整城停摆,所以把「有商家的城市」列出来对照
      setCities(c)
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
          // **合并,不是替换。** 服务端回的是完整的一份,但这里仍然写成合并:
          // 万一哪天它又只回改动的那一个键(2026-09-16 之前就是),
          // 替换会让另外三十个开关在页面上当场全变成「关」——
          // 库里其实一个都没动,而看见的人不知道,他会挨个去「修」,
          // 每一下都是真写入、还会进透明中心的公开时间线
          const got = await setFlag(meta.key, value, reason.trim())
          setFlags((f) => ({ ...f, ...got }))
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
                  {m.key === 'open_cities' && cities && (
                    <div style={{ fontSize: 12, marginTop: 4 }}>
                      <span style={{ color: 'var(--sz-ink-muted)' }}>有商家的城市:</span>
                      {cities.cities.map((c) => (
                        <Tag key={c.city} style={{ cursor: 'pointer', marginTop: 2 }}
                             onClick={() => setDrafts((d) => {
                               const cur = (d[m.key] ?? flags[m.key] ?? '')
                                 .split(',').map((x) => x.trim()).filter(Boolean)
                               if (cur.includes(c.city)) return d
                               return { ...d, [m.key]: [...cur, c.city].join(',') }
                             })}>
                          {c.city} {c.merchants}
                        </Tag>
                      ))}
                    </div>
                  )}
                </div>
                {m.kind === 'channels' ? (
                  // **勾选,不让人手打 key。** 打错一个字的后果是那个频道
                  // 从首页消失,而后台显示得好好的 —— 这种错没人查得出来
                  <Space wrap>
                    {CHANNELS.map((c) => {
                      const on = cur.split(',').includes(c.key)
                      return (
                        <Tag.CheckableTag
                          key={c.key}
                          checked={on}
                          onChange={(next) => {
                            const set = new Set(
                              cur.split(',').filter(Boolean))
                            next ? set.add(c.key) : set.delete(c.key)
                            // 按注册顺序输出,不按点击顺序 ——
                            // 否则每次改动都产生一条"看起来变了"的留痕
                            change(m, CHANNELS.filter((x) => set.has(x.key))
                              .map((x) => x.key).join(','))
                          }}
                        >
                          {c.name}
                        </Tag.CheckableTag>
                      )
                    })}
                  </Space>
                ) : m.kind === 'switch' ? (
                  <Switch
                    checked={cur === 'on'}
                    onChange={(v) => change(m, v ? 'on' : 'off')}
                  />
                ) : (
                  <Space.Compact>
                    {/* 密钥类:后端只回 'set'/'',所以输入框**不回填**当前值 ——
                        回填的话会把一串假值当成真密钥再存一次。留空 = 不改 */}
                    <Input
                      style={{ width: 260 }}
                      value={m.secret ? (draft ?? '') : (draft ?? cur)}
                      placeholder={m.secret && cur === 'set'
                        ? '已设置(留空 = 不改)'
                        : m.placeholder}
                      onChange={(e) => setDrafts(
                        (d) => ({ ...d, [m.key]: e.target.value }))}
                    />
                    <Button
                      type="primary"
                      disabled={m.secret
                        ? !draft
                        : draft === undefined || draft === cur}
                      onClick={() => change(m, m.secret
                        ? (draft ?? '')
                        : (draft ?? cur).trim())}
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
