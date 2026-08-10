import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import {
  Alert, Button, Card, DatePicker, Form, Input, Modal, Popconfirm, Switch,
  Table, Tag, Upload, message,
} from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, archiveHealthCert, fetchPrivateImage, HealthCert, healthCerts,
  LicenseStage, saveHealthCert, UPLOAD_ACCEPT, uploadImage,
} from '../api'

/**
 * 从业人员健康证台账。
 *
 * 《食品安全法》四十五条:接触直接入口食品的从业人员每年体检、持证上岗。
 * 证一年一换、到期静默失效 —— 监管检查看的是**记录**,
 * 塞在抽屉里翻不出来就是没有。
 *
 * 两条写在界面上的规矩:
 * - **到期只提醒不停业**:证是按人的,一个员工过期停整家店不成比例
 *   (与食品经营许可证过期的后果明确不同,别让商家以为是一回事);
 * - **离职归档不删除**:监管查的是"当时在岗的人有没有证"。
 */
export default function HealthCertsPage() {
  const [items, setItems] = useState<HealthCert[]>([])
  const [note, setNote] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<HealthCert | null | undefined>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await healthCerts(showArchived)
      setItems(r.items)
      setNote(r.note)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [showArchived])

  useEffect(() => { load() }, [load])

  return (
    <Card
      title="从业人员健康证"
      extra={
        <>
          <span style={{ marginRight: 8, fontSize: 13, color: '#8c8c8c' }}>
            显示已离职
          </span>
          <Switch size="small" checked={showArchived}
            onChange={setShowArchived} style={{ marginRight: 12 }} />
          <Button type="primary" icon={<PlusOutlined />}
            onClick={() => setEditing(null)}>
            录入健康证
          </Button>
        </>
      }
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 12 }}
        message="健康证一年一检,到期只提醒、不停业"
        description={
          <>
            证是<b>按人</b>的,一个员工的证过期停整家店不成比例 ——
            这一点和食品经营许可证不同(那张过期超宽限期会暂停营业)。
            <br />
            员工离职请用「归档」而不是删除:监管查的是「当时在岗的人有没有证」。
          </>
        }
      />
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={items}
        pagination={false}
        locale={{ emptyText: '还没有录入健康证' }}
        columns={[
          {
            title: '姓名', dataIndex: 'name', width: 120,
            render: (v: string, r) => (
              <span style={{ opacity: r.archived ? 0.45 : 1 }}>
                {v}{r.archived && <Tag style={{ marginLeft: 6 }}>已离职</Tag>}
              </span>
            ),
          },
          { title: '岗位', dataIndex: 'role', width: 100 },
          { title: '证件号', dataIndex: 'cert_no', width: 180 },
          {
            title: '有效期至', dataIndex: 'expires_at', width: 130,
            render: (v: string | null) => v ?? '—',
          },
          {
            title: '状态', dataIndex: 'stage', width: 140,
            render: (s: LicenseStage, r) => <StageTag stage={s}
              daysLeft={r.days_left} archived={r.archived} />,
          },
          {
            title: '', width: 140,
            render: (_, r) => r.archived ? null : (
              <>
                <Button type="link" size="small"
                  onClick={() => setEditing(r)}>换新证</Button>
                <Popconfirm
                  title="该员工已离职?"
                  description="归档后不再提醒,记录仍保留以备核查。"
                  onConfirm={async () => {
                    try {
                      await archiveHealthCert(r.id)
                      message.success('已归档')
                      load()
                    } catch (e) {
                      message.error(e instanceof ApiError
                        ? e.message : String(e))
                    }
                  }}
                >
                  <Button type="text" danger size="small"
                    icon={<DeleteOutlined />} />
                </Popconfirm>
              </>
            ),
          },
        ]}
      />
      <div style={{ marginTop: 12, color: '#8c8c8c', fontSize: 12 }}>{note}</div>
      <CertModal
        open={editing !== undefined}
        cert={editing ?? null}
        onClose={() => setEditing(undefined)}
        onDone={() => { setEditing(undefined); load() }}
      />
    </Card>
  )
}

function StageTag(
  { stage, daysLeft, archived }:
  { stage: LicenseStage; daysLeft: number | null; archived: boolean },
) {
  if (archived) return <Tag>已离职</Tag>
  switch (stage) {
    case 'unknown': return <Tag>未填有效期</Tag>
    case 'ok': return <Tag color="green">有效</Tag>
    case 'soon': return <Tag color="blue">{daysLeft} 天后到期</Tag>
    case 'urgent':
    case 'last': return <Tag color="orange">{daysLeft} 天后到期</Tag>
    default:
      return <Tag color="red">
        已过期{daysLeft === null ? '' : ` ${-daysLeft} 天`}
      </Tag>
  }
}

function CertModal(
  { open, cert, onClose, onDone }: {
    open: boolean
    cert: HealthCert | null
    onClose: () => void
    onDone: () => void
  },
) {
  const [form] = Form.useForm()
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    // 换新证:姓名与岗位带出来(后端按「同名同岗」认作同一个人,
    // 改了名字就会变成新增一条),其余留空等着填新证的信息
    form.setFieldsValue(cert
      ? { name: cert.name, role: cert.role, cert_no: '', expires_at: null }
      : { name: '', role: '', cert_no: '', expires_at: null })
  }, [open, cert, form])

  return (
    <Modal
      open={open}
      title={cert ? `为「${cert.name}」录入新证` : '录入健康证'}
      okText="保存" confirmLoading={busy}
      onCancel={onClose}
      onOk={async () => {
        const v = await form.validateFields()
        setBusy(true)
        try {
          await saveHealthCert({
            name: v.name,
            role: v.role,
            cert_no: v.cert_no,
            photo_url: v.photo_url,
            issued_at: v.issued_at
              ? v.issued_at.format('YYYY-MM-DD') : undefined,
            expires_at: v.expires_at.format('YYYY-MM-DD'),
          })
          message.success('已保存')
          onDone()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
        } finally {
          setBusy(false)
        }
      }}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="姓名"
          rules={[{ required: true, min: 2, message: '填员工姓名' }]}
          extra={cert ? '姓名与岗位都不变才算「换新证」,改了会新增一条记录。'
            : undefined}>
          <Input maxLength={30} disabled={!!cert} />
        </Form.Item>
        <Form.Item name="role" label="岗位"
          extra="如:后厨 / 配菜 / 传菜 / 前厅。各家叫法不同,按你的习惯填。">
          <Input maxLength={20} disabled={!!cert} />
        </Form.Item>
        <Form.Item name="cert_no" label="健康证编号">
          <Input maxLength={40} placeholder="选填" />
        </Form.Item>
        <Form.Item name="issued_at" label="发证日期(选填)">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item
          name="expires_at" label="有效期至"
          rules={[{ required: true, message: '填有效期至' }]}
          extra="到期提醒靠它。到期前 30 天会提醒你安排体检 —— 体检要排队。"
        >
          <DatePicker style={{ width: '100%' }}
            disabledDate={(d) => d && d < dayjs().startOf('day')} />
        </Form.Item>
        <Form.Item name="photo_url" label="健康证照片(选填)"
          extra="照片存在私密空间,只有你和平台审核员看得到,不会出现在店铺公示页。">
          <CertImage />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** purpose 必须是 'health_cert' —— 后端按 purpose 决定进公开桶还是私密桶。
 *  这是员工本人的个人信息,填错会把别人的健康证挂到公网上。 */
/**
 * 健康证照片。
 *
 * 健康证在私密桶里(`purpose=health_cert`),唯一出口 `GET /files/{key}`
 * 每次都要过鉴权,而 `<img src>` 不带 token —— 之前直接把 URL 塞给
 * Upload 的 fileList,缩略图一律 403 破图,商家传完就再也看不到自己传了什么。
 * 先 fetch 成 blob 再显示,卸载时 revoke。与收款资料页的 SecretImage 同一套路。
 */
function CertImage(
  { value, onChange }: { value?: string; onChange?: (v: string) => void },
) {
  const [preview, setPreview] = useState('')

  useEffect(() => {
    if (!value) { setPreview(''); return }
    let dropped = false
    let objectUrl = ''
    fetchPrivateImage(value)
      .then((u) => {
        if (dropped) { URL.revokeObjectURL(u); return }
        objectUrl = u
        setPreview(u)
      })
      .catch(() => { /* 预览拉不到不影响文件本身已经传上去了 */ })
    return () => {
      dropped = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [value])

  return (
    <Upload
      listType="picture-card"
      maxCount={1}
      accept={UPLOAD_ACCEPT}
      fileList={value
        ? [{ uid: '1', name: '健康证', status: 'done' as const,
             url: preview || undefined, thumbUrl: preview || undefined }]
        : []}
      showUploadList={{ showPreviewIcon: false }}
      customRequest={async ({ file, onSuccess, onError, onProgress }) => {
        try {
          const url = await uploadImage(file as File, 'health_cert',
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
