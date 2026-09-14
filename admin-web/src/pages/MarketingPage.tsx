import { Alert, Card, Switch, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, CouponBatch, listCouponBatches,
  listSplash, Splash, toggleSplash, toggleCouponBatch, yuan,
} from '../api'

/**
 * 营销:优惠券批次(只看、只能停)。
 *
 * ⚠️ **平台不出钱发券**(2026-09-14 拍板「平台没有钱,不做平台出钱的安抚和营销」):
 * 新建平台批次、按手机号定向发券两个入口都下了,服务端也回 410;存量的平台批次
 * 一张都不再发(services/coupons.issue_from_batch),已经发出去的照旧能用。
 * 商家自己出钱的批次(店铺券、收藏即送、生日、复购……)在商家那边建,这里只列出来看。
 */
// 键跟服务端 CouponBatch.trigger 走(原来这张表写的是另一套键,一个都对不上)
const TRIGGERS: Record<string, string> = {
  newcomer: '新客', manual: '手动发放', shop: '店铺领取', favorite: '收藏即送',
  referral: '新客推荐(已停)', birthday: '生日', winback: '复购',
}

export default function MarketingPage() {
  const [rows, setRows] = useState<CouponBatch[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [splash, setSplash] = useState<Splash[]>([])

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try {
      const [b, sp] = await Promise.all([listCouponBatches(), listSplash()])
      setRows(b); setSplash(sp)
    }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>, ok: string) {
    try { await fn(); message.success(ok); await load() }
    catch (e) { message.error(e instanceof ApiError ? e.message : String(e)) }
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Alert type="info" showIcon style={{ marginBottom: 12 }}
             message="平台不再出钱发券(2026-09-14 起)"
             description="新建平台批次、定向发券都停了;平台批次一张都不再发,已经发出去的券照旧能用。商家自己出钱的券在商家后台建,这里只列出来看、必要时可以停用。" />
      <Card size="small" title="优惠券批次">
        <Table<CouponBatch>
          rowKey="id" loading={loading} dataSource={rows} size="middle"
          scroll={{ x: 'max-content' }}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            { title: '名称', dataIndex: 'name', width: 160 },
            { title: '谁出钱', width: 110,
              render: (_, b) => b.merchant_id
                ? <Tag color="blue">商家 #{b.merchant_id}</Tag>
                : <Tag>平台(已停发)</Tag> },
            { title: '触发', dataIndex: 'trigger', width: 100,
              render: (v: string) => <Tag>{TRIGGERS[v] ?? v}</Tag> },
            { title: '面额', dataIndex: 'amount_cents', width: 90, align: 'right',
              render: (v: number) => yuan(v) },
            { title: '门槛', dataIndex: 'min_spend_cents', width: 100, align: 'right',
              render: (v: number) => v ? `满 ${yuan(v)}` : '无门槛' },
            { title: '有效期', dataIndex: 'valid_days', width: 90,
              render: (v: number) => `${v} 天` },
            { title: '发放 / 总量', width: 130,
              render: (_, b) => `${b.issued} / ${b.total || '不限'}` },
            { title: '已核销', dataIndex: 'used', width: 90 },
            { title: '启用', width: 80,
              render: (_, b) => (
                // 平台批次只能停不能开(服务端也拦):开了也一张都发不出去
                <Switch size="small" checked={b.active}
                        disabled={!b.merchant_id && !b.active}
                        onChange={() => act(() => toggleCouponBatch(b.id),
                          b.active ? '已停用' : '已启用')} />
              ) },
          ]}
        />
      </Card>
      <Card size="small" title={`开屏图 ${splash.length}`} style={{ marginTop: 12 }}
            loading={loading}>
        <Table<Splash>
          rowKey="id" dataSource={splash} size="small"
          pagination={false} scroll={{ x: 'max-content' }}
          locale={{ emptyText: '没有配置开屏图' }}
          columns={[
            { title: '标题', dataIndex: 'title', width: 160 },
            { title: '副标题', dataIndex: 'subtitle', ellipsis: true },
            { title: '受众', dataIndex: 'audience', width: 100,
              render: (v: string) => <Tag>{v || '全部'}</Tag> },
            { title: '停留', dataIndex: 'countdown_seconds', width: 80,
              render: (v: number) => `${v} 秒` },
            { title: '投放期', width: 200,
              render: (_, r) => `${(r.starts_at || '').slice(0, 10)} → ${(r.ends_at || '').slice(0, 10)}` },
            { title: '上线', width: 80, fixed: 'right',
              render: (_, r) => (
                <Switch size="small" checked={r.is_active}
                        onChange={() => act(() => toggleSplash(r.id),
                          r.is_active ? '已下线' : '已上线')} />
              ) },
          ]}
        />
      </Card>
    </>
  )
}
