import { DeleteOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons'
import {
  Alert, AutoComplete, Button, Card, DatePicker, Form, Input, Modal,
  Popconfirm, Space, Table, Tag, Tooltip, Upload, message,
} from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'

import {
  addPurchase, ApiError, deletePurchase, purchaseSuppliers, purchases,
  PurchaseRecord, SupplierRow, UPLOAD_ACCEPT, uploadImage,
} from '../api'

/**
 * 进货查验台账(食品溯源)。
 *
 * 《食品安全法》五十三条要求记录食品名称、规格、数量、生产日期或批号、
 * 保质期、进货日期、供货者名称/地址/联系方式并保存凭证;留存期不少于
 * 保质期满后六个月(没有明确保质期的两年)。
 *
 * 这是餐饮小商家普遍不做、而出事时**唯一能自证清白**的东西。所以界面的
 * 全部设计压力都在一件事上:**让人真的愿意录第二次、第三次**。
 * - 只有食材名和进货日期必填,其余缺了当场列出来但不拦;
 * - 供货商可从用过的里选,一选带出地址与电话;
 * - 留存到期日平台替你算。
 */
export default function PurchasesPage() {
  const [items, setItems] = useState<PurchaseRecord[]>([])
  const [note, setNote] = useState('')
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [suppliers, setSuppliers] = useState<SupplierRow[]>([])

  const load = useCallback(async (keyword?: string) => {
    setLoading(true)
    try {
      const r = await purchases(keyword || undefined)
      setItems(r.items)
      setNote(r.note)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    purchaseSuppliers().then(setSuppliers).catch(() => { /* 静默 */ })
  }, [load])

  return (
    <Card
      title="进货查验台账"
      extra={
        <Space>
          <Input.Search
            allowClear
            placeholder="按食材名反查,如:牛腩"
            style={{ width: 220 }}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onSearch={(v) => load(v)}
            enterButton={<SearchOutlined />}
          />
          <Button type="primary" icon={<PlusOutlined />}
            onClick={() => setOpen(true)}>录一笔进货</Button>
        </Space>
      }
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 12 }}
        message="出事时,这本台账是唯一能自证清白的东西"
        description={
          <>
            「这批肉是谁供的、什么时候进的、票在哪」——
            答不上来就只能自己扛。按食材名一搜就能反查到供货商、批号和进货日。
            <br />
            只有<b>食材名</b>和<b>进货日期</b>必填;其余缺了会列出来提醒，但不拦你先记下。
          </>
        }
      />
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={items}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        locale={{
          emptyText: q ? `没有找到「${q}」的进货记录` : '还没有进货记录',
        }}
        columns={[
          {
            title: '食材', dataIndex: 'name', width: 150,
            render: (v: string, r) => (
              <div>
                <div style={{ fontWeight: 500 }}>{v}</div>
                {(r.spec || r.qty) && (
                  <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)' }}>
                    {[r.spec, r.qty].filter(Boolean).join(' · ')}
                  </div>
                )}
              </div>
            ),
          },
          { title: '进货日期', dataIndex: 'purchased_on', width: 110 },
          {
            title: '生产日期/批号', width: 140,
            render: (_, r) => r.produced_on || r.batch_no || '—',
          },
          {
            title: '保质期至', dataIndex: 'shelf_life_end', width: 110,
            render: (v: string | null) => v ?? <Tag>未填</Tag>,
          },
          {
            title: '供货商', width: 200,
            render: (_, r) => r.supplier_name ? (
              <Tooltip title={
                <>
                  {r.supplier_address || '（未填地址）'}
                  <br />{r.supplier_phone || '（未填电话）'}
                </>
              }>
                <span>{r.supplier_name}</span>
              </Tooltip>
            ) : <Tag color="orange">未填</Tag>,
          },
          {
            title: '凭证', width: 90,
            render: (_, r) => (
              <Space size={4}>
                {r.receipt_url
                  ? <Tag color="green">票据</Tag>
                  : <Tag color="orange">缺票据</Tag>}
                {r.supplier_license_url && <Tag color="green">资质</Tag>}
              </Space>
            ),
          },
          {
            title: '最短留存到', dataIndex: 'keep_until', width: 120,
            render: (v: string) => (
              <Tooltip title="保质期满后六个月;没有明确保质期的两年。平台不会替你删。">
                <span style={{ color: 'var(--sz-ink-muted)' }}>{v}</span>
              </Tooltip>
            ),
          },
          {
            title: '', width: 50,
            render: (_, r) => (
              <Popconfirm
                title="删掉这条记录?"
                description="只用来删录错的 —— 到了最短留存期平台也不会自动删。"
                onConfirm={async () => {
                  try {
                    await deletePurchase(r.id)
                    message.success('已删除')
                    load(q)
                  } catch (e) {
                    message.error(e instanceof ApiError ? e.message : String(e))
                  }
                }}
              >
                <Button type="text" danger size="small"
                  icon={<DeleteOutlined />} />
              </Popconfirm>
            ),
          },
        ]}
      />
      <div style={{ marginTop: 12, color: 'var(--sz-ink-muted)', fontSize: 12 }}>{note}</div>
      <PurchaseModal
        open={open}
        suppliers={suppliers}
        onClose={() => setOpen(false)}
        onDone={() => {
          setOpen(false)
          load(q)
          purchaseSuppliers().then(setSuppliers).catch(() => {})
        }}
      />
    </Card>
  )
}

function PurchaseModal(
  { open, suppliers, onClose, onDone }: {
    open: boolean
    suppliers: SupplierRow[]
    onClose: () => void
    onDone: () => void
  },
) {
  const [form] = Form.useForm()
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) form.setFieldsValue({ purchased_on: dayjs() })
  }, [open, form])

  return (
    <Modal
      open={open} title="录一笔进货" okText="保存" width={640}
      confirmLoading={busy}
      onCancel={onClose}
      onOk={async () => {
        const v = await form.validateFields()
        setBusy(true)
        try {
          const r = await addPurchase({
            name: v.name, spec: v.spec, qty: v.qty,
            batch_no: v.batch_no,
            produced_on: v.produced_on?.format('YYYY-MM-DD'),
            shelf_life_end: v.shelf_life_end?.format('YYYY-MM-DD'),
            purchased_on: v.purchased_on.format('YYYY-MM-DD'),
            supplier_name: v.supplier_name,
            supplier_address: v.supplier_address,
            supplier_phone: v.supplier_phone,
            supplier_license_url: v.supplier_license_url,
            receipt_url: v.receipt_url,
            note: v.note,
          })
          if (r.missing?.length) {
            // 缺项不拦,但说清楚 —— 这本台账最大的敌人是根本没人填,
            // 不是填得不全
            message.warning(
              `已保存。还缺:${r.missing.join('、')}（可稍后补录）`, 6)
          } else {
            message.success(`已保存,这条至少留到 ${r.keep_until}`)
          }
          form.resetFields()
          onDone()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
        } finally {
          setBusy(false)
        }
      }}
    >
      <Form form={form} layout="vertical">
        <Space style={{ display: 'flex' }} align="start">
          <Form.Item name="name" label="食材名称"
            rules={[{ required: true, message: '填食材名称' }]}
            style={{ flex: 2 }}
            extra="出事时按这个名字反查,写日常叫法就行">
            <Input maxLength={60} placeholder="如:牛腩" />
          </Form.Item>
          <Form.Item name="spec" label="规格" style={{ flex: 1 }}>
            <Input maxLength={40} placeholder="如:冷鲜/10kg" />
          </Form.Item>
          <Form.Item name="qty" label="数量" style={{ flex: 1 }}>
            <Input maxLength={30} placeholder="如:2 箱" />
          </Form.Item>
        </Space>
        <Space style={{ display: 'flex' }} align="start">
          <Form.Item name="purchased_on" label="进货日期"
            rules={[{ required: true, message: '填进货日期' }]}
            style={{ flex: 1 }}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="produced_on" label="生产日期" style={{ flex: 1 }}
            extra="生产日期和批号有一个即可">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="batch_no" label="生产批号" style={{ flex: 1 }}>
            <Input maxLength={40} />
          </Form.Item>
          <Form.Item name="shelf_life_end" label="保质期至" style={{ flex: 1 }}
            extra="留存期按它算">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Space>
        <Form.Item name="supplier_name" label="供货商名称"
          extra="选用过的会自动带出地址与电话">
          <AutoComplete
            options={suppliers.map((s) => ({ value: s.name }))}
            filterOption={(input, option) =>
              (option?.value as string).includes(input)}
            onSelect={(v) => {
              const s = suppliers.find((x) => x.name === v)
              if (s) {
                form.setFieldsValue({
                  supplier_address: s.address,
                  supplier_phone: s.phone,
                  supplier_license_url: s.license_url,
                })
              }
            }}
          >
            <Input maxLength={60} placeholder="如:蓉城冻品有限公司" />
          </AutoComplete>
        </Form.Item>
        <Space style={{ display: 'flex' }} align="start">
          <Form.Item name="supplier_address" label="供货商地址"
            style={{ flex: 2 }}>
            <Input maxLength={120} />
          </Form.Item>
          <Form.Item name="supplier_phone" label="联系方式" style={{ flex: 1 }}>
            <Input maxLength={20} />
          </Form.Item>
        </Space>
        <Space align="start" size={24}>
          <Form.Item name="receipt_url" label="进货票据照片">
            <ProofImage />
          </Form.Item>
          <Form.Item name="supplier_license_url" label="供货商资质照片"
            extra="第五十三条要求查验供货者许可证">
            <ProofImage />
          </Form.Item>
        </Space>
        <Form.Item name="note" label="备注">
          <Input maxLength={200} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** 票据与供货商资质都走私密桶(别人的营业执照、含价格的票据)。
 *  purpose 用 'license' —— storage.PURPOSES 里它是私密的。 */
function ProofImage(
  { value, onChange }: { value?: string; onChange?: (v: string) => void },
) {
  return (
    <Upload
      listType="picture-card"
      maxCount={1}
      accept={UPLOAD_ACCEPT}
      fileList={value
        ? [{ uid: '1', name: '凭证', status: 'done' as const, url: value }]
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
