import { Alert, Button, Image, Input, Modal, Select, Space, Table, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  ApiError, FoodSafetyReport, foodSafetyAction, listFoodSafety, takeDownDish,
} from '../api'

/**
 * 食安投诉。
 *
 * **这页优先级最高。** 食品安全出事是不可逆的 —— 别的投诉压一天是体验问题,
 * 这个压一天可能是有人进医院。旧后台把这个标签涂成红色就是这个意思。
 *
 * 四种处置都要填说明:确认/驳回/下架菜品/暂停营业。
 * 暂停营业会推给商家,写清整改要求他才知道怎么恢复。
 */
/** 取值对着 `schemas.py` 的 `Literal["foreign_object", "spoiled", "sick"]`。
 *  第一版是照着感觉**编的**(过敏、疑似食物中毒),而真实数据里最多的
 *  `sick` 反而没映射 —— 表格里直接显示成英文,自己截图才看出来。 */
const KINDS: Record<string, string> = {
  foreign_object: '异物',
  spoiled: '变质',
  sick: '吃后不适',
}

export default function FoodSafetyPage() {
  const [rows, setRows] = useState<FoodSafetyReport[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try { setRows(await listFoodSafety()) }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  function ask(title: string, hint: string, danger: boolean,
               run: (note: string) => Promise<unknown>, ok: string) {
    let note = ''
    Modal.confirm({
      title, okText: '确认', cancelText: '取消',
      okButtonProps: { danger },
      content: <Input.TextArea rows={3} maxLength={300} placeholder={hint}
                               onChange={(e) => { note = e.target.value }} />,
      onOk: async () => {
        if (note.trim().length < 2) {
          message.warning('请写清说明'); throw new Error('太短')
        }
        setActing(true)
        try { await run(note.trim()); message.success(ok); await load() }
        catch (e) { message.error(e instanceof ApiError ? e.message : String(e)); throw e }
        finally { setActing(false) }
      },
    })
  }

  return (
    <>
      {err && <Alert type="error" showIcon message={err} style={{ marginBottom: 12 }} />}
      <Alert type="error" showIcon style={{ marginBottom: 12 }}
             message="食品安全投诉不可逆 —— 别的投诉压一天是体验问题,这个压一天可能是有人进医院。" />
      <Table<FoodSafetyReport>
        rowKey="id" loading={loading} dataSource={rows} size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '时间', dataIndex: 'created_at', width: 150,
            render: (v: string) => v?.replace('T', ' ').slice(0, 16) },
          { title: '类型', dataIndex: 'kind', width: 130,
            render: (v: string) => <Tag color="error">{KINDS[v] ?? v}</Tag> },
          { title: '订单号', dataIndex: 'order_no', width: 185 },
          { title: '描述', dataIndex: 'description', ellipsis: true },
          { title: '凭证', width: 150,
            render: (_, it) => {
              const all = [...(it.images ?? []), ...(it.medical_urls ?? [])]
              return all.length ? (
                <Image.PreviewGroup>
                  {all.slice(0, 4).map((u) => (
                    <Image key={u} src={u} width={30} height={30}
                           style={{ objectFit: 'cover', marginRight: 3 }} />
                  ))}
                </Image.PreviewGroup>
              ) : '—'
            } },
          { title: '状态', dataIndex: 'status', width: 90,
            render: (v: string) => ({
              confirmed: <Tag color="error">已确认</Tag>,
              dismissed: <Tag>已驳回</Tag>,
            }[v] ?? <Tag color="warning">待处理</Tag>) },
          {
            title: '处置', width: 330, fixed: 'right',
            // 已确认 / 已驳回的不再给处置按钮
            render: (_, it) =>
              ['confirmed', 'dismissed'].includes(it.status) ? null : (
              <Space size={4} wrap>
                <Button size="small" danger disabled={acting}
                        onClick={() => ask('确认食安问题属实?', '核实说明', true,
                          (n) => foodSafetyAction(it.id, 'confirm', n), '已确认')}>
                  确认属实
                </Button>
                <Button size="small" disabled={acting}
                        onClick={() => ask('驳回这条投诉?', '驳回理由(会告知投诉人)', false,
                          (n) => foodSafetyAction(it.id, 'dismiss', n), '已驳回')}>
                  驳回
                </Button>
                <Select
                  size="small" style={{ width: 130 }} value={undefined}
                  placeholder="下架涉事菜品…"
                  options={(it.order_items ?? [])
                    .filter((d) => d.dish_id && d.price_cents !== 0)
                    .map((d) => ({ value: d.dish_id, label: d.name }))}
                  onChange={(dishId: number) => ask(
                    '下架这道菜?', '下架备注(整改要求)', true,
                    (n) => takeDownDish(it.id, dishId, n), '菜品已下架')}
                />
                {it.merchant_is_open && (
                  <Button size="small" danger type="primary" disabled={acting}
                          onClick={() => ask('暂停这家店营业?',
                            '整改原因(必填,会推送给商家)', true,
                            (n) => foodSafetyAction(it.id, 'suspend-merchant', n),
                            '已暂停营业')}>
                    暂停营业
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />
    </>
  )
}
