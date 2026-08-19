/**
 * 平台后台的薄 API 客户端。
 *
 * 结构照 `merchant-web/src/api.ts`,但**不共用一份代码**:两个后台跑在
 * 不同的构建里,共用要么做 monorepo 包、要么软链,两种都会让
 * "改一处崩另一处"变成常态,而这两边的接口重叠其实只有登录那一小段。
 *
 * 两处**故意不同**:
 * - token 的 localStorage 键不同 —— 同一台电脑上运营既是管理员又可能
 *   是某家店的商家,共用一个键会互相踢下线;
 * - 登录成功后**校验 role=admin**,不是 admin 直接不给进(见 `login`)。
 */

const TOKEN_KEY = 'superz_admin_token'
const TOKEN_AT_KEY = 'superz_admin_token_at'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(TOKEN_AT_KEY, String(Date.now()))
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(TOKEN_AT_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// token 无感续期:超过 1 天龄顺手换新。失败静默,下次请求再试
let refreshing = false

async function maybeRefreshToken(): Promise<void> {
  const token = getToken()
  const issuedAt = Number(localStorage.getItem(TOKEN_AT_KEY) || 0)
  if (!token || refreshing || !issuedAt) return
  if (Date.now() - issuedAt < 86400 * 1000) return
  refreshing = true
  try {
    const resp = await fetch('/auth/refresh', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (resp.ok) setToken(((await resp.json()) as { token: string }).token)
  } catch {
    /* 网络抖动不打断当前操作 */
  } finally {
    refreshing = false
  }
}

export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  await maybeRefreshToken()
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const resp = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (resp.status === 401) {
    clearToken()
    if (!location.pathname.endsWith('/login')) {
      location.assign(`${import.meta.env.BASE_URL}login`)
    }
    throw new ApiError(401, '登录已过期,请重新登录')
  }
  if (!resp.ok) {
    let detail = `请求失败(${resp.status})`
    try {
      const data = await resp.json()
      if (typeof data.detail === 'string') detail = data.detail
      else if (data.detail) detail = JSON.stringify(data.detail)
    } catch {
      /* 非 JSON 响应,用默认文案 */
    }
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return undefined as T
  const text = await resp.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const get = <T>(p: string) => request<T>('GET', p)
export const post = <T>(p: string, b?: unknown) => request<T>('POST', p, b)

/** 金额:分 → 元字符串 */
export function yuan(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`
}

// ---------- 登录 ----------

interface LoginOut {
  token: string
  user_id: number
  role: string
  name?: string
}

/**
 * 登录。**非 admin 一律拒绝。**
 *
 * 后端每个 `/admin/*` 接口都有 `require_role("admin")`,所以这里的检查
 * 不是安全边界 —— 它挡的是**误入**:商家或骑手用自己的号登进来,
 * 看到一个什么都点不动、每次点击都弹 403 的界面,会以为是系统坏了。
 * 在登录这一步说清楚"这个号不是管理员",比让他在里面撞十次墙好。
 */
export async function login(phone: string, password: string): Promise<LoginOut> {
  const out = await request<LoginOut>('POST', '/auth/login', { phone, password })
  if (out.role !== 'admin') {
    // 拿到 token 也不存 —— 存了下次打开会直接进一个空后台
    throw new ApiError(403, '这个账号不是平台管理员,请用管理员账号登录')
  }
  setToken(out.token)
  return out
}

// ---------- 商家审核 ----------

export interface AdminMerchant {
  id: number
  name: string
  status: string
  address: string
  city: string
  biz_type: string
  category: string
  is_open: boolean
  reject_reason: string
  created_at?: string
  // 审核要看的:证照 + 店主联系方式(字段名对着 schemas.AdminMerchantOut,
  // 猜错的话页面上就是一片空白,而且不报错)
  license_no: string
  license_image_url: string
  special_license_no: string
  special_license_image_url: string
  hygiene_image_url: string
  owner_name: string
  owner_phone: string
  // 经营质量(近 30 天):复审时看,不是首次审核用的
  rejects_30d: number
  ready_late_30d: number
}

export const listMerchants = (status: string) =>
  get<AdminMerchant[]>(`/admin/merchants?status=${encodeURIComponent(status)}`)
export const approveMerchant = (id: number) =>
  post<AdminMerchant>(`/admin/merchants/${id}/approve`)
export const rejectMerchant = (id: number, reason: string) =>
  post<AdminMerchant>(`/admin/merchants/${id}/reject`, { reason })

// ---------- 骑手实名 ----------

export interface AdminRiderProfile {
  rider_id: number
  rider_phone: string
  /** 打码后的真名。后端只下发打码值,后台也看不到完整姓名 */
  real_name: string
  status: string
  reject_reason: string
  id_verified: boolean
  health_cert_required: boolean
  health_cert_photo_url: string
  city: string
  created_at?: string
  exam_passed: boolean
  exam_best_score?: number | null
}

export const listRiderProfiles = (status: string) =>
  get<AdminRiderProfile[]>(
    `/admin/rider-profiles?status=${encodeURIComponent(status)}`)
export const approveRider = (id: number) =>
  post<AdminRiderProfile>(`/admin/rider-profiles/${id}/approve`)
export const rejectRider = (id: number, reason: string) =>
  post<AdminRiderProfile>(`/admin/rider-profiles/${id}/reject`, { reason })

// ---------- 平台开关 ----------

export type Flags = Record<string, string>

export const getFlags = () => get<Flags>('/admin/flags')
export const setFlag = (key: string, value: string, reason: string) =>
  post<Flags>(`/admin/flags/${encodeURIComponent(key)}`, { value, reason })

// ---------- 对账自检 ----------

export interface AuditProblem {
  /** 检查项标识,如 merchant_earning_missing */
  check: string
  /** 一句人话,已经把订单号和差额写进去了 */
  detail: string
}

/** 返回形状是 `{problems: 数量, detail: [...]}` —— `problems` 是**个数不是数组**。
 *  猜成数组的话页面会渲染成空,而且不报错。 */
export const runAudit = () =>
  post<{ problems: number; detail: AuditProblem[] }>('/admin/audit/run')

// ---------- 提现打款 ----------

export interface AdminWithdrawal {
  id: number
  amount_cents: number
  status: string
  reject_reason: string
  paid_note: string
  created_at: string
  processed_at?: string | null
  /** rider / merchant —— 打款对象类型 */
  role: string
  name: string
  phone: string
  account_kind: string
  account_holder: string
  account_bank: string
  account_no: string
  /** 收款账户近期改过。**打款前必看** —— 改账户 + 立刻提现是典型的盗号套路 */
  account_recently_changed: boolean
}

export const listWithdrawals = (status: string) =>
  get<AdminWithdrawal[]>(
    `/admin/withdrawals?status=${encodeURIComponent(status)}`)
export const markPaid = (id: number, note: string) =>
  post<AdminWithdrawal>(`/admin/withdrawals/${id}/paid`, { note })
export const rejectWithdrawal = (id: number, reason: string) =>
  post<AdminWithdrawal>(`/admin/withdrawals/${id}/reject`, { reason })
export const batchPaid = (ids: number[], note: string) =>
  post<{ done: number }>('/admin/withdrawals/batch-paid', { ids, note })

// ---------- 操作留痕 ----------

export interface ActionLog {
  id: number
  admin_id: number
  admin_phone: string
  action: string
  target_type: string
  target_id: string
  detail: Record<string, unknown>
  created_at: string
}

export const listActionLogs = (q: {
  action?: string
  target_type?: string
  target_id?: string
  limit?: number
} = {}) => {
  const qs = Object.entries(q)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&')
  return get<ActionLog[]>(`/admin/action-logs${qs ? `?${qs}` : ''}`)
}
