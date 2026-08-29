import {
  Alert, Button, Card, Form, Input, InputNumber, Select, Space, Statistic,
  Switch, Table, Tag, Upload, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, ApiKey, ApiLogRow, ApiUsage, HotelProfileData, Merchant,
  StaffMember, addStaff, createApiKey, myApiKeys, myApiLogs, myApiUsage,
  myHotelProfile, myShop, myStaff, removeStaff,
  restShop, revokeApiKey, updateHotelProfile, updateShop,
  UPLOAD_ACCEPT, uploadImage,
} from '../api'

/** 店铺设置:通用区(公告/图集/营业时间/临时歇业/店员)+ 业态区分叉渲染。
 *  两个业态互相看不到对方的设置(不是隐藏开关,是分叉)。 */
export default function SettingsPage({ shop: initialShop, onShopChanged }: {
  shop: Merchant
  onShopChanged: () => void
}) {
  const [shop, setShop] = useState<Merchant>(initialShop)
  const isHotel = shop.biz_type === 'hotel'

  const reload = useCallback(async () => {
    try {
      setShop(await myShop())
      onShopChanged()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }, [onShopChanged])

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <GeneralCard shop={shop} onChanged={reload} />
      {isHotel ? <HotelCard /> : <FoodCard shop={shop} onChanged={reload} />}
      <StaffCard />
      {!shop.viewer_is_staff && <ApiKeyCard />}
      <Card size="small">
        <Alert
          type="info"
          showIcon
          message="对账疑问、审核进度、资质变更等任何问题,都可以在商家 App「店铺-联系平台客服」提交工单,或直接联系平台。"
        />
      </Card>
    </Space>
  )
}

function GeneralCard({ shop, onChanged }: { shop: Merchant; onChanged: () => void }) {
  const [announcement, setAnnouncement] = useState(shop.announcement)
  const [openTime, setOpenTime] = useState(shop.open_time)
  const [closeTime, setCloseTime] = useState(shop.close_time)
  const [photos, setPhotos] = useState<string[]>(shop.photo_urls ?? [])
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    try {
      await updateShop({
        announcement: announcement.trim(),
        open_time: openTime,
        close_time: closeTime,
        photo_urls: photos,
      })
      message.success('已保存')
      onChanged()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function rest(hours: number | null, untilClose: boolean) {
    try {
      await restShop(hours, untilClose)
      message.success(untilClose ? '已歇业到今天打烊' : `已歇业 ${hours} 小时,到点自动恢复`)
      onChanged()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <Card size="small" title="通用设置">
      <Form layout="vertical" style={{ maxWidth: 640 }}>
        <Form.Item label="店铺公告(展示给用户)">
          <Input.TextArea
            value={announcement}
            maxLength={200}
            rows={2}
            onChange={(e) => setAnnouncement(e.target.value)}
          />
        </Form.Item>
        <Space>
          <Form.Item label="每日营业开始(HH:MM,留空=纯手动)">
            <Input value={openTime} style={{ width: 130 }}
              placeholder="如 09:00"
              onChange={(e) => setOpenTime(e.target.value.trim())} />
          </Form.Item>
          <Form.Item label="每日营业结束">
            <Input value={closeTime} style={{ width: 130 }}
              placeholder="如 22:00"
              onChange={(e) => setCloseTime(e.target.value.trim())} />
          </Form.Item>
        </Space>
        <Form.Item label={`门店图集(${photos.length}/9)`}>
          <Upload
            listType="picture-card"
            fileList={photos.map((url, i) => ({
              uid: String(i), name: `图${i + 1}`, status: 'done' as const, url,
            }))}
            customRequest={async ({ file, onSuccess, onError, onProgress }) => {
              try {
                const url = await uploadImage(file as File, 'gallery',
                  (percent) => onProgress?.({ percent }))
                setPhotos((prev) => [...prev, url])
                onSuccess?.(url)
              } catch (e) {
                message.error(e instanceof ApiError ? e.message : String(e))
                onError?.(e as Error)
              }
            }}
            onRemove={(file) => setPhotos((prev) => prev.filter((u) => u !== file.url))}
            accept={UPLOAD_ACCEPT}
            showUploadList={{ showPreviewIcon: false }}
          >
            {photos.length < 9 && <div>+ 上传</div>}
          </Upload>
        </Form.Item>
        <Space wrap>
          <Button type="primary" loading={busy} onClick={save}>保存</Button>
          <Button onClick={() => rest(1, false)}>临时歇业 1 小时</Button>
          <Button onClick={() => rest(3, false)}>歇业 3 小时</Button>
          <Button onClick={() => rest(null, true)}>歇业到今天打烊</Button>
        </Space>
      </Form>
    </Card>
  )
}

function FoodCard({ shop, onChanged }: { shop: Merchant; onChanged: () => void }) {
  const [minOrder, setMinOrder] = useState(shop.min_order_cents / 100)
  const [packing, setPacking] = useState(shop.packing_fee_cents / 100)
  const [readyMinutes, setReadyMinutes] = useState(shop.promise_ready_minutes)
  const [selfDelivery, setSelfDelivery] = useState(shop.self_delivery)
  const [foodSeal, setFoodSeal] = useState(shop.food_seal)
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    try {
      await updateShop({
        min_order_cents: Math.round(minOrder * 100),
        packing_fee_cents: Math.round(packing * 100),
        promise_ready_minutes: readyMinutes,
        self_delivery: selfDelivery,
        food_seal: foodSeal,
      })
      message.success('已保存')
      onChanged()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card size="small" title="外卖经营设置">
      <Space wrap size="large">
        <Form.Item label="起送价(元,0=不限)">
          <InputNumber min={0} value={minOrder} onChange={(v) => setMinOrder(v ?? 0)} />
        </Form.Item>
        <Form.Item label="每单打包费(元)">
          <InputNumber min={0} value={packing} onChange={(v) => setPacking(v ?? 0)} />
        </Form.Item>
        <Form.Item label="承诺出餐时长(分钟)">
          <InputNumber min={5} max={120} value={readyMinutes}
            onChange={(v) => setReadyMinutes(v ?? 15)} />
        </Form.Item>
        <Form.Item label="商家自配送(订单不进抢单池)">
          <Switch checked={selfDelivery} onChange={setSelfDelivery} />
        </Form.Item>
        <Form.Item label="食安封签"
          tooltip="打包贴一次性封签,拆封即留痕。用户端显示「商家声明使用食安封签」——是你的声明不是平台认证">
          <Switch checked={foodSeal} onChange={setFoodSeal} />
        </Form.Item>
      </Space>
      <div>
        <Button type="primary" loading={busy} onClick={save}>保存</Button>
      </div>
    </Card>
  )
}

const FACILITY_OPTIONS = [
  { value: 'wifi', label: '免费 WiFi' },
  { value: 'parking', label: '停车场' },
  { value: 'breakfast', label: '含早餐' },
  { value: 'luggage', label: '行李寄存' },
  { value: 'front_desk_24h', label: '24h 前台' },
  { value: 'elevator', label: '电梯' },
]

function HotelCard() {
  const [profile, setProfile] = useState<HotelProfileData | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    myHotelProfile().then(setProfile).catch((e) =>
      message.error(e instanceof ApiError ? e.message : String(e)))
  }, [])

  if (!profile) return null

  async function save() {
    if (!profile) return
    setBusy(true)
    try {
      await updateHotelProfile({
        front_desk_phone: profile.front_desk_phone,
        checkin_from: profile.checkin_from,
        checkout_until: profile.checkout_until,
        facilities: profile.facilities,
      })
      message.success('已保存,用户端订单详情与酒店页同步更新')
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card size="small" title="酒店经营设置">
      <Form layout="vertical" style={{ maxWidth: 560 }}>
        <Space wrap>
          <Form.Item label="前台电话(住客一键拨打)">
            <Input
              value={profile.front_desk_phone}
              style={{ width: 180 }}
              maxLength={20}
              onChange={(e) => setProfile({ ...profile, front_desk_phone: e.target.value.trim() })}
            />
          </Form.Item>
          <Form.Item label="最早入住时刻">
            <Input
              value={profile.checkin_from}
              style={{ width: 100 }}
              placeholder="14:00"
              onChange={(e) => setProfile({ ...profile, checkin_from: e.target.value.trim() })}
            />
          </Form.Item>
          <Form.Item label="最晚退房时刻">
            <Input
              value={profile.checkout_until}
              style={{ width: 100 }}
              placeholder="12:00"
              onChange={(e) => setProfile({ ...profile, checkout_until: e.target.value.trim() })}
            />
          </Form.Item>
        </Space>
        <Form.Item label="设施标签">
          <Select
            mode="multiple"
            value={profile.facilities}
            options={FACILITY_OPTIONS}
            style={{ maxWidth: 420 }}
            onChange={(v) => setProfile({ ...profile, facilities: v })}
          />
        </Form.Item>
        <Form.Item label="资质(只读)">
          <Tag>特种行业许可证:{profile.special_license_no}</Tag>
          <span style={{ color: 'var(--sz-ink-muted)', fontSize: 12, marginLeft: 8 }}>
            变更资质请联系平台客服人工核验
          </span>
        </Form.Item>
        <Button type="primary" loading={busy} onClick={save}>保存</Button>
      </Form>
    </Card>
  )
}

function StaffCard() {
  const [staff, setStaff] = useState<StaffMember[]>([])
  const [phone, setPhone] = useState('')
  const [name, setName] = useState('')

  const load = useCallback(() => {
    myStaff().then(setStaff).catch(() => { /* 店员访问返回空 */ })
  }, [])

  useEffect(() => { load() }, [load])

  async function add() {
    if (!/^1\d{10}$/.test(phone)) return message.warning('请输入 11 位手机号')
    try {
      await addStaff(phone, name.trim())
      message.success('已添加店员')
      setPhone('')
      setName('')
      load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <Card size="small" title="店员管理(店员可接单/办理入住,不能提现改价)">
      <Space style={{ marginBottom: 12 }} wrap>
        <Input value={phone} placeholder="店员手机号" maxLength={11}
          style={{ width: 160 }} onChange={(e) => setPhone(e.target.value.trim())} />
        <Input value={name} placeholder="备注名(选填)" maxLength={20}
          style={{ width: 140 }} onChange={(e) => setName(e.target.value)} />
        <Button type="primary" onClick={add}>添加</Button>
        <span style={{ color: 'var(--sz-ink-muted)', fontSize: 12 }}>
          对方需先用商家端 App 或本网页登录过一次(同手机号的商家账号)
        </span>
      </Space>
      <Table<StaffMember>
        rowKey="user_id"
        dataSource={staff}
        size="small"
        pagination={false}
        columns={[
          { title: '姓名', dataIndex: 'name' },
          { title: '手机号', dataIndex: 'phone' },
          {
            title: '操作',
            render: (_, s) => (
              <Button size="small" danger onClick={async () => {
                try {
                  await removeStaff(s.user_id)
                  message.success('已移除')
                  load()
                } catch (e) {
                  message.error(e instanceof ApiError ? e.message : String(e))
                }
              }}>
                移除
              </Button>
            ),
          },
        ]}
      />
    </Card>
  )
}

/** 开放接口(POS 对接):生成/吊销只读 Key + 接入说明。
 *  明文只在生成那一刻显示一次,库里存的是哈希。 */
function ApiKeyCard() {
  const [keys, setKeys] = useState<ApiKey[]>([])
  const [name, setName] = useState('')
  const [fresh, setFresh] = useState('')

  const load = useCallback(() => {
    myApiKeys().then(setKeys).catch(() => { /* 店员无权,静默 */ })
  }, [])

  useEffect(() => { load() }, [load])

  async function create() {
    try {
      const created = await createApiKey(name.trim())
      setFresh(created.token)
      setName('')
      load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    }
  }

  const base = location.origin

  return (
    <Card size="small" title="开放接口(收银系统/POS 对接)">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="用收银系统的商家可以用它自动拉单,不用两块屏抄单"
        description={
          <div style={{ fontSize: 12, lineHeight: 1.8 }}>
            当前版本<b>只读</b>(查店铺信息、拉订单),不能接单或改价。<br />
            调用方式:请求头带 <code>Authorization: Bearer 你的Key</code><br />
            · 店铺信息 <code>GET {base}/open/v1/shop</code><br />
            · 拉订单 <code>GET {base}/open/v1/orders?since=上次拉到的时间&amp;limit=50</code><br />
            顾客手机号按商家视角脱敏,与你在 App 里看到的一致。
          </div>
        }
      />
      {fresh && (
        <Alert
          type="success"
          showIcon
          closable
          onClose={() => setFresh('')}
          style={{ marginBottom: 12 }}
          message="Key 已生成——只显示这一次,请立即复制保存"
          description={
            <Space>
              <Input.Password readOnly value={fresh} style={{ width: 380 }} />
              <Button size="small" onClick={() => {
                navigator.clipboard?.writeText(fresh)
                message.success('已复制')
              }}>复制</Button>
            </Space>
          }
        />
      )}
      <Space style={{ marginBottom: 12 }} wrap>
        <Input value={name} placeholder="备注(如 收银台1)" maxLength={30}
          style={{ width: 180 }} onChange={(e) => setName(e.target.value)} />
        <Button type="primary" onClick={create}>生成新 Key</Button>
      </Space>
      <Table<ApiKey>
        rowKey="id"
        dataSource={keys}
        size="small"
        pagination={false}
        columns={[
          { title: '备注', dataIndex: 'name', render: (v) => v || '—' },
          { title: 'Key', dataIndex: 'prefix', render: (v) => `${v}…` },
          {
            title: '状态',
            render: (_, k) => k.revoked
              ? <Tag>已吊销</Tag>
              : <Tag color="green">有效</Tag>,
          },
          {
            title: '创建时间',
            dataIndex: 'created_at',
            render: (v: string) => new Date(v).toLocaleString('zh-CN'),
          },
          {
            title: '操作',
            render: (_, k) => k.revoked ? null : (
              <Button size="small" danger onClick={async () => {
                try {
                  await revokeApiKey(k.id)
                  message.success('已吊销')
                  load()
                } catch (e) {
                  message.error(e instanceof ApiError ? e.message : String(e))
                }
              }}>
                吊销
              </Button>
            ),
          },
        ]}
      />
      <ApiUsagePanel />
    </Card>
  )
}

/**
 * 用量与调用日志。
 *
 * ## 错误率和限流分开报
 *
 * 它们要做的事完全不同:错误率高多半是集成写错了(看日志改代码),
 * 限流高是调得太密(改成退避重试)。混成一个「失败率」两边都指导不了。
 *
 * ## 「一条都没有」是有含义的
 *
 * 认得出是谁的失败会记(Key 被吊销、店铺被停用);完全不认识的 Key 不记
 * —— 否则任何人拿垃圾请求就能撑爆这张表。所以空列表要说清这一点,
 * 否则接入方会以为是页面坏了。
 */
function ApiUsagePanel() {
  const [usage, setUsage] = useState<ApiUsage | null>(null)
  const [logs, setLogs] = useState<ApiLogRow[]>([])
  const [onlyErrors, setOnlyErrors] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    try {
      const [u, l] = await Promise.all([myApiUsage(7), myApiLogs(onlyErrors)])
      setUsage(u)
      setLogs(l.items)
      setErr('')
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    }
  }, [onlyErrors])
  useEffect(() => { void load() }, [load])

  if (err) {
    return <Alert type="error" showIcon message={err} style={{ marginTop: 16 }} />
  }
  if (!usage) return null

  return (
    <div style={{ marginTop: 20 }}>
      <Space size={24} wrap style={{ marginBottom: 12 }}>
        <Statistic title="近 7 天调用" value={usage.total} />
        <Statistic
          title="错误率"
          value={usage.total ? usage.error_ratio * 100 : 0}
          precision={1}
          suffix="%"
          valueStyle={usage.error_ratio > 0.05 ? { color: '#cf1322' } : undefined}
        />
        <Statistic
          title="被限流"
          value={usage.throttled}
          valueStyle={usage.throttled ? { color: '#d46b08' } : undefined}
        />
        <Statistic title="平均耗时" value={usage.avg_ms} suffix="ms" />
      </Space>
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
             message={usage.note} />
      <Space style={{ marginBottom: 8 }}>
        <Switch checked={onlyErrors} onChange={setOnlyErrors}
                checkedChildren="只看出错" unCheckedChildren="全部" />
        <Button size="small" onClick={() => void load()}>刷新</Button>
      </Space>
      <Table<ApiLogRow>
        size="small"
        rowKey={(r) => `${r.at}-${r.path}-${r.status}`}
        dataSource={logs}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{
          emptyText: onlyErrors
            ? '近期没有出错的调用'
            : '还没有调用记录。如果你确实调过,说明这把 Key 没被认出来'
              + '(打错了,或者不是这个环境的)—— 完全不认识的 Key 不留记录。',
        }}
        columns={[
          {
            title: '时间', dataIndex: 'at',
            render: (v: string | null) =>
              v ? v.slice(0, 19).replace('T', ' ') : '—',
          },
          { title: '方法', dataIndex: 'method', width: 70 },
          { title: '路径', dataIndex: 'path' },
          {
            title: '状态', dataIndex: 'status', width: 80,
            render: (v: number) => (
              <Tag color={v >= 500 ? 'red' : v === 429 ? 'orange'
                : v >= 400 ? 'gold' : 'green'}>{v}</Tag>
            ),
          },
          {
            title: '耗时', dataIndex: 'duration_ms', width: 80,
            render: (v: number) => `${v}ms`,
          },
        ]}
      />
      <div style={{ fontSize: 12, color: '#888', marginTop: 8 }}>
        日志不含请求体和响应体 —— 那里面有顾客的地址和手机号。
      </div>
    </div>
  )
}
