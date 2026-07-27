import {
  Alert, Button, Card, Form, InputNumber, Input, Space, Switch, Table,
  message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, GiftRule, Merchant, PromoRule, ShopCouponBatch, createShopCouponBatch,
  Dish, myDishes, myShop, shopCouponBatches, toggleShopCouponBatch, updateShop,
  yuan,
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
  const [busy, setBusy] = useState(false)

  async function create() {
    if (!name.trim() || !off || !total) {
      return message.warning('请填写券名、减额与总量')
    }
    setBusy(true)
    try {
      await createShopCouponBatch({
        name: name.trim(),
        threshold_cents: Math.round((threshold ?? 0) * 100),
        off_cents: Math.round(off * 100),
        total,
        per_user_limit: perUser ?? 1,
        valid_days: validDays ?? 7,
      })
      message.success('店铺券已创建并开始发放')
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
      <Form.Item label="每人限领">
        <InputNumber min={1} max={10} value={perUser} onChange={setPerUser} style={{ width: 70 }} />
      </Form.Item>
      <Form.Item label="有效天数">
        <InputNumber min={1} max={90} value={validDays} onChange={setValidDays} style={{ width: 70 }} />
      </Form.Item>
      <Button type="primary" loading={busy} onClick={create}>创建</Button>
    </Form>
  )
}
