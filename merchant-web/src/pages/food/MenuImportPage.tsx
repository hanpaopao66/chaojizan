import { DownloadOutlined, InboxOutlined } from '@ant-design/icons'
import {
  Alert, Button, Card, Select, Space, Steps, Table, Tag, Typography, Upload,
  message,
} from 'antd'
import { useMemo, useState } from 'react'

import {
  ApiError, ImportRow, downloadFile, importCommit, importPreview, yuan,
} from '../../api'

/**
 * 菜单批量导入。
 *
 * ## 为什么是三步而不是"选文件→导入"
 *
 * 一次错误的表格能把 80 道菜的价格全改掉,而商家发现时已经卖了半天 ——
 * 一列串位就是一整店的价格错乱,退款和差评一起来。所以中间必须有一屏
 * **让他看见即将发生什么**:哪几行新增、哪几行覆盖旧价、哪几行有问题。
 *
 * ## 列映射:不写死表头
 *
 * 商家的表格是从别处导出来的,列名五花八门("菜名"/"品名"/"名称")。
 * 写死表头的话,90% 的表格第一步就被拒。这里做的是:按表头猜一次,
 * 猜不中就让他自己下拉指一下 —— **猜错的代价必须可纠正**。
 *
 * ## 图片不在这一步
 *
 * 表格里的图片链接多半指向别家的 CDN,防盗链会挂、版权也不在商家手里。
 * 导入只处理文字,图片让他在菜品管理里逐个传 —— 这一条页面上要明说,
 * 否则他会以为导完就齐活了。
 */
export default function MenuImportPage() {
  const [step, setStep] = useState(0)
  const [headers, setHeaders] = useState<string[]>([])
  const [raw, setRaw] = useState<string[][]>([])
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<ImportRow[]>([])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  /** 服务端认的列名(见 routers/merchants.py 的 _IMPORT_COLUMNS) */
  const FIELDS: { key: string; label: string; required?: boolean }[] = [
    { key: '名称', label: '菜名', required: true },
    { key: '分类', label: '分类' },
    { key: '价格(元)', label: '售价', required: true },
    { key: '成本(元)', label: '成本(只你自己看得到)' },
    { key: '库存', label: '库存' },
    { key: '描述', label: '描述' },
    { key: '标签', label: '标签(竖线分隔)' },
    { key: '额外打包费(元)', label: '额外打包费' },
  ]

  /** 表头猜测:去掉空格括号后包含即可。猜不中留空,让他自己指 */
  function guess(header: string[]): Record<string, string> {
    const norm = (s: string) => s.replace(/[\s()()]/g, '')
    const hints: Record<string, string[]> = {
      名称: ['名称', '菜名', '品名', '商品名', 'name'],
      分类: ['分类', '类别', '菜系', 'category'],
      '价格(元)': ['价格', '售价', '单价', 'price'],
      '成本(元)': ['成本', 'cost'],
      库存: ['库存', '数量', 'stock'],
      描述: ['描述', '简介', '介绍'],
      标签: ['标签', 'tag'],
      '额外打包费(元)': ['打包', '餐盒'],
    }
    const out: Record<string, string> = {}
    for (const [field, keys] of Object.entries(hints)) {
      const hit = header.find((h) => keys.some((k) => norm(h).includes(k)))
      if (hit) out[field] = hit
    }
    return out
  }

  /** CSV 解析:只处理逗号与引号包裹,够用即可 —— 复杂表格让他另存为 CSV */
  function parseCsv(text: string): string[][] {
    const rows: string[][] = []
    let cell = ''
    let row: string[] = []
    let quoted = false
    // BOM 去掉,否则第一列列名会带一个看不见的字符,映射永远猜不中
    const s = text.replace(/^﻿/, '')
    for (let i = 0; i < s.length; i++) {
      const c = s[i]
      if (quoted) {
        if (c === '"' && s[i + 1] === '"') { cell += '"'; i++ }
        else if (c === '"') quoted = false
        else cell += c
      } else if (c === '"') quoted = true
      else if (c === ',') { row.push(cell); cell = '' }
      else if (c === '\n') {
        row.push(cell.replace(/\r$/, ''))
        rows.push(row)
        row = []
        cell = ''
      } else cell += c
    }
    if (cell || row.length) { row.push(cell); rows.push(row) }
    return rows.filter((r) => r.some((c) => c.trim()))
  }

  const mapped = useMemo(() => raw.map((r) => {
    const o: Record<string, string> = {}
    for (const f of FIELDS) {
      const col = mapping[f.key]
      if (!col) continue
      const idx = headers.indexOf(col)
      if (idx >= 0) o[f.key] = r[idx] ?? ''
    }
    return o
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [raw, headers, mapping])

  async function doPreview() {
    if (!mapping['名称'] || !mapping['价格(元)']) {
      message.warning('至少要指出「菜名」和「售价」是哪两列')
      return
    }
    setBusy(true)
    try {
      const r = await importPreview(mapped)
      setPreview(r.items)
      setNote(r.note)
      setStep(2)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function doCommit() {
    const ok = preview.filter((i) => i.action !== 'problem')
    setBusy(true)
    try {
      const r = await importCommit(ok)
      message.success(`新增 ${r.created} 个、更新 ${r.updated} 个`)
      setStep(0)
      setPreview([])
      setRaw([])
      setHeaders([])
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const counts = {
    create: preview.filter((i) => i.action === 'create').length,
    update: preview.filter((i) => i.action === 'update').length,
    problem: preview.filter((i) => i.action === 'problem').length,
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="菜单批量导入">
        <Steps
          current={step}
          style={{ marginBottom: 16 }}
          items={[
            { title: '选文件' },
            { title: '对上列' },
            { title: '看清楚再导' },
          ]}
        />

        {step === 0 && (
          <>
            <Alert
              type="info" showIcon style={{ marginBottom: 12 }}
              message="从别的平台搬过来?先在那边导出你自己的菜单"
              description={
                <>
                  我们<b>不去别家系统里抓你的数据</b> —— 那既不合法,
                  也要你把账号密码交出来。你自己导出的表格是你的东西,
                  拿过来我们解析。表格里的图片链接不会导入
                  (多半指向别家 CDN,防盗链会挂),菜品图请在「菜品管理」里逐个传。
                </>
              }
            />
            <Space>
              {/* 模板要带 token 才拿得到,不能用裸 href —— 那样是 401 */}
              <Button
                icon={<DownloadOutlined />}
                onClick={() => downloadFile(
                    '/merchants/me/dishes/import-template',
                    'menu-template.csv')
                  .catch((e) => message.error(
                    e instanceof ApiError ? e.message : String(e)))}
              >
                下载模板 CSV
              </Button>
              <Upload.Dragger
                accept=".csv,text/csv"
                showUploadList={false}
                beforeUpload={(file) => {
                  const reader = new FileReader()
                  reader.onload = () => {
                    const rows = parseCsv(String(reader.result || ''))
                    if (rows.length < 2) {
                      message.error('这个文件里没有数据行')
                      return
                    }
                    const [head, ...body] = rows
                    setHeaders(head)
                    setRaw(body)
                    setMapping(guess(head))
                    setStep(1)
                  }
                  reader.readAsText(file, 'utf-8')
                  return false   // 不上传:解析全在浏览器里做
                }}
                style={{ padding: '8px 24px' }}
              >
                <p style={{ margin: 0 }}>
                  <InboxOutlined style={{ fontSize: 22 }} />
                </p>
                <p style={{ margin: 0 }}>把 CSV 拖进来,或点击选择</p>
              </Upload.Dragger>
            </Space>
          </>
        )}

        {step === 1 && (
          <>
            <Alert
              type="warning" showIcon style={{ marginBottom: 12 }}
              message="确认每一列对应什么"
              description="我们按列名猜了一次。猜错的地方自己改 —— 一列串位就是一整店的价格错乱。"
            />
            <Table
              rowKey="key"
              size="small"
              pagination={false}
              dataSource={FIELDS}
              columns={[
                {
                  title: '这个字段', dataIndex: 'label', width: 220,
                  render: (v: string, r) => (
                    <>{v}{r.required && <Tag color="red" style={{ marginLeft: 6 }}>必填</Tag>}</>
                  ),
                },
                {
                  title: '取表格里的哪一列', width: 260,
                  render: (_, r) => (
                    <Select
                      allowClear
                      style={{ width: 220 }}
                      placeholder="不导入这一项"
                      value={mapping[r.key]}
                      onChange={(v) => setMapping((m) => ({ ...m, [r.key]: v }))}
                      options={headers.map((h) => ({ value: h, label: h }))}
                    />
                  ),
                },
                {
                  title: '第一行长这样',
                  render: (_, r) => {
                    const idx = headers.indexOf(mapping[r.key])
                    return <Typography.Text type="secondary">
                      {idx >= 0 ? (raw[0]?.[idx] ?? '') : '—'}
                    </Typography.Text>
                  },
                },
              ]}
            />
            <Space style={{ marginTop: 12 }}>
              <Button onClick={() => setStep(0)}>换个文件</Button>
              <Button type="primary" loading={busy} onClick={doPreview}>
                下一步:预览 {raw.length} 行
              </Button>
            </Space>
          </>
        )}

        {step === 2 && (
          <>
            <Alert
              type={counts.problem ? 'warning' : 'success'} showIcon
              style={{ marginBottom: 12 }}
              message={`新增 ${counts.create} 个 · 覆盖 ${counts.update} 个`
                + (counts.problem ? ` · ${counts.problem} 行有问题(会跳过)` : '')}
              description={note}
            />
            <Table
              rowKey="row"
              size="small"
              dataSource={preview}
              pagination={{ pageSize: 20, hideOnSinglePage: true }}
              columns={[
                { title: '行', dataIndex: 'row', width: 60 },
                { title: '菜名', dataIndex: 'name', ellipsis: true },
                {
                  title: '将要', width: 110,
                  render: (_, r) => r.action === 'create'
                    ? <Tag color="green">新增</Tag>
                    : r.action === 'update'
                      ? <Tag color="blue">覆盖</Tag>
                      : <Tag color="red">跳过</Tag>,
                },
                {
                  title: '售价', width: 150,
                  render: (_, r) => r.price_cents === null ? '—'
                    : r.old_price_cents !== null
                      && r.old_price_cents !== r.price_cents
                      ? <>
                          <Typography.Text delete type="secondary">
                            {yuan(r.old_price_cents)}
                          </Typography.Text>
                          {' → '}
                          <Typography.Text strong>
                            {yuan(r.price_cents)}
                          </Typography.Text>
                        </>
                      : yuan(r.price_cents),
                },
                { title: '分类', dataIndex: 'category', width: 110 },
                {
                  title: '问题', dataIndex: 'problems',
                  render: (v: string[]) => v.length
                    ? <Typography.Text type="danger">{v.join('、')}</Typography.Text>
                    : '',
                },
              ]}
            />
            <Space style={{ marginTop: 12 }}>
              <Button onClick={() => setStep(1)}>回去改列映射</Button>
              <Button
                type="primary" loading={busy} onClick={doCommit}
                disabled={counts.create + counts.update === 0}
              >
                确认导入 {counts.create + counts.update} 个
              </Button>
            </Space>
          </>
        )}
      </Card>
    </Space>
  )
}
