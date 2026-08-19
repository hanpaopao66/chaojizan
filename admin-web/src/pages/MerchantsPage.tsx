import { Alert, Button, Descriptions, Image, Input, Modal, Space, Table, Tabs, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  AdminMerchant, ApiError, approveMerchant, listMerchants, rejectMerchant,
} from '../api'

/**
 * 商家审核。
 *
 * ## 为什么这页排第一
 *
 * 新商家提交入驻之后状态是 `pending` 且 `is_open=false` —— **没人批就永远
 * 开不了张**。在这个界面之前只能 curl,等于每来一家新店都要有人手敲一条命令。
 *
 * ## 为什么驳回必须填理由
 *
 * 理由会原样回到商家端(`reject_reason`),商家照着改了再交。
 * 只写"不合格"的话他不知道改哪,来回三四轮 —— 后端已经限制 2~200 字,
 * 这里也拦一道,免得点了才弹 422。
 */
export default function MerchantsPage() {
  const [status, setStatus] = useState('pending')
  const [rows, setRows] = useState<AdminMerchant[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [detail, setDetail] = useState<AdminMerchant | null>(null)
  const [reason, setReason] = useState('')
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      setRows(await listMerchants(status))
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [status])

  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, ok: string) {
    setActing(true)
    try {
      await fn()
      message.success(ok)
      setDetail(null)
      setReason('')
      await load()
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setActing(false)
    }
  }

  function doReject(m: AdminMerchant) {
    const r = reason.trim()
    if (r.length < 2) {
      message.warning('请写清驳回理由 —— 商家要照着它改')
      return
    }
    void act(() => rejectMerchant(m.id, r), '已驳回,理由已回传给商家')
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Tabs
        activeKey={status}
        onChange={setStatus}
        items={[
          { key: 'pending', label: '待审核' },
          { key: 'approved', label: '已通过' },
          { key: 'rejected', label: '已驳回' },
        ]}
      />
      <Table<AdminMerchant>
        rowKey="id"
        loading={loading}
        dataSource={rows}
        size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '店名', dataIndex: 'name', width: 200 },
          {
            title: '业态', dataIndex: 'biz_type', width: 90,
            render: (v: string) => (
              <Tag color={v === 'hotel' ? 'blue' : 'orange'}>
                {v === 'hotel' ? '住宿' : '餐饮'}
              </Tag>
            ),
          },
          { title: '城市', dataIndex: 'city', width: 90 },
          { title: '地址', dataIndex: 'address', ellipsis: true },
          { title: '店主', dataIndex: 'owner_name', width: 100 },
          { title: '联系电话', dataIndex: 'owner_phone', width: 130 },
          {
            title: '操作', width: 100, fixed: 'right',
            render: (_, m) => (
              <Button type="link" onClick={() => { setDetail(m); setReason('') }}>
                看材料
              </Button>
            ),
          },
        ]}
      />

      <Modal
        open={!!detail}
        title={detail?.name}
        onCancel={() => setDetail(null)}
        width={720}
        footer={detail?.status === 'pending' ? [
          <Button key="reject" danger loading={acting}
                  onClick={() => detail && doReject(detail)}>
            驳回
          </Button>,
          <Button key="ok" type="primary" loading={acting}
                  onClick={() => detail && act(
                    () => approveMerchant(detail.id), '已通过,商家可以开张了')}>
            通过
          </Button>,
        ] : null}
      >
        {detail && (
          <>
            <Descriptions column={2} size="small" bordered
                          style={{ marginBottom: 12 }}>
              <Descriptions.Item label="营业执照号" span={2}>
                {detail.license_no || <span style={{ color: 'var(--sz-ink-muted)' }}>未填</span>}
              </Descriptions.Item>
              <Descriptions.Item label="地址" span={2}>{detail.address}</Descriptions.Item>
              <Descriptions.Item label="城市">{detail.city || '—'}</Descriptions.Item>
              <Descriptions.Item label="品类">{detail.category}</Descriptions.Item>
              <Descriptions.Item label="店主">{detail.owner_name || '—'}</Descriptions.Item>
              <Descriptions.Item label="电话">{detail.owner_phone || '—'}</Descriptions.Item>
              {detail.status === 'rejected' && (
                <Descriptions.Item label="上次驳回理由" span={2}>
                  {detail.reject_reason}
                </Descriptions.Item>
              )}
            </Descriptions>

            {/* 证照图。**要点开看大图** —— 缩略图上根本看不清有效期,
                而过期执照正是最常见的驳回理由 */}
            <Space wrap>
              <Image.PreviewGroup>
                {[
                  ['营业执照', detail.license_image_url],
                  ['特种行业许可', detail.special_license_image_url],
                  ['卫生许可', detail.hygiene_image_url],
                ].filter(([, u]) => u).map(([label, url]) => (
                  <div key={label} style={{ textAlign: 'center' }}>
                    <Image src={url as string} width={150} height={110}
                           style={{ objectFit: 'cover' }} />
                    <div style={{ fontSize: 12, color: 'var(--sz-ink-muted)' }}>
                      {label}
                    </div>
                  </div>
                ))}
              </Image.PreviewGroup>
            </Space>
            {!detail.license_image_url && (
              <Alert type="warning" showIcon style={{ marginTop: 10 }}
                     message="没有上传营业执照 —— 通过之前先让商家补" />
            )}

            {detail.status === 'pending' && (
              <div style={{ marginTop: 16 }}>
                <Input.TextArea
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  maxLength={200}
                  showCount
                  placeholder="驳回理由(会原样回传给商家,写清楚要改什么)"
                />
              </div>
            )}
          </>
        )}
      </Modal>
    </>
  )
}
