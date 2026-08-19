import { Alert, Button, Descriptions, Image, Input, Modal, Table, Tabs, Tag, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  AdminRiderProfile, ApiError, approveRider, listRiderProfiles, rejectRider,
} from '../api'

/**
 * 骑手实名审核。
 *
 * ## 驳回会把人踢下线
 *
 * 后端在驳回时顺手 `is_online = false` —— 已经在路上的骑手会被强制下线。
 * 所以驳回不是"标个记号回头再说",是**立刻影响运力**的动作。
 * 界面上把这一点说出来,别让人以为只是改了个状态。
 *
 * ## 姓名是打码的
 *
 * `real_name` 后端下发的就是打码值,后台也看不到完整姓名 —— 这是刻意的:
 * 审核要核对的是**证件照片和本人**,不是数据库里的字符串。
 */
export default function RidersPage() {
  const [status, setStatus] = useState('pending')
  const [rows, setRows] = useState<AdminRiderProfile[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [detail, setDetail] = useState<AdminRiderProfile | null>(null)
  const [reason, setReason] = useState('')
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      setRows(await listRiderProfiles(status))
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
      <Table<AdminRiderProfile>
        rowKey="rider_id"
        loading={loading}
        dataSource={rows}
        size="middle"
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: '骑手', dataIndex: 'real_name', width: 120 },
          { title: '手机号', dataIndex: 'rider_phone', width: 130 },
          { title: '城市', dataIndex: 'city', width: 90 },
          {
            title: '培训考试', width: 110,
            render: (_, r) => r.exam_passed
              ? <Tag color="success">已通过{r.exam_best_score ? ` ${r.exam_best_score} 分` : ''}</Tag>
              : <Tag>未通过</Tag>,
          },
          {
            title: '健康证', width: 110,
            render: (_, r) => !r.health_cert_required
              ? <span style={{ color: 'var(--sz-ink-muted)' }}>本市不要求</span>
              : r.health_cert_photo_url
                ? <Tag color="success">已上传</Tag>
                : <Tag color="warning">缺</Tag>,
          },
          {
            title: '操作', width: 100, fixed: 'right',
            render: (_, r) => (
              <Button type="link" onClick={() => { setDetail(r); setReason('') }}>
                看材料
              </Button>
            ),
          },
        ]}
      />

      <Modal
        open={!!detail}
        title={`骑手 ${detail?.real_name ?? ''}`}
        onCancel={() => setDetail(null)}
        width={620}
        footer={detail?.status === 'pending' ? [
          <Button key="reject" danger loading={acting} onClick={() => {
            const r = reason.trim()
            if (r.length < 2) {
              message.warning('请写清驳回理由 —— 骑手要照着它重交')
              return
            }
            void act(() => rejectRider(detail!.rider_id, r),
                     '已驳回,该骑手已被强制下线')
          }}>
            驳回并下线
          </Button>,
          <Button key="ok" type="primary" loading={acting}
                  onClick={() => detail && act(
                    () => approveRider(detail.rider_id), '已通过,骑手可以上线接单')}>
            通过
          </Button>,
        ] : null}
      >
        {detail && (
          <>
            <Descriptions column={2} size="small" bordered
                          style={{ marginBottom: 12 }}>
              <Descriptions.Item label="姓名">{detail.real_name}</Descriptions.Item>
              <Descriptions.Item label="手机号">{detail.rider_phone}</Descriptions.Item>
              <Descriptions.Item label="城市">{detail.city || '—'}</Descriptions.Item>
              <Descriptions.Item label="实名核验">
                {detail.id_verified
                  ? <Tag color="success">已核验</Tag>
                  : <Tag color="warning">未核验</Tag>}
              </Descriptions.Item>
              {detail.status === 'rejected' && (
                <Descriptions.Item label="上次驳回理由" span={2}>
                  {detail.reject_reason}
                </Descriptions.Item>
              )}
            </Descriptions>

            {detail.health_cert_required ? (
              detail.health_cert_photo_url ? (
                <Image src={detail.health_cert_photo_url} width={200} />
              ) : (
                <Alert type="warning" showIcon
                       message="本市要求健康证,但骑手还没上传" />
              )
            ) : (
              <Alert type="info" showIcon
                     message="本市不要求送餐员持健康证(开关在「平台开关」里配)" />
            )}

            {detail.status === 'pending' && (
              <>
                <Alert type="warning" showIcon style={{ margin: '12px 0' }}
                       message="驳回会立刻把这名骑手强制下线" />
                <Input.TextArea
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  maxLength={200}
                  showCount
                  placeholder="驳回理由(会回传给骑手,写清楚要补什么)"
                />
              </>
            )}
          </>
        )}
      </Modal>
    </>
  )
}
