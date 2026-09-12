import { Alert, Button, Card, Descriptions, Form, Input, List, Radio, Space, Tag, Typography, Upload, message } from 'antd'
import { useEffect, useState } from 'react'

import { ApiError, Me, api } from '../api'

/**
 * 账号与认证(#329):开发者名、个人实名 / 企业认证、接受开发者规则。
 *
 * 个人:姓名 + 身份证号(机器核验,须满 18 岁),**只存密文、页面只显示尾号**;
 * 公开页只显示你自取的开发者名 +「个人开发者 · 已实名」。企业:营业执照 + 统一社会信用代码,人工审核,企业名公开。
 */
export default function AccountPage({ me, onChanged, reload }: { me: Me | null; onChanged: (m: Me) => void; reload: () => void }) {
  const [kind, setKind] = useState<'individual' | 'company'>('individual')
  const [rules, setRules] = useState<{ draft: boolean; sections: Array<{ title: string; items: string[] }> } | null>(null)
  const [license, setLicense] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.rules().then(setRules).catch(() => undefined) }, [])
  if (!me) return null

  const run = async (fn: () => Promise<Me>, ok: string) => {
    setBusy(true)
    try {
      onChanged(await fn())
      message.success(ok)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  const canVerify = me.status === 'unverified' || me.status === 'rejected'

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="开发者信息">
        <Form layout="vertical" initialValues={{ display_name: me.display_name, contact_email: me.contact_email }}
          onFinish={(v) => run(() => api.updateProfile(v), '已保存')} disabled={busy}>
          <Form.Item name="display_name" label="开发者名(公开展示)" rules={[{ required: true, min: 2, max: 40 }]}
            extra="企业认证通过后公开展示公司名;个人开发者公开展示这个名字。不能用「超级赞」「官方」等字样。">
            <Input />
          </Form.Item>
          <Form.Item name="contact_email" label="联系邮箱(不公开,审核有问题时联系你)">
            <Input />
          </Form.Item>
          <Button htmlType="submit">保存</Button>
        </Form>
      </Card>

      <Card title="认证" extra={<Tag>{me.status_label}</Tag>}>
        {me.status === 'verified' && (
          <Descriptions column={1} size="small">
            <Descriptions.Item label="公开显示">{me.public.name} · {me.public.label}</Descriptions.Item>
            {me.kind === 'individual' && <Descriptions.Item label="实名">{me.real_name_masked}(证号尾号 {me.id_no_tail})</Descriptions.Item>}
            {me.kind === 'company' && <Descriptions.Item label="企业">{me.company_name}({me.uscc})</Descriptions.Item>}
          </Descriptions>
        )}
        {me.status === 'pending' && <Alert type="info" showIcon message="企业认证审核中" description="审核结果会出现在「消息」里。平台不承诺具体时限,审核时长的中位数在透明中心公示。" />}
        {me.status === 'rejected' && <Alert type="error" showIcon style={{ marginBottom: 12 }} message="认证没有通过" description={me.reject_reason} />}
        {canVerify && (
          <>
            <Typography.Paragraph type="secondary">
              没认证也能建应用、传开发版、加体验者、用模拟器;**认证通过才能提交审核**。
            </Typography.Paragraph>
            <Radio.Group value={kind} onChange={(e) => setKind(e.target.value)} style={{ marginBottom: 12 }}>
              <Radio.Button value="individual">个人</Radio.Button>
              <Radio.Button value="company">企业</Radio.Button>
            </Radio.Group>
            {kind === 'individual' ? (
              <Form layout="vertical" disabled={busy} onFinish={(v) => run(() => api.verifyIndividual(v), '实名核验通过')}>
                <Form.Item name="real_name" label="真实姓名" rules={[{ required: true, min: 2 }]}><Input /></Form.Item>
                <Form.Item name="id_no" label="身份证号" rules={[{ required: true, len: 18 }]}
                  extra="须年满 18 周岁。只存密文,页面只显示尾号;真名不会公开。"><Input /></Form.Item>
                <Button type="primary" htmlType="submit">提交核验</Button>
              </Form>
            ) : (
              <Form layout="vertical" disabled={busy}
                onFinish={(v) => run(() => api.verifyCompany({ ...v, license_key: license }), '已提交,等待人工审核')}>
                <Form.Item name="company_name" label="企业名称(公开展示)" rules={[{ required: true, min: 4 }]}><Input /></Form.Item>
                <Form.Item name="uscc" label="统一社会信用代码" rules={[{ required: true, len: 18 }]}><Input /></Form.Item>
                <Form.Item label="营业执照" required extra="只有审核员看得到(私有存储)">
                  <Upload accept="image/*" maxCount={1} showUploadList={false}
                    customRequest={async ({ file }) => {
                      try {
                        const r = await api.uploadImage(file as File, 'dev_license')
                        setLicense(r.url)
                        message.success('已上传')
                      } catch (e) {
                        message.error(e instanceof ApiError ? e.message : String(e))
                      }
                    }}>
                    <Button>{license ? '已上传,点击更换' : '上传照片'}</Button>
                  </Upload>
                </Form.Item>
                <Form.Item name="contact_name" label="联系人" rules={[{ required: true, min: 2 }]}><Input /></Form.Item>
                <Button type="primary" htmlType="submit" disabled={!license}>提交审核</Button>
              </Form>
            )}
          </>
        )}
      </Card>

      <Card title="开发者规则" extra={me.agreement.ok ? <Tag color="success">已接受第 {me.agreement.accepted} 版</Tag>
        : <Tag color="warning">待接受第 {me.agreement.required} 版</Tag>}>
        {rules?.draft && <Alert type="warning" message="开发者规则与协议目前是草案,法务定稿前可能调整;每次调整都记在规则留痕里。" style={{ marginBottom: 12 }} />}
        <List
          dataSource={rules?.sections || []}
          renderItem={(s) => (
            <List.Item style={{ display: 'block' }}>
              <Typography.Text strong>{s.title}</Typography.Text>
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {s.items.filter((x) => x).map((x, i) => <li key={i} style={{ color: 'var(--sz-ink)', fontSize: 13 }}>{x.replace(/\*\*/g, '')}</li>)}
              </ul>
            </List.Item>
          )}
        />
        <Space style={{ marginTop: 12 }}>
          <Button type="primary" disabled={me.agreement.ok || busy}
            onClick={() => run(() => api.acceptAgreement(me.agreement.required), '已接受')}>
            我已阅读并接受第 {me.agreement.required} 版
          </Button>
          <a href="/opensource" target="_blank" rel="noreferrer">规则变更留痕 ›</a>
          <a onClick={reload}>刷新</a>
        </Space>
      </Card>
    </Space>
  )
}
