import { PlusOutlined } from '@ant-design/icons'
import {
  Alert, Button, Card, DatePicker, Form, InputNumber, Modal, Popconfirm,
  Select, Space, Table, Tag, message,
} from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'

import {
  addDishSchedule, ApiError, cancelDishSchedule, Dish, DishSchedule,
  dishSchedules, myDishes, yuan,
} from '../../api'

/**
 * 定时改价 / 定时上下架。
 *
 * ## 和「供应时段」不是一回事
 *
 * 供应时段是**每天重复**的(早餐只在 6-10 点卖),到点只是灰掉,不改价。
 * 这里是**一次性**的:周五晚上八点降价清库存、下周一恢复原价。
 * 两个都叫"定时",商家很容易搞混,所以页面上要直说区别 ——
 * 用错的结果是他以为设了每天生效,实际只跑了一次。
 *
 * ## 错过太久的不补跑
 *
 * 服务端的规则:清扫任务挂了两天再起来,不会把三天前该降的价降下来。
 * 这个必须写在界面上 —— 商家的默认预期是"我设了就一定会执行",
 * 而"三天后突然降价"比"没执行"糟得多。
 */
export default function SchedulesPage() {
  const [items, setItems] = useState<DishSchedule[]>([])
  const [dishes, setDishes] = useState<Dish[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [r, d] = await Promise.all([dishSchedules(), myDishes()])
      setItems(r.items)
      setDishes(d)
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const ACTIONS: Record<string, { label: string; color: string }> = {
    price: { label: '改价', color: 'blue' },
    on: { label: '上架', color: 'green' },
    off: { label: '下架', color: 'orange' },
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title="定时改价 / 上下架"
        extra={
          <Button type="primary" icon={<PlusOutlined />}
            onClick={() => setOpen(true)}>新增定时</Button>
        }
      >
        <Alert
          type="info" showIcon style={{ marginBottom: 12 }}
          message="一次性动作,不是每天重复"
          description={
            <>
              想让某道菜每天只在固定时段卖,用菜品编辑里的「供应时段」——
              那个每天生效、只灰掉不改价。这里是一次性的:到点执行一次就结束。
              <br />
              <b>错过太久的不会补跑</b> —— 系统停了两天再起来,
              不会把三天前该降的价降下来。那样你会莫名其妙亏一笔。
            </>
          }
        />
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={items}
          pagination={{ pageSize: 20, hideOnSinglePage: true }}
          locale={{ emptyText: '还没有排定的定时动作' }}
          columns={[
            { title: '菜品', dataIndex: 'dish_name', ellipsis: true },
            {
              title: '动作', width: 130,
              render: (_, r) => (
                <>
                  <Tag color={ACTIONS[r.action]?.color}>
                    {ACTIONS[r.action]?.label ?? r.action}
                  </Tag>
                  {r.action === 'price' && r.price_cents !== null
                    && <b>{yuan(r.price_cents)}</b>}
                </>
              ),
            },
            {
              title: '执行时刻', dataIndex: 'run_at', width: 180,
              render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
            },
            {
              title: '状态', width: 110,
              render: (_, r) => r.status === 'pending'
                ? <Tag>等待执行</Tag>
                : r.status === 'done'
                  ? <Tag color="green">已执行</Tag>
                  : <Tag color="default">{r.status}</Tag>,
            },
            { title: '备注', dataIndex: 'note', ellipsis: true },
            {
              title: '', width: 70,
              render: (_, r) => r.status !== 'pending' ? null : (
                <Popconfirm
                  title="取消这条定时?"
                  onConfirm={async () => {
                    try {
                      await cancelDishSchedule(r.id)
                      message.success('已取消')
                      load()
                    } catch (e) {
                      message.error(e instanceof ApiError
                        ? e.message : String(e))
                    }
                  }}
                >
                  <Button type="link" danger size="small">取消</Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        open={open} title="新增定时动作" footer={null} destroyOnClose
        onCancel={() => setOpen(false)}
      >
        <NewScheduleForm
          dishes={dishes}
          onDone={() => { setOpen(false); load() }}
        />
      </Modal>
    </Space>
  )
}

function NewScheduleForm(
  { dishes, onDone }: { dishes: Dish[]; onDone: () => void },
) {
  const [form] = Form.useForm()
  const [busy, setBusy] = useState(false)
  const action = Form.useWatch('action', form)

  return (
    <Form
      form={form} layout="vertical"
      initialValues={{ action: 'price', run_at: dayjs().add(1, 'hour') }}
      onFinish={async (v) => {
        setBusy(true)
        try {
          await addDishSchedule({
            dish_id: v.dish_id,
            action: v.action,
            price_cents: v.action === 'price'
              ? Math.round(v.price * 100) : undefined,
            // 后端按 ISO 解析;带上时区偏移,免得服务器和商家不在同一时区时差几小时
            run_at: dayjs(v.run_at).toISOString(),
            // tags 模式给的是数组,取第一个 —— 直接传数组后端存进去
            // 就成了 "['周末清库存']" 那种字符串
            note: Array.isArray(v.note) ? v.note[0] : v.note,
          })
          message.success('已排定')
          onDone()
        } catch (e) {
          message.error(e instanceof ApiError ? e.message : String(e))
        } finally {
          setBusy(false)
        }
      }}
    >
      <Form.Item name="dish_id" label="哪道菜"
        rules={[{ required: true, message: '选一道菜' }]}>
        <Select
          showSearch
          optionFilterProp="label"
          placeholder="搜菜名"
          options={dishes.map((d) => ({
            value: d.id, label: `${d.name}(现价 ${yuan(d.price_cents)})`,
          }))}
        />
      </Form.Item>
      <Form.Item name="action" label="到点做什么" rules={[{ required: true }]}>
        <Select options={[
          { value: 'price', label: '改成新价格' },
          { value: 'on', label: '上架' },
          { value: 'off', label: '下架' },
        ]} />
      </Form.Item>
      {action === 'price' && (
        <Form.Item name="price" label="新价格(元)"
          rules={[{ required: true, message: '填新价格' }]}>
          <InputNumber min={0.01} max={9999} step={1} precision={2}
            style={{ width: '100%' }} />
        </Form.Item>
      )}
      <Form.Item name="run_at" label="什么时候执行"
        rules={[{ required: true, message: '选一个时间' }]}
        extra="错过太久的不会补跑 —— 三天后突然降价比没执行糟得多">
        <DatePicker
          showTime={{ format: 'HH:mm' }} format="YYYY-MM-DD HH:mm"
          style={{ width: '100%' }}
          disabledDate={(d) => d.isBefore(dayjs().startOf('day'))}
        />
      </Form.Item>
      <Form.Item name="note" label="备注(只你自己看得到)">
        <Select
          allowClear mode="tags" maxCount={1}
          placeholder="如:周末清库存"
          options={[
            { value: '周末清库存' }, { value: '活动结束恢复原价' },
            { value: '临期特价' },
          ]}
        />
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={busy} block>
        排定
      </Button>
    </Form>
  )
}
