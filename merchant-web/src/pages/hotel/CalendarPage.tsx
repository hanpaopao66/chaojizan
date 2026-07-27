import { PlusOutlined } from '@ant-design/icons'
import {
  Button, Checkbox, DatePicker, Drawer, Form, Input, InputNumber, Modal,
  Segmented, Select, Space, Switch, Table, Tabs, Tag, Upload, message,
} from 'antd'
import dayjs, { Dayjs } from 'dayjs'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  ApiError, CANCEL_POLICIES, RoomCalendarRow, RoomType, createRoomType,
  setStayCalendar, stayCalendar, stayRoomTypes, updateRoomType, uploadImage,
} from '../../api'

const DAYS = 30 // 一屏 30 天

const fmt = (d: Dayjs) => d.format('YYYY-MM-DD')

/** 房态中控台:大网格(点单格/拖选区间/键盘流)+ 房型管理。对标 eBooking 网页版。 */
export default function CalendarPage() {
  const [tab, setTab] = useState('calendar')
  const [roomTypes, setRoomTypes] = useState<RoomType[]>([])
  const [rows, setRows] = useState<RoomCalendarRow[]>([])
  const [start, setStart] = useState<Dayjs>(dayjs().startOf('day'))
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [types, calendar] = await Promise.all([
        stayRoomTypes(),
        stayCalendar(fmt(dayjs().startOf('day').isBefore(dayjs(start)) ? start : dayjs().startOf('day').isAfter(start) ? start : start), DAYS),
      ])
      setRoomTypes(types)
      setRows(calendar)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [start])

  useEffect(() => { load() }, [load])

  return (
    <Tabs
      activeKey={tab}
      onChange={setTab}
      items={[
        {
          key: 'calendar',
          label: '房态日历',
          children: (
            <CalendarGrid
              roomTypes={roomTypes}
              rows={rows}
              start={start}
              loading={loading}
              onStartChange={setStart}
              onChanged={load}
            />
          ),
        },
        {
          key: 'types',
          label: '房型管理',
          children: <RoomTypeTable roomTypes={roomTypes} onChanged={load} />,
        },
      ]}
    />
  )
}

// ---------- 房态网格 ----------

interface GridProps {
  roomTypes: RoomType[]
  rows: RoomCalendarRow[]
  start: Dayjs
  loading: boolean
  onStartChange: (d: Dayjs) => void
  onChanged: () => void
}

interface Focus { rt: number; day: number }
interface Drag { rt: number; from: number; to: number }

function CalendarGrid({ roomTypes, rows, start, loading, onStartChange, onChanged }: GridProps) {
  const [focus, setFocus] = useState<Focus | null>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [editor, setEditor] = useState<{ rt: RoomType; date: string } | null>(null)
  const [batch, setBatch] = useState<{
    rtIds: number[]; range: [Dayjs, Dayjs] | null
  } | null>(null)
  const dragRef = useRef<Drag | null>(null)
  const gridRef = useRef<HTMLDivElement>(null)

  const today = dayjs().startOf('day')
  const dates = useMemo(
    () => Array.from({ length: DAYS }, (_, i) => start.add(i, 'day')),
    [start],
  )
  const byKey = useMemo(() => {
    const map = new Map<string, RoomCalendarRow['days'][number]>()
    for (const row of rows) {
      for (const day of row.days) map.set(`${row.room_type_id}:${day.date}`, day)
    }
    return map
  }, [rows])

  // 拖选:mousedown 起点,行内 mouseenter 扩展,mouseup 落定(单格=编辑,多格=批量)
  useEffect(() => {
    function onUp() {
      const d = dragRef.current
      dragRef.current = null
      setDrag(null)
      if (!d) return
      const rt = roomTypes[d.rt]
      if (!rt) return
      const [a, b] = [Math.min(d.from, d.to), Math.max(d.from, d.to)]
      // 推迟到本次 click 事件之后再挂弹层:否则 mouseup 后续的 click
      // 会落在刚出现的蒙层上,把弹层瞬间关掉
      setTimeout(() => {
        if (a === b) {
          setEditor({ rt, date: fmt(dates[a]) })
        } else {
          setBatch({ rtIds: [rt.id], range: [dates[a], dates[b]] })
        }
      }, 0)
    }
    window.addEventListener('mouseup', onUp)
    return () => window.removeEventListener('mouseup', onUp)
  }, [roomTypes, dates])

  function onKeyDown(e: React.KeyboardEvent) {
    if (!focus) return
    const move = (drt: number, dday: number) => {
      e.preventDefault()
      setFocus({
        rt: Math.max(0, Math.min(roomTypes.length - 1, focus.rt + drt)),
        day: Math.max(0, Math.min(DAYS - 1, focus.day + dday)),
      })
    }
    switch (e.key) {
      case 'ArrowLeft': return move(0, -1)
      case 'ArrowRight': return move(0, 1)
      case 'ArrowUp': return move(-1, 0)
      case 'ArrowDown': return move(1, 0)
      case 'Enter': {
        e.preventDefault()
        const rt = roomTypes[focus.rt]
        if (rt && !dates[focus.day].isBefore(today)) {
          setEditor({ rt, date: fmt(dates[focus.day]) })
        }
        return
      }
      case 'Escape':
        setFocus(null)
        return
    }
  }

  const inDrag = (rtIdx: number, dayIdx: number) => {
    const d = drag
    if (!d || d.rt !== rtIdx) return false
    const [a, b] = [Math.min(d.from, d.to), Math.max(d.from, d.to)]
    return dayIdx >= a && dayIdx <= b
  }

  if (roomTypes.length === 0 && !loading) {
    return <div style={{ padding: 40, color: '#888' }}>先到「房型管理」建房型,再回来设价开卖</div>
  }

  return (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button onClick={() => onStartChange(start.subtract(DAYS, 'day'))}
          disabled={!start.isAfter(today)}>← 前 {DAYS} 天</Button>
        <DatePicker
          value={start}
          allowClear={false}
          onChange={(d) => d && onStartChange(d.startOf('day'))}
          disabledDate={(d) => d.isBefore(today)}
        />
        <Button onClick={() => onStartChange(start.add(DAYS, 'day'))}>后 {DAYS} 天 →</Button>
        <Button type="primary" onClick={() => setBatch({ rtIds: roomTypes.map(r => r.id), range: null })}>
          批量设置
        </Button>
        <span style={{ color: '#999', fontSize: 12 }}>
          点单格编辑 · 行内拖选批量 · 方向键移动 + 回车编辑
        </span>
      </Space>
      <div
        ref={gridRef}
        tabIndex={0}
        onKeyDown={onKeyDown}
        style={{ overflowX: 'auto', outline: 'none', userSelect: 'none' }}
      >
        <table style={{ borderCollapse: 'collapse', minWidth: DAYS * 64 + 120 }}>
          <thead>
            <tr>
              <th style={{ ...cellStyle, position: 'sticky', left: 0, background: '#fafafa', zIndex: 2, minWidth: 110 }}>房型</th>
              {dates.map((d, i) => {
                const weekend = d.day() === 0 || d.day() === 6
                const isToday = d.isSame(today, 'day')
                return (
                  <th key={i} style={{
                    ...cellStyle, minWidth: 62, fontWeight: isToday ? 700 : 500,
                    background: isToday ? '#fff3ed' : weekend ? '#fffbe6' : '#fafafa',
                  }}>
                    {d.format('M/D')}
                    <div style={{ fontSize: 10, color: '#999' }}>
                      {'日一二三四五六'[d.day()]}
                    </div>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {roomTypes.map((rt, rtIdx) => (
              <tr key={rt.id}>
                <td style={{
                  ...cellStyle, position: 'sticky', left: 0, background: '#fff',
                  zIndex: 1, fontWeight: 600, minWidth: 110,
                  textDecoration: rt.is_on_sale ? undefined : 'line-through',
                }}>
                  {rt.name}
                </td>
                {dates.map((d, dayIdx) => {
                  const day = byKey.get(`${rt.id}:${fmt(d)}`)
                  const past = d.isBefore(today)
                  const focused = focus?.rt === rtIdx && focus?.day === dayIdx
                  const dragged = inDrag(rtIdx, dayIdx)
                  return (
                    <td
                      key={dayIdx}
                      onMouseDown={() => {
                        if (past) return
                        setFocus({ rt: rtIdx, day: dayIdx })
                        const d0 = { rt: rtIdx, from: dayIdx, to: dayIdx }
                        dragRef.current = d0
                        setDrag(d0)
                        gridRef.current?.focus()
                      }}
                      onMouseEnter={() => {
                        if (dragRef.current && dragRef.current.rt === rtIdx) {
                          const next = { ...dragRef.current, to: dayIdx }
                          dragRef.current = next
                          setDrag(next)
                        }
                      }}
                      style={{
                        ...cellStyle,
                        cursor: past ? 'not-allowed' : 'pointer',
                        opacity: past ? 0.4 : 1,
                        background: dragged ? '#ffd9c9'
                          : focused ? '#fff3ed'
                          : day?.closed ? '#fff1f0' : undefined,
                        outline: focused ? '2px solid #FF5A1F' : undefined,
                        outlineOffset: -2,
                      }}
                    >
                      {day == null ? (
                        <span style={{ color: '#bbb', fontSize: 11 }}>未设价</span>
                      ) : day.closed ? (
                        <span style={{ color: '#e5484d', fontSize: 12 }}>关房</span>
                      ) : (
                        <>
                          <div style={{ fontWeight: 600, fontSize: 12 }}>
                            ¥{(day.price_cents / 100).toFixed(0)}
                          </div>
                          <div style={{
                            fontSize: 11,
                            color: day.total_qty - day.sold_qty <= 0 ? '#e5484d' : '#0E8A5F',
                          }}>
                            余{day.total_qty - day.sold_qty}
                          </div>
                        </>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editor && (
        <CellEditor
          rt={editor.rt}
          date={editor.date}
          day={byKey.get(`${editor.rt.id}:${editor.date}`)}
          onClose={(changed) => {
            setEditor(null)
            if (changed) onChanged()
          }}
        />
      )}
      {batch && (
        <BatchEditor
          roomTypes={roomTypes}
          initialIds={batch.rtIds}
          initialRange={batch.range}
          onClose={(changed) => {
            setBatch(null)
            if (changed) onChanged()
          }}
        />
      )}
    </div>
  )
}

const cellStyle: React.CSSProperties = {
  border: '1px solid #eee',
  padding: '4px 6px',
  textAlign: 'center',
  fontSize: 12,
  height: 44,
}

// ---------- 单格编辑 ----------

function CellEditor({ rt, date, day, onClose }: {
  rt: RoomType
  date: string
  day?: { price_cents: number; total_qty: number; sold_qty: number; closed: boolean }
  onClose: (changed: boolean) => void
}) {
  const [price, setPrice] = useState<number | null>(day ? day.price_cents / 100 : null)
  const [qty, setQty] = useState<number | null>(day ? day.total_qty : 1)
  const [closed, setClosed] = useState(day?.closed ?? false)
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    try {
      await setStayCalendar({
        room_type_ids: [rt.id],
        from_date: date,
        to_date: date,
        price_cents: price != null && price > 0 ? Math.round(price * 100) : undefined,
        total_qty: qty ?? undefined,
        closed,
      })
      onClose(true)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={`${rt.name} · ${date}`}
      onCancel={() => onClose(false)}
      onOk={save}
      confirmLoading={busy}
      okText="保存"
      width={360}
    >
      <Form layout="vertical">
        <Form.Item label="当晚价格(元)" required={!day}>
          <InputNumber
            style={{ width: '100%' }}
            min={1}
            value={price}
            onChange={setPrice}
            placeholder={day ? '不改留空' : '首次开放必须设价'}
          />
        </Form.Item>
        <Form.Item
          label="可售总量(间)"
          extra={day && day.sold_qty > 0 ? `已售 ${day.sold_qty} 间,总量不能低于已售` : undefined}
        >
          <InputNumber style={{ width: '100%' }} min={0} value={qty} onChange={setQty} />
        </Form.Item>
        <Form.Item label="关房(暂停售卖当晚)">
          <Switch checked={closed} onChange={setClosed} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ---------- 批量设置 ----------

function BatchEditor({ roomTypes, initialIds, initialRange, onClose }: {
  roomTypes: RoomType[]
  initialIds: number[]
  initialRange: [Dayjs, Dayjs] | null
  onClose: (changed: boolean) => void
}) {
  const [ids, setIds] = useState<number[]>(initialIds)
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(initialRange)
  const [price, setPrice] = useState<number | null>(null)
  const [qty, setQty] = useState<number | null>(null)
  const [roomState, setRoomState] = useState<'keep' | 'open' | 'close'>('keep')
  const [busy, setBusy] = useState(false)
  const today = dayjs().startOf('day')

  async function save() {
    if (ids.length === 0) return message.warning('至少选择一个房型')
    if (!range) return message.warning('请选择日期区间')
    if (price == null && qty == null && roomState === 'keep') {
      return message.warning('价格、间数、房态至少设置一项')
    }
    setBusy(true)
    try {
      const result = await setStayCalendar({
        room_type_ids: ids,
        from_date: fmt(range[0]),
        to_date: fmt(range[1]),
        price_cents: price != null ? Math.round(price * 100) : undefined,
        total_qty: qty ?? undefined,
        closed: roomState === 'keep' ? undefined : roomState === 'close',
      })
      message.success(`已应用:新开 ${result.created} 天格,更新 ${result.updated} 天格`)
      onClose(true)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title="批量设置(区间 × 多房型,留空的项不改)"
      onCancel={() => onClose(false)}
      onOk={save}
      confirmLoading={busy}
      okText="应用"
      width={460}
    >
      <Form layout="vertical">
        <Form.Item label="房型">
          <Checkbox.Group
            options={roomTypes.map(rt => ({ label: rt.name, value: rt.id }))}
            value={ids}
            onChange={(v) => setIds(v as number[])}
          />
        </Form.Item>
        <Form.Item label="日期区间(今天起,最长 120 天)">
          <DatePicker.RangePicker
            value={range}
            onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)}
            disabledDate={(d) => d.isBefore(today) || d.isAfter(today.add(120, 'day'))}
          />
        </Form.Item>
        <Form.Item label="每晚价格(元)" extra="首次开放的日期必须带价格">
          <InputNumber style={{ width: '100%' }} min={1} value={price}
            onChange={setPrice} placeholder="不改留空" />
        </Form.Item>
        <Form.Item label="可售总量(间)">
          <InputNumber style={{ width: '100%' }} min={0} value={qty}
            onChange={setQty} placeholder="不改留空" />
        </Form.Item>
        <Form.Item label="房态">
          <Segmented
            options={[
              { label: '不动', value: 'keep' },
              { label: '开房', value: 'open' },
              { label: '关房', value: 'close' },
            ]}
            value={roomState}
            onChange={(v) => setRoomState(v as 'keep' | 'open' | 'close')}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ---------- 房型管理 ----------

function RoomTypeTable({ roomTypes, onChanged }: {
  roomTypes: RoomType[]
  onChanged: () => void
}) {
  const [editing, setEditing] = useState<RoomType | null | 'new'>(null)

  return (
    <div>
      <Button
        type="primary"
        icon={<PlusOutlined />}
        style={{ marginBottom: 12 }}
        onClick={() => setEditing('new')}
      >
        新增房型
      </Button>
      <Table<RoomType>
        rowKey="id"
        dataSource={roomTypes}
        pagination={false}
        columns={[
          {
            title: '房型',
            dataIndex: 'name',
            render: (name: string, rt) => (
              <Space>
                {rt.image_urls[0] && (
                  <img src={rt.image_urls[0]} alt="" style={{
                    width: 40, height: 40, objectFit: 'cover', borderRadius: 6,
                  }} />
                )}
                <span style={{
                  textDecoration: rt.is_on_sale ? undefined : 'line-through',
                }}>{name}</span>
              </Space>
            ),
          },
          { title: '床型', dataIndex: 'bed_type' },
          {
            title: '面积',
            dataIndex: 'area_m2',
            render: (v: number) => (v > 0 ? `${v}㎡` : '—'),
          },
          {
            title: '可住',
            dataIndex: 'max_guests',
            render: (v: number) => `${v} 人`,
          },
          {
            title: '取消政策',
            dataIndex: 'cancel_policy',
            render: (p: string, rt) => (
              <Tag color={p === 'limited_free' ? 'green' : p === 'strict' ? 'orange' : 'default'}>
                {CANCEL_POLICIES[p]}
                {p === 'limited_free' ? ` ${rt.free_cancel_until} 前` : ''}
              </Tag>
            ),
          },
          {
            title: '在售',
            dataIndex: 'is_on_sale',
            render: (v: boolean, rt) => (
              <Switch
                checked={v}
                onChange={async (checked) => {
                  try {
                    await updateRoomType(rt.id, { is_on_sale: checked })
                    onChanged()
                  } catch (e) {
                    message.error(e instanceof ApiError ? e.message : String(e))
                  }
                }}
              />
            ),
          },
          {
            title: '操作',
            render: (_, rt) => (
              <Button size="small" onClick={() => setEditing(rt)}>编辑</Button>
            ),
          },
        ]}
      />
      {editing !== null && (
        <RoomTypeDrawer
          existing={editing === 'new' ? null : editing}
          onClose={(changed) => {
            setEditing(null)
            if (changed) onChanged()
          }}
        />
      )}
    </div>
  )
}

function RoomTypeDrawer({ existing, onClose }: {
  existing: RoomType | null
  onClose: (changed: boolean) => void
}) {
  const [name, setName] = useState(existing?.name ?? '')
  const [bedType, setBedType] = useState(existing?.bed_type ?? '')
  const [area, setArea] = useState<number | null>(existing?.area_m2 || null)
  const [maxGuests, setMaxGuests] = useState(existing?.max_guests ?? 2)
  const [policy, setPolicy] = useState(existing?.cancel_policy ?? 'limited_free')
  const [freeUntil, setFreeUntil] = useState(existing?.free_cancel_until ?? '18:00')
  const [images, setImages] = useState<string[]>(existing?.image_urls ?? [])
  const [busy, setBusy] = useState(false)

  async function save() {
    if (!name.trim()) return message.warning('请填写房型名称')
    setBusy(true)
    const fields = {
      name: name.trim(),
      bed_type: bedType.trim(),
      area_m2: area ?? 0,
      max_guests: maxGuests,
      cancel_policy: policy,
      free_cancel_until: freeUntil,
      image_urls: images,
    }
    try {
      if (existing) await updateRoomType(existing.id, fields)
      else await createRoomType(fields)
      onClose(true)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <Drawer
      open
      title={existing ? '编辑房型' : '新增房型'}
      width={420}
      onClose={() => onClose(false)}
      extra={<Button type="primary" loading={busy} onClick={save}>保存</Button>}
    >
      <Form layout="vertical">
        <Form.Item label="房型名称" required>
          <Input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="如 高级大床房" maxLength={60} />
        </Form.Item>
        <Form.Item label="床型">
          <Input value={bedType} onChange={(e) => setBedType(e.target.value)}
            placeholder="如 1.8m 大床" maxLength={30} />
        </Form.Item>
        <Space>
          <Form.Item label="面积(㎡)">
            <InputNumber min={0} max={500} value={area} onChange={setArea} />
          </Form.Item>
          <Form.Item label="可住人数">
            <Select
              style={{ width: 100 }}
              value={maxGuests}
              onChange={setMaxGuests}
              options={[1, 2, 3, 4, 5, 6].map(n => ({ label: `${n} 人`, value: n }))}
            />
          </Form.Item>
        </Space>
        <Form.Item
          label="取消政策"
          extra="改动只影响新订单,已有订单按下单时的政策执行"
        >
          <Select
            value={policy}
            onChange={setPolicy}
            options={Object.entries(CANCEL_POLICIES).map(([value, label]) => ({ value, label }))}
          />
        </Form.Item>
        {policy === 'limited_free' && (
          <Form.Item label="入住日免费取消截止时刻">
            <Select
              value={freeUntil}
              onChange={setFreeUntil}
              options={['12:00', '14:00', '16:00', '18:00', '20:00', '23:59']
                .map(t => ({ value: t, label: `入住日 ${t} 前免费取消` }))}
            />
          </Form.Item>
        )}
        <Form.Item label={`房型图片(${images.length}/9)`}>
          <Upload
            listType="picture-card"
            fileList={images.map((url, i) => ({
              uid: String(i), name: `图${i + 1}`, status: 'done' as const, url,
            }))}
            customRequest={async ({ file, onSuccess, onError }) => {
              try {
                const url = await uploadImage(file as File)
                setImages((prev) => [...prev, url])
                onSuccess?.(url)
              } catch (e) {
                message.error(e instanceof ApiError ? e.message : String(e))
                onError?.(e as Error)
              }
            }}
            onRemove={(file) => {
              setImages((prev) => prev.filter((u) => u !== file.url))
            }}
            accept="image/*"
            showUploadList={{ showPreviewIcon: false }}
          >
            {images.length < 9 && <div>+ 上传</div>}
          </Upload>
        </Form.Item>
      </Form>
    </Drawer>
  )
}
