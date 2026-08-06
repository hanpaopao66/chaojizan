import { PlusOutlined } from '@ant-design/icons'
import {
  Button, Drawer, Form, Input, InputNumber, Select, Space, Switch, Table,
  Tag, Upload, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, Dish, DishOptionGroup, createDish, myDishes, reorderDishes,
  sellOutDish, updateDish, UPLOAD_ACCEPT, uploadImage, yuan,
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
              <span style={{ color: v <= 0 ? '#e5484d' : undefined }}>
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

function DishDrawer({ existing, onClose }: {
  existing: Dish | null
  onClose: (changed: boolean) => void
}) {
  const [name, setName] = useState(existing?.name ?? '')
  const [category, setCategory] = useState(existing?.category ?? '')
  const [price, setPrice] = useState<number | null>(
    existing ? existing.price_cents / 100 : null)
  const [stock, setStock] = useState<number | null>(existing?.stock ?? 100)
  const [dailyStock, setDailyStock] = useState<number | null>(
    existing?.daily_stock ?? null)
  const [imageUrl, setImageUrl] = useState(existing?.image_url ?? '')
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
      stock,
      daily_stock: dailyStock,
      image_url: imageUrl,
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
              <div key={gi} style={{ border: '1px solid #eee', borderRadius: 8, padding: 8 }}>
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
