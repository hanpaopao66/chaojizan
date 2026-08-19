import { PlusOutlined } from '@ant-design/icons'
import {
  Button, Drawer, Form, Input, InputNumber, Select, Space, Switch, Table,
  Tag, Upload, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, Dish, DISH_BADGES, DishOptionGroup, createDish, myDishes,
  reorderDishes, sellOutDish, updateDish, UPLOAD_ACCEPT, uploadImage, yuan,
} from '../../api'

/** 菜品管理:表格批量效率是网页价值(多选批量上下架/改分类,单击进抽屉编辑)。 */
export default function DishesPage() {
  const [dishes, setDishes] = useState<Dish[]>([])
  const [selected, setSelected] = useState<number[]>([])
  const [editing, setEditing] = useState<Dish | null | 'new'>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setDishes(await myDishes())
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function batchOnSale(onSale: boolean) {
    try {
      await Promise.all(selected.map((id) => updateDish(id, { is_on_sale: onSale })))
      message.success(`已批量${onSale ? '上架' : '下架'} ${selected.length} 个菜品`)
      setSelected([])
      load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  const categories = [...new Set(dishes.map((d) => d.category).filter(Boolean))]

  return (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditing('new')}>
          新增菜品
        </Button>
        <Button disabled={selected.length === 0} onClick={() => batchOnSale(true)}>
          批量上架({selected.length})
        </Button>
        <Button disabled={selected.length === 0} onClick={() => batchOnSale(false)}>
          批量下架({selected.length})
        </Button>
      </Space>
      <Table<Dish>
        rowKey="id"
        dataSource={dishes}
        loading={loading}
        pagination={{ pageSize: 20 }}
        rowSelection={{
          selectedRowKeys: selected,
          onChange: (keys) => setSelected(keys as number[]),
        }}
        columns={[
          {
            title: '菜品',
            dataIndex: 'name',
            render: (name: string, d) => (
              <Space>
                {d.image_url && (
                  <img src={d.image_url} alt="" style={{
                    width: 36, height: 36, objectFit: 'cover', borderRadius: 6,
                  }} />
                )}
                <span style={{
                  textDecoration: d.is_on_sale ? undefined : 'line-through',
                }}>{name}</span>
                {d.is_alcohol && <Tag color="red">酒</Tag>}
                {d.sold_out_today && <Tag>今日售罄</Tag>}
              </Space>
            ),
          },
          {
            title: '分类',
            dataIndex: 'category',
            filters: categories.map((c) => ({ text: c, value: c })),
            onFilter: (v, d) => d.category === v,
          },
          {
            title: '价格',
            dataIndex: 'price_cents',
            render: (v: number) => yuan(v),
            sorter: (a, b) => a.price_cents - b.price_cents,
          },
          {
            title: '库存',
            dataIndex: 'stock',
            sorter: (a, b) => a.stock - b.stock,
            render: (v: number, d) => (
              <span style={{ color: v <= 0 ? 'var(--sz-danger)' : undefined }}>
                {v}{d.daily_stock != null ? ` / 每日回满 ${d.daily_stock}` : ''}
              </span>
            ),
          },
          { title: '月售', dataIndex: 'monthly_sales' },
          {
            title: '在售',
            dataIndex: 'is_on_sale',
            render: (v: boolean, d) => (
              <Switch checked={v} onChange={async (checked) => {
                try {
                  await updateDish(d.id, { is_on_sale: checked })
                  load()
                } catch (e) {
                  message.error(e instanceof ApiError ? e.message : String(e))
                }
              }} />
            ),
          },
          {
            title: '顺序',
            dataIndex: 'sort',
            sorter: (a, b) => a.sort - b.sort,
            render: (v: number) => v,
          },
          {
            title: '操作',
            render: (_, d) => (
              <Space>
                <Button size="small" onClick={() => setEditing(d)}>编辑</Button>
                <Button size="small" onClick={async () => {
                  // 置顶:排到同分类最前(招牌菜该在第一屏)
                  const sameCat = dishes.filter((x) => x.category === d.category)
                  const min = Math.min(...sameCat.map((x) => x.sort), 0)
                  if (sameCat[0]?.id === d.id) {
                    message.info('已经在最前面了')
                    return
                  }
                  try {
                    await reorderDishes([{
                      dish_id: d.id,
                      sort: Math.max(min - 1, -9999),
                    }])
                    message.success(`已置顶到「${d.category || '未分类'}」最前`)
                    load()
                  } catch (e) {
                    message.error(e instanceof ApiError ? e.message : String(e))
                  }
                }}>置顶</Button>
                <Button size="small" onClick={async () => {
                  try {
                    await sellOutDish(d.id, d.sold_out_today)
                    message.success(d.sold_out_today ? '已恢复售卖' : '已标记今日售罄')
                    load()
                  } catch (e) {
                    message.error(e instanceof ApiError ? e.message : String(e))
                  }
                }}>
                  {d.sold_out_today ? '恢复' : '估清'}
                </Button>
              </Space>
            ),
          },
        ]}
      />
      {editing !== null && (
        <DishDrawer
          allDishes={dishes}
          existing={editing === 'new' ? null : editing}
          onClose={(changed) => {
            setEditing(null)
            if (changed) load()
          }}
        />
      )}
    </div>
  )
}

function DishDrawer({ existing, allDishes, onClose }: {
  existing: Dish | null
  allDishes: Dish[]
  onClose: (changed: boolean) => void
}) {
  const [name, setName] = useState(existing?.name ?? '')
  const [category, setCategory] = useState(existing?.category ?? '')
  const [price, setPrice] = useState<number | null>(
    existing ? existing.price_cents / 100 : null)
  const [stock, setStock] = useState<number | null>(existing?.stock ?? 100)
  // 成本(元)。0/未录 → null,输入框留空 —— 0 是"没录过"不是"成本为零",
  // 显示成 0.00 会让人以为已经录过了
  const [cost, setCost] = useState<number | null>(
    existing?.cost_cents ? existing.cost_cents / 100 : null)
  // 额外打包费(元);null = 用店铺的每单打包费
  const [packing, setPacking] = useState<number | null>(
    existing?.packing_fee_cents != null
      ? existing.packing_fee_cents / 100 : null)
  const [dailyStock, setDailyStock] = useState<number | null>(
    existing?.daily_stock ?? null)
  const [imageUrl, setImageUrl] = useState(existing?.image_url ?? '')
  const [description, setDescription] = useState(existing?.description ?? '')
  const [badges, setBadges] = useState<string[]>(existing?.badges ?? [])
  const [serveWindow, setServeWindow] = useState(existing?.serve_window ?? '')
  const [comboItems, setComboItems] = useState<{ dish_id: number; quantity: number }[]>(
    existing?.combo_items ?? [])
  const [groups, setGroups] = useState<DishOptionGroup[]>(
    existing?.options ?? [])
  const [busy, setBusy] = useState(false)

  async function save() {
    const priceCents = Math.round((price ?? 0) * 100)
    if (!name.trim() || priceCents <= 0 || stock == null || stock < 0) {
      return message.warning('名称、价格、库存必填且有效')
    }
    setBusy(true)
    const cleanGroups = groups
      .filter((g) => g.name.trim() && g.items.length > 0)
      .map((g) => ({
        name: g.name.trim(),
        required: g.required,
        items: g.items.filter((i) => i.name.trim()),
      }))
    const fields = {
      name: name.trim(),
      category: category.trim(),
      price_cents: priceCents,
      cost_cents: cost == null ? 0 : Math.round(cost * 100),
      // null 有语义:清回"用店铺默认",所以显式传 null 而不是省略
      packing_fee_cents: packing == null ? null : Math.round(packing * 100),
      stock,
      daily_stock: dailyStock,
      image_url: imageUrl,
      description: description.trim(),
      badges,
      serve_window: serveWindow.trim(),
      combo_items: comboItems,
      options: cleanGroups,
    }
    try {
      if (existing) await updateDish(existing.id, fields)
      else await createDish(fields)
      onClose(true)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <Drawer
      open
      title={existing ? '编辑菜品' : '新增菜品'}
      width={440}
      onClose={() => onClose(false)}
      extra={<Button type="primary" loading={busy} onClick={save}>保存</Button>}
    >
      <Form layout="vertical">
        <Form.Item label="菜品名称" required>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} />
        </Form.Item>
        <Form.Item label="店内分类(如 主食/饮品,用于点单页归组)">
          <Input value={category} onChange={(e) => setCategory(e.target.value)} maxLength={20} />
        </Form.Item>
        <Space>
          <Form.Item label="价格(元)" required>
            <InputNumber min={0.01} value={price} onChange={setPrice} />
          </Form.Item>
          <Form.Item label="库存" required>
            <InputNumber min={0} value={stock} onChange={setStock} />
          </Form.Item>
          <Form.Item label="每日回满(空=不启用)">
            <InputNumber min={0} value={dailyStock} onChange={setDailyStock} />
          </Form.Item>
        </Space>
        <Space align="start">
          <Form.Item
            label="成本(元/份)"
            extra="只你自己看得到,不会出现在用户端。填了才能算毛利。"
          >
            <InputNumber min={0} value={cost} onChange={setCost}
              placeholder="未录" />
          </Form.Item>
          <Form.Item
            label="额外打包费(元/份)"
            extra={`空=只收店铺的每单打包费;填了在那笔之外按份数另加。`}
          >
            <InputNumber min={0} max={20} value={packing}
              onChange={setPacking} placeholder="用店铺默认" />
          </Form.Item>
          {cost != null && price != null && price > 0 && (
            <Form.Item label="毛利">
              <div style={{ paddingTop: 4 }}>
                <span style={{
                  fontSize: 16, fontWeight: 600,
                  color: price - cost > 0 ? 'var(--sz-earn)' : 'var(--sz-danger)',
                }}>
                  ¥{(price - cost).toFixed(2)}
                </span>
                <span style={{ marginLeft: 8, color: 'var(--sz-ink-muted)' }}>
                  {Math.round((price - cost) / price * 100)}%
                </span>
                <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)' }}>
                  卖价 − 进价,不含平台佣金与配送
                </div>
              </div>
            </Form.Item>
          )}
        </Space>
        <Form.Item label="菜品描述"
          extra="写清用料和口味,有忌口的顾客不用猜">
          <Input.TextArea
            value={description}
            maxLength={200}
            rows={2}
            showCount
            onChange={(e) => setDescription(e.target.value)}
          />
        </Form.Item>
        <Form.Item label="标签(最多 4 个,用户端显示角标)">
          <Space wrap>
            {DISH_BADGES.map((b) => (
              <Tag.CheckableTag
                key={b}
                checked={badges.includes(b)}
                onChange={(on) => setBadges(on
                  ? (badges.length < 4 ? [...badges, b] : badges)
                  : badges.filter((x) => x !== b))}
              >{b}</Tag.CheckableTag>
            ))}
          </Space>
        </Form.Item>
        <Form.Item label="供应时段(选填)"
          extra="留空=全天供应;非供应时段顾客看得到但点不了,如 06:00-10:30">
          <Input
            value={serveWindow}
            placeholder="06:00-10:30"
            style={{ width: 180 }}
            onChange={(e) => setServeWindow(e.target.value.trim())}
          />
        </Form.Item>
        <Form.Item label="套餐(选填)"
          extra="选中的菜组成套餐,本菜价格即套餐价;下单时逐个扣子项库存">
          <Select
            mode="multiple"
            allowClear
            style={{ width: '100%' }}
            placeholder="不选 = 这是一道普通菜"
            value={comboItems.map((c) => c.dish_id)}
            onChange={(ids: number[]) => setComboItems(ids.slice(0, 8).map((id) => ({
              dish_id: id,
              quantity: comboItems.find((c) => c.dish_id === id)?.quantity ?? 1,
            })))}
            options={allDishes
              .filter((d) => d.id !== existing?.id && !(d.combo_items?.length))
              .map((d) => ({ value: d.id, label: `${d.name}(${yuan(d.price_cents)})` }))}
          />
        </Form.Item>
        <Form.Item label="菜品图">
          <Upload
            listType="picture-card"
            maxCount={1}
            fileList={imageUrl
              ? [{ uid: '1', name: '图', status: 'done' as const, url: imageUrl }]
              : []}
            customRequest={async ({ file, onSuccess, onError, onProgress }) => {
              try {
                const url = await uploadImage(file as File, 'dish',
                  (percent) => onProgress?.({ percent }))
                setImageUrl(url)
                onSuccess?.(url)
              } catch (e) {
                message.error(e instanceof ApiError ? e.message : String(e))
                onError?.(e as Error)
              }
            }}
            onRemove={() => setImageUrl('')}
            accept={UPLOAD_ACCEPT}
          >
            {!imageUrl && <div>+ 上传</div>}
          </Upload>
        </Form.Item>
        <Form.Item label="规格组(如 份量/辣度;每组内单选)">
          <Space direction="vertical" style={{ width: '100%' }}>
            {groups.map((g, gi) => (
              <div key={gi} style={{ border: '1px solid var(--sz-line)', borderRadius: 8, padding: 8 }}>
                <Space style={{ marginBottom: 6 }}>
                  <Input
                    placeholder="组名(如 辣度)"
                    value={g.name}
                    style={{ width: 140 }}
                    onChange={(e) => {
                      const next = [...groups]
                      next[gi] = { ...g, name: e.target.value }
                      setGroups(next)
                    }}
                  />
                  <Select
                    value={g.required ? 1 : 0}
                    style={{ width: 90 }}
                    options={[{ value: 1, label: '必选' }, { value: 0, label: '可选' }]}
                    onChange={(v) => {
                      const next = [...groups]
                      next[gi] = { ...g, required: v === 1 }
                      setGroups(next)
                    }}
                  />
                  <Button size="small" danger
                    onClick={() => setGroups(groups.filter((_, i) => i !== gi))}>
                    删组
                  </Button>
                </Space>
                {g.items.map((it, ii) => (
                  <Space key={ii} style={{ marginBottom: 4 }}>
                    <Input
                      placeholder="规格名(如 微辣)"
                      value={it.name}
                      style={{ width: 140 }}
                      onChange={(e) => {
                        const next = [...groups]
                        const items = [...g.items]
                        items[ii] = { ...it, name: e.target.value }
                        next[gi] = { ...g, items }
                        setGroups(next)
                      }}
                    />
                    <InputNumber
                      placeholder="加价(元)"
                      value={it.price_delta_cents / 100}
                      style={{ width: 110 }}
                      onChange={(v) => {
                        const next = [...groups]
                        const items = [...g.items]
                        items[ii] = { ...it, price_delta_cents: Math.round((v ?? 0) * 100) }
                        next[gi] = { ...g, items }
                        setGroups(next)
                      }}
                    />
                    <Button size="small"
                      onClick={() => {
                        const next = [...groups]
                        next[gi] = { ...g, items: g.items.filter((_, i) => i !== ii) }
                        setGroups(next)
                      }}>
                      删
                    </Button>
                  </Space>
                ))}
                <Button size="small" onClick={() => {
                  const next = [...groups]
                  next[gi] = { ...g, items: [...g.items, { name: '', price_delta_cents: 0 }] }
                  setGroups(next)
                }}>
                  + 加规格
                </Button>
              </div>
            ))}
            <Button onClick={() => setGroups([...groups, { name: '', required: true, items: [] }])}>
              + 加规格组
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Drawer>
  )
}
