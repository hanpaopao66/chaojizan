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

// ---------- 数据看板 ----------

export interface DashboardOut {
  today: {
    orders: number
    gmv_cents: number
    commission_cents: number
    active_merchants: number
    active_riders: number
    new_users: number
  }
  trend_7d: { day: string; orders: number; gmv: number }[]
  pending: {
    merchants: number
    riders: number
    withdrawals: number
    tickets: number
    after_sales: number
    stay_orders: number
    stay_aftersales: number
  }
  totals: { users: number; merchants: number; riders: number; orders: number }
  audit_alerts: { check: string; detail: string; created_at: string }[]
}

export const getDashboard = () => get<DashboardOut>('/admin/dashboard')

// ---------- 客服工单 ----------

export interface Ticket {
  id: number
  role: string
  status: string
  content: string
  reply: string
  contact: string
  user_phone: string
  created_at: string
}

export const listTickets = () => get<Ticket[]>('/admin/tickets')
export const replyTicket = (id: number, reply: string) =>
  post(`/admin/tickets/${id}/reply`, { reply })
export const closeTicket = (id: number) => post(`/admin/tickets/${id}/close`)

// ---------- 售后仲裁 ----------

export interface AfterSale {
  id: number
  order_no: string
  status: string
  reason: string
  fault: string
  images: string[]
  refund_cents: number
  total_cents: number
  created_at: string
}

export const listAfterSales = (days = 7) =>
  get<AfterSale[]>(`/admin/after-sales?days=${days}`)
/** 判骑手责任:全额退用户(含配送费),商家骑手收入不动,损失走骑手保障金 */
export const riderFault = (id: number, reason: string) =>
  post<{ refunded_cents: number }>(`/admin/after-sales/${id}/rider-fault`, { reason })

// ---------- 配送异常 ----------

export interface DeliveryIssue {
  id: number
  order_no: string
  kind: string
  note: string
  photo_url: string
  address: string
  contact_phone: string
  rider_name: string
  rider_phone: string
  order_status: string
  created_at?: string
}

export const listDeliveryIssues = (status = 'open') =>
  get<DeliveryIssue[]>(`/admin/delivery-issues?status=${status}`)
/** 处置配送异常。**action 是必填的** —— 后端是 Literal,少传直接 422。
 *  - continue_delivery 让骑手继续送
 *  - mark_delivered 判定已送达
 *  - refund 退款 */
export type IssueAction = 'continue_delivery' | 'mark_delivered' | 'refund'

export const resolveDeliveryIssue = (
  id: number, action: IssueAction, note: string,
) => post(`/admin/delivery-issues/${id}/resolve`, { action, note })

// ---------- 食安投诉 ----------

export interface FoodSafetyReport {
  id: number
  order_no: string
  kind: string
  description: string
  status: string
  customer_phone: string
  images: string[]
  medical_urls: string[]
  merchant_is_open: boolean
  merchant_id?: number
  order_items?: { dish_id: number; name: string; price_cents: number }[]
  created_at?: string
}

export const listFoodSafety = () => get<FoodSafetyReport[]>('/admin/food-safety')
export const foodSafetyAction = (
  id: number, action: 'confirm' | 'dismiss' | 'suspend-merchant', note: string,
) => post(`/admin/food-safety/${id}/${action}`, { note })
export const takeDownDish = (id: number, dishId: number, note: string) =>
  post(`/admin/food-safety/${id}/take-down-dish`, { dish_id: dishId, note })

// ---------- 内容审核 ----------

export interface ContentReview {
  id: number
  kind: string
  url: string
  created_at: string
}

export const listContentReviews = () =>
  get<ContentReview[]>('/admin/content-reviews?status=pending')
export const approveContent = (id: number) =>
  post(`/admin/content-reviews/${id}/approve`)
export const rejectContent = (id: number) =>
  post(`/admin/content-reviews/${id}/reject`)

export interface ModerationWord {
  id: number
  word: string
  category: string
  created_at?: string
}

export const listModerationWords = () =>
  get<ModerationWord[]>('/admin/moderation-words')
export const addModerationWord = (word: string, category: string) =>
  post('/admin/moderation-words', { word, category })
export const delModerationWord = (id: number) =>
  request<void>('DELETE', `/admin/moderation-words/${id}`)

// ---------- 风控 ----------

export interface RiskOrder {
  id: number
  order_no: string
  merchant_name: string
  customer_phone: string
  customer_id: number
  customer_risk_level: string
  hits: string[]
  total_cents: number
  order_status: string
  risk_status: string
  created_at: string
}

export const listRiskOrders = () => get<RiskOrder[]>('/admin/risk-orders?status=')
export const riskVerdict = (id: number, verdict: 'confirmed' | 'cleared') =>
  post(`/admin/risk-orders/${id}/verdict`, { verdict })
export const setRiskLevel = (userId: number, level: string, reason: string) =>
  post(`/admin/users/${userId}/risk-level`, { level, reason })

// ---------- 判责申诉 ----------

export interface Appeal {
  id: number
  role: string
  name: string
  phone: string
  reason: string
  target_type: string
  target_summary: string
  images: string[]
  created_at: string
}

export const listAppeals = () => get<Appeal[]>('/admin/appeals?status=open')
export const resolveAppeal = (
  id: number, result: 'overturned' | 'upheld', note: string,
) => post(`/admin/appeals/${id}/resolve`, { result, note })

// ---------- 运力 ----------

export interface DispatchOverview {
  stats: Record<string, number>
  pool: { order_no: string; merchant_name: string; wait_minutes: number;
          tip_cents: number; status: string }[]
  in_flight: { order_no: string; merchant_name: string; status: string;
               wait_minutes: number }[]
  riders: { rider_id: number; name?: string; phone?: string;
            is_online?: boolean; active?: number }[]
}

export const getDispatch = () => get<DispatchOverview>('/admin/dispatch-overview')
export const reassignOrder = (orderNo: string) =>
  post(`/admin/orders/${orderNo}/reassign`)

// ---------- 骑手关怀(事故 / 求助 / 装备) ----------

export interface RiderAccident {
  id: number
  rider_phone: string
  severity: string
  description: string
  photos: string[]
  status: string
  created_at: string
}

export interface RiderEmergency {
  id: number
  rider_phone: string
  lat: number
  lng: number
  note: string
  status: string
  created_at: string
}

export interface RiderGear {
  id: number
  rider_phone: string
  item_label: string
  created_at: string
}

export const listAccidents = (status: string) =>
  get<RiderAccident[]>(`/admin/rider-accidents?status=${status}`)
export const updateAccident = (id: number, status: string, note: string) =>
  post(`/admin/rider-accidents/${id}/update`, { status, note })
export const listEmergencies = (status: string) =>
  get<RiderEmergency[]>(`/admin/rider-emergencies?status=${status}`)
export const updateEmergency = (id: number, status: string, note: string) =>
  post(`/admin/rider-emergencies/${id}/update`, { status, note })
export const listGear = () => get<RiderGear[]>('/admin/rider-gear?status=requested')
export const issueGear = (id: number) => post(`/admin/rider-gear/${id}/issue`)

// ---------- 营销 ----------

export interface CouponBatch {
  id: number
  name: string
  trigger: string
  amount_cents: number
  min_spend_cents: number
  valid_days: number
  total: number
  issued: number
  used: number
  active: boolean
}

export const listCouponBatches = () => get<CouponBatch[]>('/admin/coupon-batches')
export const toggleCouponBatch = (id: number) =>
  post(`/admin/coupon-batches/${id}/toggle`)
export const createCouponBatch = (b: {
  name: string; trigger: string; amount_cents: number
  min_spend_cents: number; valid_days: number; total: number
}) => post('/admin/coupon-batches', b)

// ---------- 开票 ----------

export interface Invoice {
  id: number
  merchant_name: string
  owner_phone: string
  title: string
  tax_no: string
  email: string
  period: string
  amount_cents: number
  created_at: string
}

export const listInvoices = () => get<Invoice[]>('/admin/invoices?status=pending')
export const issueInvoice = (id: number, url: string) =>
  post(`/admin/invoices/${id}/issue`, { url })
export const rejectInvoice = (id: number, reason: string) =>
  post(`/admin/invoices/${id}/reject`, { reason })

// ---------- 住宿 ----------

export interface StayOrder {
  order_no: string
  hotel: string
  room_type: string
  rooms_qty: number
  nights: number
  checkin_date: string
  checkout_date: string
  guest_name: string
  status: string
  total_cents: number
  fee_cents: number
  net_cents: number
  refund_cents: number
}

export interface StayAfterSale {
  id: number
  order_no: string
  hotel: string
  kind: string
  note: string
  status: string
  refund_cents: number
  penalty_cents: number
  created_at: string
}

export const listStayOrders = (status: string, day: string) => {
  const qs = [status && `status=${status}`, day && `day=${day}`]
    .filter(Boolean).join('&')
  return get<StayOrder[]>(`/admin/stay-orders${qs ? `?${qs}` : ''}`)
}
export const listStayAftersales = () =>
  get<StayAfterSale[]>('/admin/stay-aftersales')

// ---------- 税务导出 ----------

/** 带 token 下载 CSV。URL 里不能带凭证 —— 会进浏览器历史和服务器日志。 */
export async function downloadTax(kind: string, period: string) {
  const token = getToken()
  const resp = await fetch(`/admin/tax/${kind}.csv?period=${period}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!resp.ok) throw new ApiError(resp.status, `导出失败(${resp.status})`)
  const url = URL.createObjectURL(await resp.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = `${kind}-${period}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// ---------- 补齐:旧后台有而这里缺的 ----------

/** 已有商家的城市清单 + 当前开城清单。改「开城清单」开关时对着它填,
 *  免得手敲城市名敲错一个字导致整城停摆。 */
export interface CitiesOut {
  cities: { city: string; merchants: number }[]
  open_cities: string[]
}
export const getCities = () => get<CitiesOut>('/admin/cities')

export const setMerchantCategory = (id: number, category: string) =>
  post(`/admin/merchants/${id}/category`, { category })
export const setMerchantCity = (id: number, city: string) =>
  post(`/admin/merchants/${id}/city`, { city })
/** 二清收口:回填微信特约商户号。ready=true 之后新订单货款走分账。 */
export const setSubMchid = (id: number, subMchid: string, ready: boolean) =>
  post(`/admin/merchants/${id}/sub-mchid`, { sub_mchid: subMchid, ready })

/** 定向发券:给指定手机号发某个批次的券。 */
export const issueCoupon = (phone: string, batchId: number) =>
  post('/admin/coupons/issue', { phone, batch_id: batchId })

/** T+1 批量打款:昨天及更早申请的 pending 一键打完。 */
export const t1BatchPaid = () => post<{ done: number }>('/admin/withdrawals/t1-batch-paid')

/** 打款退票(银行退回/收款信息有误):余额自动退回,自动开工单跟进。 */
export const markWithdrawalFailed = (id: number, reason: string) =>
  post(`/admin/withdrawals/${id}/failed`, { reason })

/** 骑手工作明细(考核用) */
export const getRiderWorklog = (riderId: number, days = 14) =>
  get<unknown>(`/admin/riders/${riderId}/worklog?days=${days}`)

/** 食安投诉导出 CSV(监管报送用) */
export async function downloadFoodSafetyCsv() {
  const token = getToken()
  const resp = await fetch('/admin/food-safety.csv', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!resp.ok) throw new ApiError(resp.status, `导出失败(${resp.status})`)
  const url = URL.createObjectURL(await resp.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = 'food-safety.csv'
  a.click()
  URL.revokeObjectURL(url)
}

// ---------- 开屏图(在 platform 路由下,不是 /admin) ----------

export interface Splash {
  id: number
  title: string
  subtitle: string
  image_url: string
  audience: string
  countdown_seconds: number
  starts_at: string
  ends_at: string
  is_active: boolean
}
export const listSplash = () => get<Splash[]>('/platform/splash')
export const toggleSplash = (id: number) => post(`/admin/splash/${id}/toggle`)

// ---------- 异常订单标记(商家上报,平台跨店核查) ----------

export interface OrderFlagDetail {
  id: number
  shop: string
  order_no: string
  kind: string
  reason: string
  status: string
  created_at: string | null
}

export interface OrderFlagPerson {
  user_id: number
  name: string
  phone: string
  shop_count: number
  flags: number
  pending: number
  kinds: Record<string, number>
  details: OrderFlagDetail[]
}

export interface OrderFlagsOut {
  items: OrderFlagPerson[]
  only_cross_shop: boolean
  how_to_read: string
}

export function listOrderFlags(onlyCrossShop: boolean) {
  return request<OrderFlagsOut>(
    'GET', `/admin/order-flags?only_cross_shop=${onlyCrossShop}`)
}

export function resolveOrderFlag(flagId: number, result: 'reviewed' | 'dismissed') {
  return request<{ ok: boolean; status: string }>(
    'POST', `/admin/order-flags/${flagId}/resolve`, { result })
}
