import {
  Alert, Button, Card, Form, Input, InputNumber, Select, Space, Switch,
  Table, Tag, Upload, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, HotelProfileData, Merchant, StaffMember, addStaff, myHotelProfile,
  myShop, myStaff, removeStaff, restShop, updateHotelProfile, updateShop,
  uploadImage,
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
            customRequest={async ({ file, onSuccess, onError }) => {
              try {
                const url = await uploadImage(file as File)
                setPhotos((prev) => [...prev, url])
                onSuccess?.(url)
              } catch (e) {
                message.error(e instanceof ApiError ? e.message : String(e))
                onError?.(e as Error)
              }
            }}
            onRemove={(file) => setPhotos((prev) => prev.filter((u) => u !== file.url))}
            accept="image/*"
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
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    try {
      await updateShop({
        min_order_cents: Math.round(minOrder * 100),
        packing_fee_cents: Math.round(packing * 100),
        promise_ready_minutes: readyMinutes,
        self_delivery: selfDelivery,
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
          <span style={{ color: '#888', fontSize: 12, marginLeft: 8 }}>
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
        <span style={{ color: '#888', fontSize: 12 }}>
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
