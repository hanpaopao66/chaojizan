import {
  Alert, Button, Card, Form, InputNumber, Input, Select, Space, Statistic,
  Switch, Table, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, GiftRule, MarketingStats, Merchant, PromoRule, ShopCouponBatch,
  createShopCouponBatch, Dish, marketingStats, myDishes, myShop,
  shopCouponBatches, toggleShopCouponBatch, updateShop, yuan,
} from '../../api'

/** 店内营销:满减(动钱)/满赠(动货)/店铺券。成本 100% 商家承担,
 *  平台按券后实收计佣——你让利,平台跟着少收。 */
export default function MarketingPage() {
  const [shop, setShop] = useState<Merchant | null>(null)
  const [promoRules, setPromoRules] = useState<PromoRule[]>([])
  const [giftRules, setGiftRules] = useState<GiftRule[]>([])
  const [dishes, setDishes] = useState<Dish[]>([])
  const [batches, setBatches] = useState<ShopCouponBatch[]>([])

  const load = useCallback(async () => {
    try {
      const [s, d, b] = await Promise.all([
        myShop(), myDishes(), shopCouponBatches(),
      ])
      setShop(s)
      setPromoRules((s as unknown as { promo_rules: PromoRule[] }).promo_rules ?? [])
      setGiftRules((s as unknown as { gift_rules: GiftRule[] }).gift_rules ?? [])
      setDishes(d.filter((x) => x.is_on_sale))
      setBatches(b)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function savePromo(rules: PromoRule[]) {
    try {
      await updateShop({ promo_rules: rules })
      message.success('满减已保存')
      load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  async function saveGifts(rules: GiftRule[]) {
    try {
      await updateShop({ gift_rules: rules })
      message.success('满赠已保存')
      load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  if (!shop) return null

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Alert
        type="info"
        showIcon
        message="满减/满赠/店铺券成本都由你承担;你让利,平台按折后实收计佣,跟着少收。"
      />
      <EffectCard />

      <Card size="small" title="满减活动(最多 3 档,动钱)">
        <RuleEditor
          rules={promoRules}
          max={3}
          onSave={savePromo}
          render={(rule, update) => (
            <>
              满 <InputNumber min={1} value={rule.threshold_cents / 100}
                onChange={(v) => update({ ...rule, threshold_cents: Math.round((v ?? 0) * 100) })} /> 元
              减 <InputNumber min={1} value={rule.off_cents / 100}
                onChange={(v) => update({ ...rule, off_cents: Math.round((v ?? 0) * 100) })} /> 元
            </>
          )}
          blank={{ threshold_cents: 3000, off_cents: 500 }}
        />
      </Card>

      <Card size="small" title="满赠活动(最多 2 档,动货:赠品以 0 元行进订单)">
        <RuleEditor
          rules={giftRules}
          max={2}
          onSave={saveGifts}
          render={(rule, update) => (
            <>
              满 <InputNumber min={1} value={rule.threshold_cents / 100}
                onChange={(v) => update({ ...rule, threshold_cents: Math.round((v ?? 0) * 100) })} /> 元
              赠 <select
                value={rule.dish_id}
                style={{ padding: 4 }}
                onChange={(e) => {
                  const dish = dishes.find((d) => d.id === Number(e.target.value))
                  update({
                    ...rule,
                    dish_id: Number(e.target.value),
                    name: dish?.name ?? '',
                  })
                }}
              >
                <option value={0}>选赠品菜</option>
                {dishes.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </>
          )}
          blank={{ threshold_cents: 3000, dish_id: 0, name: '' }}
        />
      </Card>

      <Card size="small" title="店铺券(用户在你的店铺页领取,下单自动可用)">
        <CouponCreator onCreated={load} />
        <Table<ShopCouponBatch>
          rowKey="id"
          dataSource={batches}
          pagination={false}
          size="small"
          columns={[
            { title: '名称', dataIndex: 'name' },
            {
              title: '规则',
              render: (_, b) => b.threshold_cents > 0
                ? `满 ${yuan(b.threshold_cents)} 减 ${yuan(b.off_cents)}`
                : `无门槛减 ${yuan(b.off_cents)}`,
            },
            { title: '已领/总量', render: (_, b) => `${b.issued}/${b.total}` },
            { title: '每人限领', dataIndex: 'per_user_limit' },
            { title: '有效期', dataIndex: 'valid_days', render: (v: number) => `${v} 天` },
            {
              title: '发放中',
              dataIndex: 'active',
              render: (v: boolean, b) => (
                <Switch checked={v} onChange={async () => {
                  try {
                    await toggleShopCouponBatch(b.id)
                    load()
                  } catch (e) {
                    message.error(e instanceof ApiError ? e.message : String(e))
                  }
                }} />
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )
}

function RuleEditor<T>({ rules, max, onSave, render, blank }: {
  rules: T[]
  max: number
  onSave: (rules: T[]) => void
  render: (rule: T, update: (next: T) => void) => React.ReactNode
  blank: T
}) {
  const [draft, setDraft] = useState<T[] | null>(null)
  const current = draft ?? rules

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      {current.map((rule, i) => (
        <Space key={i} wrap>
          {render(rule, (next) => {
            const list = [...current]
            list[i] = next
            setDraft(list)
          })}
          <Button size="small" danger
            onClick={() => setDraft(current.filter((_, x) => x !== i))}>
            删除
          </Button>
        </Space>
      ))}
      <Space>
        <Button size="small" disabled={current.length >= max}
          onClick={() => setDraft([...current, blank])}>
          + 加一档
        </Button>
        {draft != null && (
          <Button size="small" type="primary" onClick={() => {
            onSave(draft)
            setDraft(null)
          }}>
            保存
          </Button>
        )}
      </Space>
    </Space>
  )
}

function CouponCreator({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState('')
  const [threshold, setThreshold] = useState<number | null>(30)
  const [off, setOff] = useState<number | null>(5)
  const [total, setTotal] = useState<number | null>(100)
  const [perUser, setPerUser] = useState<number | null>(1)
  const [validDays, setValidDays] = useState<number | null>(7)
  const [trigger, setTrigger] = useState('shop')
  const [busy, setBusy] = useState(false)

  async function create() {
    if (!name.trim() || !off || !total) {
      return message.warning('请填写券名、减额与总量')
    }
    setBusy(true)
    try {
      await createShopCouponBatch({
        name: name.trim(),
        trigger,
        threshold_cents: Math.round((threshold ?? 0) * 100),
        off_cents: Math.round(off * 100),
        total,
        per_user_limit: perUser ?? 1,
        valid_days: validDays ?? 7,
      })
      message.success(trigger === 'favorite'
        ? '收藏有礼已开启:顾客收藏你的店就自动发这张券'
        : '店铺券已创建并开始发放')
      setName('')
      onCreated()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Form layout="inline" style={{ marginBottom: 12, rowGap: 8 }}>
      <Form.Item label="发放方式">
        <Select
          value={trigger}
          style={{ width: 150 }}
          onChange={setTrigger}
          options={[
            { value: 'shop', label: '顾客主动领' },
            { value: 'favorite', label: '收藏即送' },
          ]}
        />
      </Form.Item>
      <Form.Item label="券名">
        <Input value={name} onChange={(e) => setName(e.target.value)}
          placeholder="如 新店尝鲜券" maxLength={50} style={{ width: 150 }} />
      </Form.Item>
      <Form.Item label="满(元,0=无门槛)">
        <InputNumber min={0} value={threshold} onChange={setThreshold} style={{ width: 90 }} />
      </Form.Item>
      <Form.Item label="减(元)">
        <InputNumber min={0.01} value={off} onChange={setOff} style={{ width: 90 }} />
      </Form.Item>
      <Form.Item label="总量">
        <InputNumber min={1} value={total} onChange={setTotal} style={{ width: 90 }} />
      </Form.Item>
      <Form.Item label="每人限领"
        hidden={trigger === 'favorite'}
        tooltip="收藏即送固定一店一人一张,此项不适用">
        <InputNumber min={1} max={10} value={perUser} onChange={setPerUser} style={{ width: 70 }} />
      </Form.Item>
      <Form.Item label="有效天数">
        <InputNumber min={1} max={90} value={validDays} onChange={setValidDays} style={{ width: 70 }} />
      </Form.Item>
      <Button type="primary" loading={busy} onClick={create}>创建</Button>
    </Form>
  )
}

/** 活动效果:花出去的钱换回了什么。
 *  只给事实不下结论 —— "用了满减的单客单价更高"不等于"满减让客单价变高"。 */
function EffectCard() {
  const [stats, setStats] = useState<MarketingStats | null>(null)
  const [days, setDays] = useState(30)

  useEffect(() => {
    marketingStats(days).then(setStats).catch(() => { /* 不打断主流程 */ })
  }, [days])

  if (!stats) return null
  const { promo, plain, coupon } = stats
  const diff = promo.avg_ticket_cents - plain.avg_ticket_cents

  return (
    <Card
      size="small"
      title={`活动效果(近 ${stats.days} 天)`}
      extra={
        <Space>
          {[7, 30, 90].map((d) => (
            <Button key={d} size="small" type={d === days ? 'primary' : 'default'}
              onClick={() => setDays(d)}>{d}天</Button>
          ))}
        </Space>
      }
    >
      <Space size="large" wrap style={{ marginBottom: 8 }}>
        <Statistic title="用了满减的单" value={promo.orders} suffix="单" />
        <Statistic title="满减让利" value={yuan(promo.give_cents)} />
        <Statistic title="券核销" value={`${coupon.used}/${coupon.issued}`}
          suffix={coupon.issued > 0
            ? `(${Math.round(coupon.use_rate * 100)}%)` : ''} />
        <Statistic title="券让利" value={yuan(coupon.give_cents)} />
        <Statistic title="让利合计" value={yuan(stats.total_give_cents)} />
      </Space>
      <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)', lineHeight: 1.8 }}>
        客单价:用活动的单 {yuan(promo.avg_ticket_cents)} vs
        没用活动的单 {yuan(plain.avg_ticket_cents)}
        {promo.orders > 0 && plain.orders > 0 && (
          <span style={{ color: diff >= 0 ? 'var(--sz-earn)' : 'var(--sz-danger)' }}>
            （{diff >= 0 ? '+' : ''}{yuan(diff)}）
          </span>
        )}
        <br />
        {stats.flash.length > 0 && (
          <>限时折扣在跑 {stats.flash.length} 道：
            {stats.flash.map((f) => `${f.name}(月售 ${f.monthly_sales})`).join('、')}
            <br /></>
        )}
        <span style={{ color: 'var(--sz-ink-muted)' }}>{stats.note}</span>
      </div>
    </Card>
  )
}
