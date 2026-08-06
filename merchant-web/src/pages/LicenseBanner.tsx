import { Alert, Button, DatePicker, Form, Input, Modal, Upload, message } from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, LicenseRenewal, LicenseStage, Merchant, myLicenseRenewal,
  submitLicenseRenewal, UPLOAD_ACCEPT, uploadImage,
} from '../api'

/**
 * 证照到期横幅:工作台顶部常驻,直到证换完。
 *
 * **为什么要常驻而不是塞进消息中心**:证过期是唯一一件"到点就自动出事"
 * 的事(过期 → 7 天宽限 → 自动停业),而消息中心里的东西商家划一下就没了。
 * 到期这条必须一直在眼前,直到真的处理掉。
 *
 * unknown(未登记)也出横幅,但语气最轻 —— 存量商家全是这个状态,
 * 目的是请他们补一次,不是吓唬人。
 */
export default function LicenseBanner({ shop }: { shop: Merchant }) {
  const [renewal, setRenewal] = useState<LicenseRenewal | null>(null)
  const [open, setOpen] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await myLicenseRenewal()
      setRenewal(r.renewal)
    } catch {
      /* 横幅拉不到进度不该影响工作台,静默 */
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    // 只有真要提醒时才去问进度,别给每个商家的每次进页面都加一次请求
    if (shop.license_stage !== 'ok') load()
    else setLoaded(true)
  }, [shop.license_stage, load])

  if (!loaded || shop.license_stage === 'ok') return null
  // 店员看不到资质入口(资质材料不是接单要用的东西)
  if (shop.viewer_is_staff || shop.viewer_is_owner === false) return null

  // 已经提交在审:横幅改成"在审中",别让人反复交
  if (renewal?.status === 'pending') {
    return (
      <Alert
        type="info" showIcon banner style={{ marginBottom: 12 }}
        message={`新证核验中(${renewal.license_no}),核验期间照常营业`}
      />
    )
  }

  const cfg = BANNER[shop.license_stage]
  if (!cfg) return null
  const left = shop.license_days_left

  return (
    <>
      {renewal?.status === 'rejected' && (
        <Alert
          type="error" showIcon banner style={{ marginBottom: 8 }}
          message={`上次提交的新证未通过:${renewal.reject_reason}`}
        />
      )}
      <Alert
        type={cfg.type} showIcon banner style={{ marginBottom: 12 }}
        message={cfg.title(left)}
        description={cfg.desc}
        action={
          <Button size="small" type="primary" onClick={() => setOpen(true)}>
            {shop.license_stage === 'unknown' ? '去登记' : '提交新证'}
          </Button>
        }
      />
      <RenewalModal
        open={open}
        onClose={() => setOpen(false)}
        onDone={() => { setOpen(false); load() }}
      />
    </>
  )
}

const BANNER: Record<LicenseStage, {
  type: 'info' | 'warning' | 'error'
  title: (left: number | null) => string
  desc: string
} | undefined> = {
  ok: undefined,
  unknown: {
    type: 'info',
    title: () => '还没登记食品经营许可证的有效期',
    desc: '登记后我们会在到期前 30 / 7 / 1 天提醒你。'
      + '证过期是静默失效 —— 没人提醒就只能等监管上门。',
  },
  soon: {
    type: 'info',
    title: (l) => `食品经营许可证还有 ${l} 天到期`,
    desc: '续证要跑审批流程,建议现在就去办;拿到新证在这里提交即可。',
  },
  urgent: {
    type: 'warning',
    title: (l) => `食品经营许可证 ${l} 天后到期`,
    desc: '过期后仍可营业 7 天,之后需人工核验新证才能恢复接单。',
  },
  last: {
    type: 'warning',
    title: () => '食品经营许可证明天到期',
    desc: '过期后有 7 天宽限期,请尽快提交新证。',
  },
  expired: {
    type: 'error',
    title: (l) => `食品经营许可证已过期 ${l === null ? '' : -l} 天`,
    desc: '目前仍可正常接单,但 7 天宽限期结束后将暂停营业。',
  },
  overdue: {
    type: 'error',
    title: () => '已暂停营业:食品经营许可证过期超过宽限期',
    desc: '提交新证后由平台人工核验恢复 —— 无证经营是违法的,'
      + '这一步我们不能替你跳过。',
  },
}

function RenewalModal(
  { open, onClose, onDone }:
  { open: boolean; onClose: () => void; onDone: () => void },
) {
  const [form] = Form.useForm()
  const [busy, setBusy] = useState(false)
  return (
    <Modal
      open={open} title="提交新的食品经营许可证" okText="提交核验"
      confirmLoading={busy}
      onCancel={onClose}
      onOk={async () => {
        const v = await form.validateFields()
        setBusy(true)
        try {
          await submitLicenseRenewal({
            license_no: v.license_no,
            license_image_url: v.license_image_url,
            license_expires_at: v.license_expires_at.format('YYYY-MM-DD'),
            business_license_no: v.business_license_no,
            license_subject: v.license_subject,
          })
          message.success('已提交,核验通过后自动替换;核验期间照常营业')
          form.resetFields()
          onDone()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
        } finally {
          setBusy(false)
        }
      }}
    >
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message="核验期间照常营业"
        description="换证不用停业。通过后自动替换店里的资质,并解除因过期造成的停业。"
      />
      <Form form={form} layout="vertical">
        <Form.Item name="license_no" label="许可证编号"
          rules={[{ required: true, message: '填新证的编号' }]}>
          <Input maxLength={50} />
        </Form.Item>
        <Form.Item
          name="license_expires_at" label="有效期至"
          rules={[{ required: true, message: '填新证的有效期至' }]}
          extra="到期提醒靠它。填了才会在到期前 30 / 7 / 1 天提醒你。"
        >
          <DatePicker
            style={{ width: '100%' }}
            // 交一张已经过期的证没有意义,当场拦掉比等三天核验强
            disabledDate={(d) => d && d <= dayjs().endOf('day')}
          />
        </Form.Item>
        <Form.Item name="license_subject" label="证照主体名称(选填)"
          extra="证上的公司/个体户全称。与店招不同很正常(店招「赞小碗」/ 证上是公司全称)。">
          <Input maxLength={100} placeholder="如:成都赞小碗餐饮管理有限公司" />
        </Form.Item>
        <Form.Item name="business_license_no" label="营业执照统一社会信用代码(选填)">
          <Input maxLength={50} />
        </Form.Item>
        <Form.Item
          name="license_image_url" label="许可证照片"
          rules={[{ required: true, message: '上传新证照片' }]}
        >
          <LicenseImage />
        </Form.Item>
      </Form>
    </Modal>
  )
}

/** purpose 必须是 'license' —— 后端按 purpose 决定进公开桶还是私密桶,
 *  证照走私密桶,填错会把许可证挂到公网上。 */
function LicenseImage(
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
