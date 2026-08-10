import {
  Alert, Button, Card, Col, Form, Input, Progress, Radio, Row, Space, Spin,
  Steps, Tag, Upload, message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, Applyment, ApplymentIn, ApplymentMissing, ApplymentStatus,
  SettleAccountType, SubjectType, UPLOAD_ACCEPT, UploadPurpose,
  fetchPrivateImage, myApplyment, saveApplyment, uploadImage, validateIdNo,
} from '../api'

/**
 * 收款资料(微信特约商户进件,#205 + #206 商家侧)。
 *
 * 这一页要商家交法人身份证和银行账号 —— 是整个商家端最"要命"的一张表。
 * **文案是这一页的一半工作量**:不把「交给谁、交了之后钱怎么走、
 * 平台看得到什么」讲清楚,就是在空手要人的敏感证件。
 *
 * 两条刻意的设计:
 * - **必填清单不在前端**。个体工商户和企业要交的材料不一样,规则写两份
 *   迟早分叉,商家会卡在「页面说填完了、提交却说没填完」。
 *   这里只校验**格式**,而且格式规则是照着服务端 `ApplymentIn.check_formats`
 *   一条条对过来的(身份证连校验位一起算),齐没齐一律听服务端的 `missing`;
 * - **允许填一半就保存**。老板对着营业执照抄的时候,银行账号常常
 *   要另找一张卡,不让存就等于让他从头再来一遍。
 */
export default function ApplymentPage() {
  const [data, setData] = useState<Applyment | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await myApplyment()
      setData(r)
      form.setFieldsValue({
        subject_type: r.subject_type || undefined,
        business_license_image_url: r.business_license_image_url,
        legal_person_name: r.legal_person_name,
        legal_person_id_front_url: r.legal_person_id_front_url,
        legal_person_id_back_url: r.legal_person_id_back_url,
        admin_contact_name: r.admin_contact_name,
        admin_contact_phone: r.admin_contact_phone,
        admin_contact_email: r.admin_contact_email,
        settle_account_type: r.settle_account_type || undefined,
        settle_account_name: r.settle_account_name,
        settle_bank_name: r.settle_bank_name,
        settle_bank_branch: r.settle_bank_branch,
        // 身份证号和银行账号**不回显** —— 服务端只给尾 4 位,
        // 把尾号填进输入框,商家一按保存就把库里的完整号码覆盖成 4 位数
        legal_person_id_no: '',
        settle_account_no: '',
      })
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [form])

  useEffect(() => { load() }, [load])

  async function save() {
    const v = await form.validateFields()
    const payload: ApplymentIn = {
      subject_type: v.subject_type,
      business_license_image_url: v.business_license_image_url ?? '',
      legal_person_name: (v.legal_person_name ?? '').trim(),
      legal_person_id_front_url: v.legal_person_id_front_url ?? '',
      legal_person_id_back_url: v.legal_person_id_back_url ?? '',
      admin_contact_name: (v.admin_contact_name ?? '').trim(),
      admin_contact_phone: (v.admin_contact_phone ?? '').trim(),
      admin_contact_email: (v.admin_contact_email ?? '').trim(),
      settle_account_type: v.settle_account_type,
      settle_account_name: (v.settle_account_name ?? '').trim(),
      settle_bank_name: (v.settle_bank_name ?? '').trim(),
      settle_bank_branch: (v.settle_bank_branch ?? '').trim(),
    }
    // 两个敏感字段:留空 = 不动库里已有的,填了才当作"改了"
    const idNo = (v.legal_person_id_no ?? '').trim()
    if (idNo) payload.legal_person_id_no = idNo.toUpperCase()
    const acctNo = (v.settle_account_no ?? '').replace(/\s/g, '')
    if (acctNo) payload.settle_account_no = acctNo

    setSaving(true)
    try {
      const r = await saveApplyment(payload)
      setData(r)
      form.setFieldsValue({ legal_person_id_no: '', settle_account_no: '' })
      message.success(r.complete
        ? '资料已保存,该交的都齐了'
        : `已保存,还缺 ${r.missing.length} 项`)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const subjectType: SubjectType | undefined =
    Form.useWatch('subject_type', form)
  const settleType: SettleAccountType | undefined =
    Form.useWatch('settle_account_type', form)

  if (loading && !data) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}><Spin size="large" /></div>
    )
  }

  // 微信侧已经在处理的单子,服务端 PUT 一律 409。
  // 表单先锁掉而不是等提交时报错 —— 让人重填一遍再告诉他白填了,是最难受的
  const status = data?.applyment_status ?? 'not_submitted'
  const locked = status === 'need_sign' || status === 'need_account_verify'
    || status === 'finished'

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <WhyCard />
      <StatusCard data={data} />
      {!locked && <MissingCard data={data} />}

      <Card size="small" title="收款资料">
        {locked && (
          <Alert
            type={status === 'finished' ? 'success' : 'info'}
            showIcon style={{ marginBottom: 12 }}
            message={status === 'finished'
              ? '已开通,资料锁定'
              : '微信正在处理,资料暂时锁定'}
            description={status === 'finished'
              ? '要换结算账户或换法人,得重新走一遍进件,联系平台客服。别指望在这里改——改了也不会生效,钱还是进原来那个账户。'
              : '这会儿改库里的资料没用:报上去的是提交时的那一版,改了只会让你以为「我已经改好了」。真要改,先联系平台客服把单子退回来。现在该做的是上面那一步。'}
          />
        )}
        <Form form={form} layout="vertical" disabled={locked}>
          <SectionTitle text="一、经营主体" />
          <Form.Item
            name="subject_type" label="主体类型"
            extra="按营业执照上写的选。选错了微信那边直接驳回,材料清单也不一样。"
          >
            <Radio.Group>
              <Radio.Button value="individual">个体工商户</Radio.Button>
              <Radio.Button value="enterprise">企业</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            name="business_license_image_url" label="营业执照照片"
            extra="拍正本、四角拍全、字要看得清。存在私密空间,不会出现在你的店铺页上。"
          >
            <SecretImage purpose="license" title="营业执照" />
          </Form.Item>

          <SectionTitle text="二、法定代表人" />
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item
                name="legal_person_name" label="法人姓名"
                rules={[{ validator: nameRule }]}
                extra={subjectType === 'individual'
                  ? '个体工商户填营业执照上的「经营者」姓名。'
                  : '填营业执照上的「法定代表人」,不是股东也不是店长。'}
              >
                <Input maxLength={50} placeholder="与营业执照一致" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item
                name="legal_person_id_no" label="法人身份证号"
                rules={[{ validator: idCardRule }]}
                extra={<SecretHint
                  tail={data?.legal_person_id_tail ?? ''} what="身份证号" />}
              >
                <Input maxLength={18} placeholder="18 位,末位是 X 也照填" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item name="legal_person_id_front_url" label="身份证人像面">
                <SecretImage purpose="id_card" title="身份证人像面" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item name="legal_person_id_back_url" label="身份证国徽面">
                <SecretImage purpose="id_card" title="身份证国徽面" />
              </Form.Item>
            </Col>
          </Row>

          <SectionTitle text="三、超级管理员" />
          <Alert
            type="warning" showIcon style={{ marginBottom: 12 }}
            message="这三项填错,进件会一直卡着,而且不会有人提醒你"
            description="微信把「该你签约了」「账户验证要你填金额」这类通知发给这个人。手机号打错一位,通知就石沉大海,页面上只会显示「待签约」不动——所以填之前核一遍。填能长期联系上的人,一般就是老板本人。"
          />
          <Row gutter={16}>
            <Col xs={24} sm={8}>
              <Form.Item
                name="admin_contact_name" label="姓名"
                rules={[{ validator: nameRule }]}
              >
                <Input maxLength={50} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item
                name="admin_contact_phone" label="手机号"
                rules={[{ validator: phoneRule }]}
                extra="要用这个号绑定的微信扫码签约。"
              >
                <Input maxLength={11} placeholder="11 位手机号" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item
                name="admin_contact_email" label="邮箱"
                rules={[{ validator: emailRule }]}
                extra="微信的进件结果邮件发到这里,常用邮箱。"
              >
                <Input maxLength={100} placeholder="name@example.com" />
              </Form.Item>
            </Col>
          </Row>

          <SectionTitle text="四、结算账户(钱最后打到哪)" />
          <Form.Item
            name="settle_account_type" label="账户类型"
            extra={subjectType === 'enterprise'
              ? '企业主体微信一般要求对公账户;对私能不能过以微信受理结果为准。'
              : '个体工商户对公、对私都可以。对私填经营者本人的银行卡。'}
          >
            <Radio.Group>
              <Radio.Button value="corporate">对公账户</Radio.Button>
              <Radio.Button value="personal">对私账户</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item
                name="settle_account_name" label="开户名"
                rules={[{ validator: nameRule }]}
                extra={settleType === 'corporate'
                  ? '对公:填营业执照上的主体全称,一个字都不能差。'
                  : '对私:填持卡人姓名,必须是上面那位法人本人。'}
              >
                <Input maxLength={80} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item
                name="settle_account_no" label="银行账号"
                rules={[{ validator: bankAccountRule }]}
                extra={<SecretHint
                  tail={data?.settle_account_tail ?? ''} what="银行账号" />}
              >
                <Input maxLength={32} placeholder="只填数字,不要空格和横杠" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item
                name="settle_bank_name" label="开户银行"
                extra="如:中国工商银行。填银行全称,别填简称。"
              >
                <Input maxLength={80} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item
                name="settle_bank_branch" label="开户支行"
                extra="如:中国工商银行成都春熙路支行。卡背面或手机银行里查得到。"
              >
                <Input maxLength={120} />
              </Form.Item>
            </Col>
          </Row>
        </Form>

        {!locked && (
          <Space wrap>
            <Button type="primary" loading={saving} onClick={save}>
              保存资料
            </Button>
            <Button onClick={load} disabled={saving}>放弃修改,重新载入</Button>
            <span style={{ color: '#8c8c8c', fontSize: 12 }}>
              可以只填一部分先存着,不用一次填完。
            </span>
          </Space>
        )}
      </Card>
    </Space>
  )
}

/** 顶部三件事。要商家交身份证和银行账号,不解释清楚就是在要命的东西。 */
function WhyCard() {
  return (
    <Card size="small" title="填之前,先说清楚三件事">
      <div style={{ fontSize: 13, lineHeight: 2 }}>
        <p style={{ marginTop: 0 }}>
          <b>① 这些资料是交给微信支付的,不是交给平台。</b><br />
          微信要给你开一个<b>属于你自己的</b>特约商户号,营业执照、法人身份证、
          结算账户是它开户要的材料。平台只负责把材料原样转交,
          改不了,也不能拿去做别的。
        </p>
        <p>
          <b>② 开通之后,顾客付的钱直接进你填的这个银行账户。</b><br />
          现在是:钱先进平台的商户号,再由平台人工打款给你 ——
          中间隔着平台的账、隔着人。开通之后:微信收款后直接结给你的账户,
          平台的佣金走分账另外扣走。你少一道等待,平台少碰一笔不该沉淀的钱。
        </p>
        <p>
          <b>③ 平台看得到尾号,看不到完整号码,看了会留痕。</b><br />
          身份证号和银行账号加密存库,接口回给任何角色都<b>只有尾 4 位</b> ——
          这个页面也一样,所以你填过之后这两栏是空的,不是丢了。
          平台员工在后台解密看完整号码会写一条审计记录:谁、什么时候、
          看了哪家店的哪一项。证件照放私密空间,每次打开都要过鉴权,
          不会出现在你的店铺页上。
        </p>
        <Alert
          type="info"
          message="还有几句不太好听但你该知道的"
          description={
            <div style={{ fontSize: 12, lineHeight: 1.9 }}>
              · 这一版<b>只是把资料存起来</b>,还没真的提交给微信 ——
              微信服务商类目确认之后才会提交。现在填,是为了那天不用等你;
              要不要现在填,你自己定。<br />
              · 提交之后再改资料,要重新走一遍审核,开通时间往后拖。<br />
              · 开通之后想换结算账户,得重新进件,不是在这页改一下就行。
            </div>
          }
        />
      </div>
    </Card>
  )
}

const STEP_ITEMS = [
  { title: '填资料', description: '照着营业执照抄' },
  { title: '提交微信', description: '平台代传,等受理' },
  { title: '账户验证', description: '要你填回打款金额' },
  { title: '管理员签约', description: '要本人微信扫码' },
  { title: '开通收款', description: '货款直达你的账户' },
]

interface StatusInfo {
  step: number
  stepStatus: 'process' | 'error' | 'finish'
  type: 'info' | 'warning' | 'error' | 'success'
  title: string
  detail: React.ReactNode
}

/**
 * 状态解释(#206)。微信进件是异步的,「待账户验证」和「待签约」
 * 这两步**要商家本人操作**,平台干等是等不来的 ——
 * 所以每个状态都得回答两个问题:卡在哪、下一步你要做什么。
 */
function statusInfo(status: ApplymentStatus, reason: string): StatusInfo {
  switch (status) {
    case 'submitted':
      return {
        step: 1, stepStatus: 'process', type: 'info',
        title: '资料已交齐,等平台报送微信',
        detail: '这一步不用你做什么,球在平台这边。报送并受理之后,页面会变成「待账户验证」或「待签约」——那时候才轮到你动手,到时再回来看。',
      }
    case 'need_account_verify':
      return {
        step: 2, stepStatus: 'process', type: 'warning',
        title: '卡在账户验证 —— 要你本人操作,平台替不了',
        detail: (
          <>
            微信已经往你填的结算账户打了<b>一笔一元以内的随机金额</b>
            (一般 1~3 个工作日到账)。
            <br />
            你要做的:查这笔钱到账后的<b>实际金额</b>,
            按微信发给超级管理员的短信/邮件里的指引把金额填回去。
            <br />
            填错次数多了当天会锁,第二天才能再试 —— 所以查准了再填。
            钱一直没到账,先核对开户名、账号、支行是不是填错了。
          </>
        ),
      }
    case 'need_sign':
      return {
        step: 3, stepStatus: 'process', type: 'warning',
        title: '卡在签约 —— 要超级管理员本人操作',
        detail: (
          <>
            微信会给你填的<b>超级管理员手机号</b>发签约通知。
            请用<b>这个手机号绑定的微信</b>扫码,签《微信支付服务协议》。
            <br />
            别人代签不行,签完才能开始收款。没收到通知先检查手机号填得对不对
            —— 填错了通知会一直发不到,页面就一直停在这一步。
          </>
        ),
      }
    case 'rejected':
      return {
        step: 1, stepStatus: 'error', type: 'error',
        title: '被驳回了',
        detail: reason
          ? <>驳回原因:<b>{reason}</b><br />按原因改完下面的资料,再保存提交一次。</>
          : '没有拿到具体原因,请联系平台客服帮你问。',
      }
    case 'finished':
      return {
        step: 4, stepStatus: 'finish', type: 'success',
        title: '已开通,货款直达你的账户',
        detail: '从开通那一刻起,顾客付的钱直接结到你填的这个结算账户,平台佣金走分账另外扣。要换账户得重新走一遍进件。',
      }
    default:
      return {
        step: 0, stepStatus: 'process', type: 'info',
        title: '还没提交',
        detail: '把下面这张表填完保存就行。缺哪几项,页面上会列出来 —— 不用你自己对着清单猜。',
      }
  }
}

function StatusCard({ data }: { data: Applyment | null }) {
  const info = statusInfo(
    data?.applyment_status ?? 'not_submitted',
    data?.applyment_reject_reason ?? '')
  return (
    <Card
      size="small" title="进件进度"
      // 状态短名用服务端下发的,不在这边再写一张对照表:
      // 服务端哪天加了状态,这里至少还显示得出名字,不会是一片空白
      extra={data?.applyment_status_label
        ? <Tag color="blue">{data.applyment_status_label}</Tag>
        : null}
    >
      {/* Steps 自带 responsive:窄屏自动转竖排,笔记本上是横排 */}
      <Steps
        size="small"
        current={info.step}
        status={info.stepStatus}
        items={STEP_ITEMS}
        style={{ marginBottom: 16 }}
      />
      <Alert
        type={info.type} showIcon
        message={info.title}
        description={<div style={{ fontSize: 13, lineHeight: 1.9 }}>
          {info.detail}
        </div>}
      />
      {(data?.applyment_no || data?.applyment_updated_at) && (
        <div style={{ marginTop: 10, color: '#8c8c8c', fontSize: 12 }}>
          {data.applyment_no && <>微信申请单号:{data.applyment_no}　</>}
          {data.applyment_updated_at && <>
            最后更新:{new Date(data.applyment_updated_at).toLocaleString('zh-CN')}
          </>}
        </div>
      )}
    </Card>
  )
}

/**
 * 完整度。**列表和中文名都是服务端下发的**(`missing: [{field,label}]`),
 * 这里一个字都不硬编码 —— 个体工商户和企业要交的东西不一样,
 * 客户端再抄一份必填清单,迟早出现「页面显示已填满、提交却说没填完」。
 */
function MissingCard({ data }: { data: Applyment | null }) {
  const missing: ApplymentMissing[] = data?.missing ?? []
  const total = data?.required_total ?? 0
  const filled = data?.filled_count ?? 0
  const percent = total > 0 ? Math.round((filled / total) * 100) : 0

  if (data?.complete) {
    return (
      <Alert
        type="success" showIcon
        message="资料齐了"
        description="该交的都在。微信服务商类目确认之后,平台会代你提交,不用你再来点一次。"
      />
    )
  }
  return (
    <Alert
      type="warning" showIcon
      message={
        <Space wrap>
          <span>还缺 {missing.length} 项</span>
          {total > 0 && (
            <Progress
              percent={percent} size="small" status="active"
              style={{ width: 180, marginBottom: 0 }}
              format={() => `${filled}/${total}`}
            />
          )}
        </Space>
      }
      description={
        <div>
          <div style={{ marginBottom: 6, fontSize: 12, color: '#595959' }}>
            这份清单是服务端算的,以它为准 —— 个体工商户和企业要交的东西不一样,
            不用你自己对着规则猜。
          </div>
          <Space size={[6, 6]} wrap>
            {missing.map((m) => (
              <Tag key={`${m.field}:${m.label}`} color="orange">{m.label}</Tag>
            ))}
          </Space>
        </div>
      }
    />
  )
}

function SectionTitle({ text }: { text: string }) {
  return (
    <div style={{
      fontWeight: 600, fontSize: 14, margin: '4px 0 12px',
      paddingLeft: 8, borderLeft: '3px solid #FF5A1F',
    }}>
      {text}
    </div>
  )
}

/** 敏感字段的提示:说清楚"空着不是丢了,是本来就不回显"。 */
function SecretHint({ tail, what }: { tail: string; what: string }) {
  if (!tail) return <>加密存库,平台只看得到尾 4 位。</>
  return (
    <>
      已存 <Tag color="blue" style={{ marginInlineEnd: 4 }}>尾号 {tail}</Tag>
      平台只看得到尾号,所以这里不回显完整{what}。
      <b>不改就留空</b>,填了才会覆盖。
    </>
  )
}

// ---- 校验:只管格式,不管必填 ----
//
// 必填与否由服务端的 missing 决定(个体户/企业不一样),
// 所以每条规则都在"空值直接放行"上开口 —— 填一半就保存是被允许的。

type Rule = (_: unknown, value: string) => Promise<void>

const idCardRule: Rule = async (_, value) => {
  const v = (value ?? '').trim()
  // 校验位真算,规则与文案都取自服务端的 validate_id_no ——
  // 只判 18 位的话,手滑打错一位要等微信驳回才发现,一来一回好几天
  if (v) {
    const err = validateIdNo(v)
    if (err) throw new Error(err)
  }
}

const phoneRule: Rule = async (_, value) => {
  const v = (value ?? '').trim()
  if (v && !/^1\d{10}$/.test(v)) throw new Error('超级管理员手机号格式不正确')
}

const emailRule: Rule = async (_, value) => {
  const v = (value ?? '').trim()
  // 与服务端 ApplymentIn.check_formats 里同一条正则,别松也别紧
  if (v && !/^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(v)) {
    throw new Error('超级管理员邮箱格式不正确')
  }
}

const bankAccountRule: Rule = async (_, value) => {
  // 粘贴过来的卡号常带空格,和服务端一样先去空格再判
  const v = (value ?? '').replace(/\s/g, '')
  if (v && !/^\d{8,32}$/.test(v)) throw new Error('银行账号须为 8~32 位数字')
}

const nameRule: Rule = async (_, value) => {
  const v = (value ?? '').trim()
  if (v && v.length < 2) throw new Error('至少 2 个字')
}

/**
 * 证件照上传。和公开图片有两处不一样,都不能省:
 *
 * - **purpose 决定进公开桶还是私密桶**。营业执照用 `license`、
 *   身份证用 `id_card`,这两个 purpose 后端已经是私密的。填错一次,
 *   就是把一张身份证挂到了公网上,而且 URL 撤不回来;
 * - 私密图的唯一出口 `GET /files/{key}` 每次都要过鉴权,
 *   `<img src>` 不带 token —— 得先 fetch 成 blob 再显示,否则一片破图。
 */
function SecretImage({ value, onChange, purpose, title }: {
  value?: string
  onChange?: (v: string) => void
  purpose: Extract<UploadPurpose, 'license' | 'id_card'>
  title: string
}) {
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
      fileList={value ? [{
        uid: '1', name: title, status: 'done' as const,
        url: preview || undefined, thumbUrl: preview || undefined,
      }] : []}
      showUploadList={{ showPreviewIcon: false }}
      customRequest={async ({ file, onSuccess, onError, onProgress }) => {
        try {
          const url = await uploadImage(file as File, purpose,
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
