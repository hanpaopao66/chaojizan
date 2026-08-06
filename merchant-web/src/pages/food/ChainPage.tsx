import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import {
  Alert, Button, Card, Empty, Form, Input, InputNumber, Modal, Popconfirm,
  Select, Space, Statistic, Table, Tag, Upload, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  addBrandMember, ApiError, BrandMemberRow, BrandOverview, BrandShop,
  brandMembers, brandOverview, createBrand, Merchant, MyBrand, myBrand,
  brandFinance, BrandFinance, downloadFile, openBrandShop, removeBrandMember,
  switchShop, syncBrandCoupons, syncBrandMenu, syncBrandPromo, UPLOAD_ACCEPT,
  uploadImage, yuan,
} from '../../api'

/**
 * 连锁店群(总部视角)。
 *
 * 三条写死在界面上的规矩,是为了让老板在点之前就知道:
 * 1. **新门店证照不能复用** —— 食品经营许可证按门店核发,不是品牌资质。
 *    界面上不提供"沿用总部证照"这个选项,不是藏起来了,是根本没有。
 * 2. **抄菜单不抄库存** —— 新店还没进货,抄了等于一开门就超卖。
 * 3. **各店的数与他们自己看到的一致** —— 总部不看门店看不到的指标,
 *    否则店长会觉得自己在被暗中打分。
 */
export default function ChainPage({ shop }: { shop: Merchant }) {
  const [brand, setBrand] = useState<MyBrand | null>(null)
  const [overview, setOverview] = useState<BrandOverview | null>(null)
  const [members, setMembers] = useState<BrandMemberRow[]>([])
  const [days, setDays] = useState(7)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const b = await myBrand()
      setBrand(b)
      if (b.brand) {
        setOverview(await brandOverview(days))
        if (b.brand.is_owner) setMembers(await brandMembers())
      }
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { load() }, [load])

  if (loading && !brand) return <Card loading />

  // ---- 还没建品牌:先讲清楚建了之后会怎样,再给按钮 ----
  if (!brand?.brand) {
    return (
      <Card title="连锁店群">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <div style={{ textAlign: 'left', maxWidth: 560, margin: '0 auto' }}>
              <p>把现在这家店升级成<b>品牌总部</b>之后,你可以:</p>
              <ul>
                <li>一处看完所有门店的单量、营业额、未回差评</li>
                <li>开新门店时直接抄这家的菜单(不抄库存)</li>
                <li>把菜价、描述一次同步到指定的几家店</li>
                <li>请区域经理帮你管几家店,不用把账号密码给别人</li>
              </ul>
              <p style={{ color: '#8c8c8c' }}>
                新门店仍要各自提交证照并照走审核 ——
                食品经营许可证按门店核发,总部的不能给分店用。
              </p>
            </div>
          }
        >
          <CreateBrandButton shopName={shop.name} shopId={shop.id}
            onDone={load} />
        </Empty>
      </Card>
    )
  }

  const isOwner = brand.brand.is_owner

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={`${brand.brand.name} · ${overview?.total.shops ?? 0} 家门店`}
        extra={
          <Space>
            <Select
              size="small" value={days} onChange={setDays}
              options={[
                { value: 1, label: '今天' },
                { value: 7, label: '近 7 天' },
                { value: 30, label: '近 30 天' },
              ]}
            />
            {isOwner && <SyncMenuButton shops={brand.shops} />}
            {isOwner && <SyncPromoButton shops={brand.shops} />}
            {isOwner && <SyncCouponsButton shops={brand.shops} />}
            {isOwner && (
              <NewShopButton shops={brand.shops} onDone={load} />
            )}
          </Space>
        }
      >
        {overview && (
          <>
            <Space size={48} style={{ marginBottom: 16 }}>
              <Statistic title="门店" value={overview.total.shops} />
              <Statistic title="订单" value={overview.total.orders} />
              <Statistic title="营业额"
                value={yuan(overview.total.net_cents)} />
              <Statistic title="未回差评"
                value={overview.total.bad_unreplied}
                valueStyle={overview.total.bad_unreplied > 0
                  ? { color: '#cf1322' } : undefined} />
            </Space>
            <Table
              rowKey="shop_id"
              size="small"
              dataSource={overview.shops}
              pagination={false}
              columns={[
                {
                  title: '门店', dataIndex: 'name',
                  render: (name: string, r) => (
                    <Space>
                      <a onClick={() => switchShop(r.shop_id)}>{name}</a>
                      {r.shop_id === shop.id && <Tag color="orange">当前</Tag>}
                      {r.status !== 'approved' && <Tag color="gold">审核中</Tag>}
                      {r.status === 'approved' && !r.is_open && <Tag>打烊</Tag>}
                    </Space>
                  ),
                },
                { title: '订单', dataIndex: 'orders', width: 90 },
                {
                  title: '营业额', dataIndex: 'net_cents', width: 120,
                  render: (v: number) => yuan(v),
                },
                {
                  title: '出餐超时', dataIndex: 'ready_late', width: 100,
                  render: (v: number) => v > 0
                    ? <span style={{ color: '#cf1322' }}>{v}</span> : v,
                },
                {
                  title: '评分', dataIndex: 'rating_avg', width: 90,
                  render: (v: number | null) => v ?? '—',
                },
                {
                  title: '未回差评', dataIndex: 'bad_unreplied', width: 100,
                  render: (v: number) => v > 0
                    ? <span style={{ color: '#cf1322' }}>{v}</span> : v,
                },
              ]}
            />
            <div style={{ marginTop: 12, color: '#8c8c8c', fontSize: 12 }}>
              {overview.note}
            </div>
          </>
        )}
      </Card>

      {isOwner && <BrandFinanceCard days={days} />}

      {isOwner && (
        <Card
          title="区域经理"
          extra={<AddMemberButton shops={brand.shops} onDone={load} />}
        >
          <Alert
            type="info" showIcon style={{ marginBottom: 12 }}
            message="区域经理能管你指定的那几家店,但拿不到提现和收款账户 —— 钱只走品牌所有者。"
          />
          <Table
            rowKey="id"
            size="small"
            dataSource={members}
            pagination={false}
            locale={{ emptyText: '还没有区域经理,你自己管着全部门店' }}
            columns={[
              { title: '姓名', dataIndex: 'name' },
              { title: '手机号', dataIndex: 'phone', width: 140 },
              {
                title: '管辖门店', dataIndex: 'shop_ids',
                render: (ids: number[]) => ids.length === 0
                  ? <Tag color="blue">全部门店</Tag>
                  : ids.map((id) => (
                    <Tag key={id}>
                      {brand.shops.find((s) => s.id === id)?.name ?? `#${id}`}
                    </Tag>
                  )),
              },
              {
                title: '', width: 60,
                render: (_, r) => (
                  <Popconfirm
                    title="移出品牌?"
                    description="移出后立即失去所有门店的操作权限。"
                    onConfirm={async () => {
                      try {
                        await removeBrandMember(r.id)
                        message.success('已移出')
                        load()
                      } catch (e) {
                        message.error(e instanceof ApiError
                          ? e.message : String(e))
                      }
                    }}
                  >
                    <Button type="text" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                ),
              },
            ]}
          />
        </Card>
      )}
    </Space>
  )
}

function CreateBrandButton(
  { shopName, shopId, onDone }:
  { shopName: string; shopId: number; onDone: () => void },
) {
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  return (
    <>
      <Button type="primary" onClick={() => setOpen(true)}>
        把「{shopName}」升级为品牌总部
      </Button>
      <Modal
        open={open} title="创建品牌" okText="创建"
        onCancel={() => setOpen(false)}
        onOk={async () => {
          const v = await form.validateFields()
          try {
            await createBrand(v.name, shopId)
            message.success('品牌已创建')
            setOpen(false)
            onDone()
          } catch (e) {
            message.error(e instanceof ApiError ? e.message : String(e))
          }
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name" label="品牌名"
            rules={[{ required: true, min: 2, message: '品牌名至少 2 个字' }]}
            extra="用户端看到的仍是各门店自己的店名,品牌名只用在你的后台。"
          >
            <Input placeholder="如:赞小碗" maxLength={50} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

function NewShopButton(
  { shops, onDone }: { shops: BrandShop[]; onDone: () => void },
) {
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const inBrand = shops.filter((s) => s.in_brand)
  return (
    <>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
        开新门店
      </Button>
      <Modal
        open={open} title="开一家新门店" okText="提交审核" width={640}
        onCancel={() => setOpen(false)}
        onOk={async () => {
          const v = await form.validateFields()
          try {
            await openBrandShop({
              copy_from: v.copy_from, name: v.name, address: v.address,
              lat: v.lat, lng: v.lng,
              license_no: v.license_no,
              license_image_url: v.license_image_url,
            })
            message.success('已提交,平台核验证照后自动开通')
            setOpen(false)
            form.resetFields()
            onDone()
          } catch (e) {
            message.error(e instanceof ApiError ? e.message : String(e))
          }
        }}
      >
        <Alert
          type="warning" showIcon style={{ marginBottom: 16 }}
          message="新门店必须提交自己的证照"
          description={
            <>
              食品经营许可证<b>按门店核发</b>,总部或其他门店的证照不能复用 ——
              这是法定要求,不是平台的规定。新店照走人工核验,与任何一家新店一视同仁。
              <br />
              菜品、分类、营业时间会从参照门店抄一份;
              <b>库存不抄</b>(新店还没进货,抄了等于一开门就超卖)。
            </>
          }
        />
        <Form form={form} layout="vertical">
          <Form.Item
            name="copy_from" label="参照门店(抄它的菜单)"
            rules={[{ required: true, message: '选一家参照门店' }]}
          >
            <Select options={inBrand.map((s) => (
              { value: s.id, label: s.name }))} />
          </Form.Item>
          <Form.Item name="name" label="新门店名称"
            rules={[{ required: true, message: '填门店名称' }]}>
            <Input placeholder="如:赞小碗(高新店)" maxLength={50} />
          </Form.Item>
          <Form.Item name="address" label="门店地址"
            rules={[{ required: true, message: '填门店地址' }]}>
            <Input placeholder="街道门牌号" maxLength={200} />
          </Form.Item>
          <Space>
            <Form.Item name="lat" label="纬度"
              rules={[{ required: true, message: '填纬度' }]}>
              <InputNumber step={0.0001} style={{ width: 160 }} />
            </Form.Item>
            <Form.Item name="lng" label="经度"
              rules={[{ required: true, message: '填经度' }]}>
              <InputNumber step={0.0001} style={{ width: 160 }} />
            </Form.Item>
          </Space>
          <Form.Item name="license_no" label="食品经营许可证编号"
            rules={[{ required: true, message: '填这家店的许可证编号' }]}>
            <Input placeholder="这家店自己的编号" maxLength={64} />
          </Form.Item>
          <Form.Item
            name="license_image_url" label="食品经营许可证照片"
            rules={[{ required: true, message: '上传这家店的许可证照片' }]}
          >
            <LicenseField />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

/**
 * 跨店对账汇总。
 *
 * **只读,不做品牌级钱包** —— 钱一旦在总部合并,门店就说不清自己那份
 * 对不对,而「每一笔分账可查可申诉」是平台写在规则中心里的承诺。
 * 资金仍按门店结算、按门店提现;这里只是省去逐店点进去看。
 */
function BrandFinanceCard({ days }: { days: number }) {
  const [data, setData] = useState<BrandFinance | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    brandFinance(days)
      .then(setData)
      .catch(() => { /* 概览已经展示了,对账拉不到不该整页报错 */ })
      .finally(() => setLoading(false))
  }, [days])

  if (!loading && !data) return null
  return (
    <Card
      title="跨店对账"
      loading={loading}
      extra={
        <Button size="small" onClick={() => downloadFile(
          `/brands/me/finance.csv?days=${days}`,
          `brand-finance-${days}d.csv`)}>导出 CSV</Button>
      }
    >
      {data && (
        <>
          <Table
            rowKey="shop_id"
            size="small"
            dataSource={data.shops}
            pagination={false}
            summary={() => (
              <Table.Summary.Row style={{ fontWeight: 600 }}>
                <Table.Summary.Cell index={0}>合计</Table.Summary.Cell>
                <Table.Summary.Cell index={1}>
                  {data.total.orders}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={2}>
                  {yuan(data.total.gross_cents)}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={3}>
                  {yuan(data.total.commission_cents)}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={4}>
                  {yuan(data.total.net_cents)}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={5} />
              </Table.Summary.Row>
            )}
            columns={[
              { title: '门店', dataIndex: 'name' },
              { title: '订单', dataIndex: 'orders', width: 90 },
              {
                title: '流水', dataIndex: 'gross_cents', width: 120,
                render: (v: number) => yuan(v),
              },
              {
                title: '平台佣金', dataIndex: 'commission_cents', width: 120,
                render: (v: number) => yuan(v),
              },
              {
                title: '实得', dataIndex: 'net_cents', width: 120,
                render: (v: number) => (
                  <span style={{ fontWeight: 500 }}>{yuan(v)}</span>),
              },
              {
                title: '实际费率', dataIndex: 'effective_rate', width: 100,
                render: (v: number) => `${(v * 100).toFixed(2)}%`,
              },
            ]}
          />
          <div style={{ marginTop: 12, color: '#8c8c8c', fontSize: 12 }}>
            {data.note}
          </div>
        </>
      )}
    </Card>
  )
}

/** 满减下发。下发后门店仍可自己改 —— 满减的钱是门店出的。 */
function SyncPromoButton({ shops }: { shops: BrandShop[] }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()
  const inBrand = shops.filter((s) => s.in_brand)
  return (
    <>
      <Button onClick={() => setOpen(true)}>满减下发</Button>
      <Modal
        open={open} title="把满减下发到其他门店" okText="下发"
        confirmLoading={busy}
        onCancel={() => setOpen(false)}
        onOk={async () => {
          const v = await form.validateFields()
          setBusy(true)
          try {
            const r = await syncBrandPromo(v.from_shop, v.to_shops)
            message.success(`已下发 ${r.rules} 个档位到 ${r.shops.length} 家店`)
            setOpen(false)
          } catch (e) {
            message.error(e instanceof ApiError ? e.message : String(e))
          } finally {
            setBusy(false)
          }
        }}
      >
        <Alert
          type="info" showIcon style={{ marginBottom: 16 }}
          message="下发之后门店仍然可以自己改"
          description="满减的钱是门店出的(结算时从门店实收里扣),最终决定权在他们手上。总部能做的是把模板推过去,省得每家重录一遍。"
        />
        <Form form={form} layout="vertical">
          <Form.Item name="from_shop" label="以哪家店的满减为准"
            rules={[{ required: true, message: '选源门店' }]}>
            <Select options={inBrand.map((s) => (
              { value: s.id, label: s.name }))} />
          </Form.Item>
          <Form.Item name="to_shops" label="下发到"
            rules={[{ required: true, message: '至少选一家目标门店' }]}>
            <Select mode="multiple" allowClear placeholder="可多选"
              options={inBrand.map((s) => ({ value: s.id, label: s.name }))} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

/** 券下发:各店各建一个批次,各出各的。 */
function SyncCouponsButton({ shops }: { shops: BrandShop[] }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()
  const inBrand = shops.filter((s) => s.in_brand)
  return (
    <>
      <Button onClick={() => setOpen(true)}>券下发</Button>
      <Modal
        open={open} title="给多家门店发同一种券" okText="下发"
        confirmLoading={busy}
        onCancel={() => setOpen(false)}
        onOk={async () => {
          const v = await form.validateFields()
          setBusy(true)
          try {
            const r = await syncBrandCoupons({
              name: v.name,
              to_shops: v.to_shops,
              threshold_cents: Math.round(v.threshold * 100),
              off_cents: Math.round(v.off * 100),
              total: v.total,
              valid_days: v.valid_days,
            })
            message.success(
              `${r.shops.length} 家店各建了一个批次,各发 ${r.total_per_shop} 张`)
            setOpen(false)
            form.resetFields()
          } catch (e) {
            message.error(e instanceof ApiError ? e.message : String(e))
          } finally {
            setBusy(false)
          }
        }}
      >
        <Alert
          type="warning" showIcon style={{ marginBottom: 16 }}
          message="各店各建一个批次,各发各的、各自承担成本"
          description="不是几家店分一个总额。券的钱由发券的那家门店全额承担 —— 共用预算就变成「我店的钱被别店花了」,门店对不上自己那份账。门店可以自己停掉自己那个批次。"
        />
        <Form form={form} layout="vertical"
          initialValues={{ valid_days: 7, total: 100 }}>
          <Form.Item name="name" label="券名称"
            rules={[{ required: true, min: 2, message: '券名称至少 2 个字' }]}>
            <Input maxLength={50} placeholder="如:新店开业券" />
          </Form.Item>
          <Space>
            <Form.Item name="threshold" label="门槛(元)"
              rules={[{ required: true, message: '填门槛' }]}>
              <InputNumber min={0.01} style={{ width: 130 }} />
            </Form.Item>
            <Form.Item name="off" label="面额(元)"
              rules={[{ required: true, message: '填面额' }]}
              extra="必须小于门槛(不能倒贴)">
              <InputNumber min={0.01} style={{ width: 130 }} />
            </Form.Item>
            <Form.Item name="total" label="每店发放量"
              rules={[{ required: true, message: '填每店发放量' }]}
              extra="每家各发这么多">
              <InputNumber min={1} max={100000} style={{ width: 130 }} />
            </Form.Item>
            <Form.Item name="valid_days" label="有效期(天)"
              rules={[{ required: true, message: '填有效期' }]}>
              <InputNumber min={1} max={90} style={{ width: 110 }} />
            </Form.Item>
          </Space>
          <Form.Item name="to_shops" label="下发到"
            rules={[{ required: true, message: '至少选一家目标门店' }]}>
            <Select mode="multiple" allowClear placeholder="可多选"
              options={inBrand.map((s) => ({ value: s.id, label: s.name }))} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

/** 菜单下发:把一家店的在售菜应用到另外几家。库存与上下架不覆盖。 */
function SyncMenuButton({ shops }: { shops: BrandShop[] }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()
  const inBrand = shops.filter((s) => s.in_brand)
  return (
    <>
      <Button onClick={() => setOpen(true)}>菜单下发</Button>
      <Modal
        open={open} title="把菜单下发到其他门店" okText="下发"
        confirmLoading={busy}
        onCancel={() => setOpen(false)}
        onOk={async () => {
          const v = await form.validateFields()
          setBusy(true)
          try {
            const r = await syncBrandMenu(v.from_shop, v.to_shops)
            const created = r.results.reduce((a, x) => a + x.created, 0)
            const updated = r.results.reduce((a, x) => a + x.updated, 0)
            message.success(`已下发:新建 ${created} 道、更新 ${updated} 道`)
            setOpen(false)
          } catch (e) {
            message.error(e instanceof ApiError ? e.message : String(e))
          } finally {
            setBusy(false)
          }
        }}
      >
        <Alert
          type="info" showIcon style={{ marginBottom: 16 }}
          message="库存与上下架状态不会被覆盖"
          description="那是各店当天的经营决策(今天这道菜的料没了,总部在几百公里外不知道)。按菜名匹配:同名的更新价格/描述/标签/规格,没有的新建(库存 0)。"
        />
        <Form form={form} layout="vertical">
          <Form.Item name="from_shop" label="以哪家店为准"
            rules={[{ required: true, message: '选源门店' }]}>
            <Select options={inBrand.map((s) => (
              { value: s.id, label: s.name }))} />
          </Form.Item>
          <Form.Item name="to_shops" label="下发到"
            rules={[{ required: true, message: '至少选一家目标门店' }]}>
            <Select mode="multiple" allowClear placeholder="可多选"
              options={inBrand.map((s) => ({ value: s.id, label: s.name }))} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

function AddMemberButton(
  { shops, onDone }: { shops: BrandShop[]; onDone: () => void },
) {
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  return (
    <>
      <Button icon={<PlusOutlined />} onClick={() => setOpen(true)}>
        添加区域经理
      </Button>
      <Modal
        open={open} title="添加区域经理" okText="添加"
        onCancel={() => setOpen(false)}
        onOk={async () => {
          const v = await form.validateFields()
          try {
            await addBrandMember(v.phone, v.shop_ids ?? [])
            message.success('已添加')
            setOpen(false)
            form.resetFields()
            onDone()
          } catch (e) {
            message.error(e instanceof ApiError ? e.message : String(e))
          }
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="phone" label="手机号"
            rules={[{ required: true, pattern: /^1\d{10}$/, message: '填 11 位手机号' }]}
            extra="对方需先用「超级赞商家」App 或网页版登录过一次 —— 我们不替人开账号。"
          >
            <Input placeholder="11 位手机号" maxLength={11} />
          </Form.Item>
          <Form.Item
            name="shop_ids" label="管辖门店"
            extra="不选 = 管全部门店(含以后新开的)。"
          >
            <Select
              mode="multiple" allowClear placeholder="不选则管全部门店"
              options={shops.filter((s) => s.in_brand)
                .map((s) => ({ value: s.id, label: s.name }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

/**
 * 证照上传(Form.Item 受控)。
 *
 * purpose 必须是 'license' —— 后端按 purpose 决定进公开桶还是私密桶,
 * 证照走私密桶,只有本人和审核员读得到。填错会把营业执照挂到公网上。
 */
function LicenseField(
  { value, onChange }: { value?: string; onChange?: (v: string) => void },
) {
  return (
    <Upload
      listType="picture-card"
      maxCount={1}
      accept={UPLOAD_ACCEPT}
      fileList={value
        ? [{ uid: '1', name: '许可证', status: 'done' as const, url: value }]
        : []}
      showUploadList={{ showPreviewIcon: false }}
      customRequest={async ({ file, onSuccess, onError, onProgress }) => {
        try {
          const url = await uploadImage(file as File, 'license',
            (percent) => onProgress?.({ percent }))
          onChange?.(url)
          onSuccess?.(url)
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
          onError?.(e as Error)
        }
      }}
      onRemove={() => { onChange?.(''); return true }}
    >
      {!value && <div>+ 上传</div>}
    </Upload>
  )
}
