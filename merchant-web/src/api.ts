/**
 * 薄 API 客户端:fetch + token 注入 + 401 跳登录 + 中文错误透传。
 * 后端与商家 App 同一套接口,这里不做代码生成,按用到的接口手写类型。
 */

const TOKEN_KEY = 'superz_merchant_token'
const TOKEN_AT_KEY = 'superz_merchant_token_at'

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
  localStorage.removeItem(SHOP_KEY)
}

// ---------- 当前门店(连锁) ----------
//
// 单店商家永远用不到这个:不设置时后端退回"我唯一的那家店",
// 与加连锁之前一字不差。连锁下所有请求带 X-Shop-Id,后端在权限解析
// 那一处统一读 —— 这个头只是**选哪家**,权限仍由后端另判,
// 手改成别人家的 id 只会拿到 404。
const SHOP_KEY = 'superz_merchant_shop_id'

export function getShopId(): number | null {
  const v = Number(localStorage.getItem(SHOP_KEY) || 0)
  return v > 0 ? v : null
}

export function setShopId(id: number) {
  localStorage.setItem(SHOP_KEY, String(id))
}

/** 切店:整页重载。
 *
 * 看着粗暴,但比逐页失效可靠得多 —— 页面里缓存着上一家店的订单、
 * 菜单、营业额,漏掉任何一处就是"切到二店,屏幕上还是总店的数",
 * 而这种错屏用户完全看不出来。切店本来就是低频动作,重载一次不亏。
 */
export function switchShop(id: number) {
  if (id === getShopId()) return
  setShopId(id)
  location.reload()
}

// token 无感续期(与三端 App 同款):超过 1 天龄就顺手换新,
// 30 天有效期 + 滑动续期 = 常用的商家永不掉线;失败静默,下次请求再试
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
    if (resp.ok) {
      const data = (await resp.json()) as TokenOut
      setToken(data.token)
    }
  } catch {
    /* 网络抖动不打断当前操作 */
  } finally {
    refreshing = false
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
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
  const shopId = getShopId()
  if (shopId) headers['X-Shop-Id'] = String(shopId)
  const resp = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (resp.status === 401) {
    clearToken()
    // 未登录/过期:回登录页(带上当前路径便于回跳)
    if (!location.pathname.endsWith('/login')) {
      location.hash = ''
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

/** 下载需要带 token 的文件(如对账 CSV):fetch blob 落地,URL 不带凭证 */
export async function downloadFile(path: string, filename: string) {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const shopId = getShopId()
  // 对账 CSV 也要跟着当前门店走,否则切了店导出的还是上一家的账
  if (shopId) headers['X-Shop-Id'] = String(shopId)
  const resp = await fetch(path, { headers })
  if (!resp.ok) throw new ApiError(resp.status, `下载失败(${resp.status})`)
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** 金额:分 → 元字符串 */
export function yuan(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`
}

// ---------- 认证 ----------

export interface TokenOut {
  token: string
  user_id: number
  role: string
  name: string
}

export async function sendSmsCode(phone: string): Promise<string | null> {
  const data = await request<{ sent: boolean; dev_code?: string }>(
    'POST', '/auth/sms-code', { phone })
  return data.dev_code ?? null
}

export function smsLogin(phone: string, code: string): Promise<TokenOut> {
  return request('POST', '/auth/sms-login',
    { phone, code, role: 'merchant', device_id: 'merchant-web' })
}

export function passwordLogin(phone: string, password: string): Promise<TokenOut> {
  return request('POST', '/auth/login',
    { phone, password, role: 'merchant', device_id: 'merchant-web' })
}

// ---------- 店铺 ----------

export interface Merchant {
  id: number
  name: string
  description: string
  address: string
  biz_type: 'food' | 'hotel'
  category: string
  is_open: boolean
  status: 'pending' | 'approved' | 'rejected'
  reject_reason: string
  announcement: string
  logo_url: string
  photo_urls: string[]
  open_time: string
  close_time: string
  min_order_cents: number
  packing_fee_cents: number
  promise_ready_minutes: number
  self_delivery: boolean
  commission_rate: string | number
  viewer_is_staff: boolean
  /** 是不是这家店登记的经营者本人。连锁的区域经理不是店员但也不是本人,
   *  资金动作(对账/提现)服务端一律 403 —— 据此隐藏入口 */
  viewer_is_owner: boolean
  license_expires_at: string | null
  license_stage: LicenseStage
  license_days_left: number | null
  busy_active: boolean
  busy_until: string | null
  busy_extra_minutes: number
  /** 食安封签(商家自述,非平台认证) */
  food_seal: boolean
}

export function myShop(): Promise<Merchant> {
  return request('GET', '/merchants/me')
}

export function updateShop(fields: Record<string, unknown>): Promise<Merchant> {
  return request('PATCH', '/merchants/me', fields)
}

/** 忙碌模式:开(minutes 时长 / extraMinutes 出餐加时)或关(off);到点自动失效 */
export function setBusy(opts: {
  minutes?: number
  extraMinutes?: number
  off?: boolean
}): Promise<Merchant> {
  return request('POST', '/merchants/me/busy', opts.off
    ? { off: true }
    : { minutes: opts.minutes, extra_minutes: opts.extraMinutes })
}

/** WebSocket 地址(同源;dev 走 vite ws 代理) */
export function merchantWsUrl(merchantId: number): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/merchants/${merchantId}?token=${getToken()}`
}

// ---------- 图片上传 ----------

/** 与后端 storage.PURPOSES 对齐:决定这张图进公开桶还是私密桶 */
export type UploadPurpose =
  | 'dish' | 'shop' | 'gallery' | 'room' | 'avatar' | 'review'
  | 'license' | 'id_card' | 'health_cert'

/** 上传输入框统一的格式白名单(和后端 ALLOWED_EXTENSIONS 一致) */
export const UPLOAD_ACCEPT = '.jpg,.jpeg,.png,.webp'

const MAX_UPLOAD_BYTES = 5 * 1024 * 1024

/**
 * 前端压缩:长边 ≤1600、转 JPEG。商家直接拖单反原图会超后端 5MB 限制,
 * 压不动或浏览器不支持时原样返回,让后端来兜底判。
 */
async function compressImage(file: File): Promise<Blob> {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return file
  try {
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height))
    if (scale === 1 && file.size <= 2 * 1024 * 1024) return file
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', 0.85))
    return blob && blob.size < file.size ? blob : file
  } catch {
    return file
  }
}

export async function uploadImage(
  file: File,
  purpose: UploadPurpose,
  onProgress?: (percent: number) => void,
): Promise<string> {
  const blob = await compressImage(file)
  if (blob.size > MAX_UPLOAD_BYTES) {
    throw new ApiError(413, '图片压缩后仍超过 5MB,请更换更小的图片')
  }
  const form = new FormData()
  const name = blob === file
    ? file.name
    : `${file.name.replace(/\.[^.]*$/, '')}.jpg`
  form.append('file', blob, name)
  form.append('purpose', purpose)
  const token = getToken()
  // XMLHttpRequest 而非 fetch:要给 antd Upload 回报上传进度
  return await new Promise<string>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/upload')
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.timeout = 60_000
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve((JSON.parse(xhr.responseText) as { url: string }).url)
        return
      }
      let detail = `上传失败(${xhr.status})`
      try {
        const data = JSON.parse(xhr.responseText) as { detail?: unknown }
        if (typeof data.detail === 'string') detail = data.detail
      } catch { /* 非 JSON 响应,用默认文案 */ }
      reject(new ApiError(xhr.status, detail))
    }
    xhr.onerror = () => reject(new ApiError(0, '网络异常,上传失败,请重试'))
    xhr.ontimeout = () => reject(new ApiError(0, '上传超时,请检查网络后重试'))
    xhr.send(form)
  })
}

// ---------- 住宿:房型与房价房态 ----------

export interface RoomType {
  id: number
  name: string
  bed_type: string
  area_m2: number
  max_guests: number
  image_urls: string[]
  facilities: string[]
  cancel_policy: 'limited_free' | 'first_night' | 'strict'
  free_cancel_until: string
  is_on_sale: boolean
  sort: number
}

export interface RoomDay {
  date: string
  price_cents: number
  total_qty: number
  sold_qty: number
  closed: boolean
}

export interface RoomCalendarRow {
  room_type_id: number
  room_type_name: string
  days: RoomDay[]
}

export const CANCEL_POLICIES: Record<string, string> = {
  limited_free: '限时免费取消',
  first_night: '取消扣首晚',
  strict: '不可退',
}

export function stayRoomTypes(): Promise<RoomType[]> {
  return request('GET', '/stays/me/room-types')
}

export function createRoomType(fields: Record<string, unknown>): Promise<RoomType> {
  return request('POST', '/stays/me/room-types', fields)
}

export function updateRoomType(
  id: number, fields: Record<string, unknown>,
): Promise<RoomType> {
  return request('PATCH', `/stays/me/room-types/${id}`, fields)
}

export function stayCalendar(fromDate: string, days: number): Promise<RoomCalendarRow[]> {
  return request('GET', `/stays/me/calendar?from_date=${fromDate}&days=${days}`)
}

export function setStayCalendar(payload: {
  room_type_ids: number[]
  from_date: string
  to_date: string
  price_cents?: number
  total_qty?: number
  closed?: boolean
}): Promise<{ created: number; updated: number }> {
  return request('PUT', '/stays/me/calendar', payload)
}

// ---------- 住宿:订单 / 售后 / 点评 ----------

export interface StayOrder {
  order_no: string
  room_type_name: string
  rooms_qty: number
  checkin_date: string
  checkout_date: string
  nights: number
  guest_name: string
  guest_phone: string
  arrival_note: string
  total_cents: number
  fee_cents: number
  net_cents: number
  refund_cents: number
  refund_note: string
  status: string
  status_label: string
  cancel_policy_text: string
  created_at: string
}

export type StayOrderState = 'all' | 'pending' | 'arriving' | 'inhouse' | 'leaving'

export function stayMerchantOrders(state: StayOrderState): Promise<StayOrder[]> {
  return request('GET', `/stays/me/orders?state=${state}`)
}

export function stayConfirm(orderNo: string): Promise<StayOrder> {
  return request('POST', `/stays/me/orders/${orderNo}/confirm`)
}

export function stayReject(orderNo: string, reason: string): Promise<StayOrder> {
  return request('POST', `/stays/me/orders/${orderNo}/reject`, { reason })
}

export function stayCheckin(orderNo: string): Promise<StayOrder> {
  return request('POST', `/stays/me/orders/${orderNo}/checkin`)
}

export function stayCheckout(orderNo: string): Promise<StayOrder> {
  return request('POST', `/stays/me/orders/${orderNo}/checkout`)
}

export interface StayAfterSale {
  id: number
  kind: 'no_room' | 'nego_refund'
  status: 'pending' | 'accepted' | 'rejected' | 'auto_accepted'
  note: string
  merchant_note: string
  refund_cents: number
  penalty_cents: number
  order_no: string
  guest_name: string
  total_cents: number
  created_at: string
}

export function merchantStayAftersales(): Promise<StayAfterSale[]> {
  return request('GET', '/stays/me/aftersales')
}

export function respondStayAftersale(
  id: number, accept: boolean, note: string, refundCents?: number,
): Promise<StayAfterSale> {
  return request('POST', `/stays/me/aftersales/${id}/respond`, {
    accept, note,
    ...(refundCents !== undefined ? { refund_cents: refundCents } : {}),
  })
}

export interface StayReview {
  id: number
  rating: number
  comment: string
  tags: string[]
  reply: string
  append_content: string
  append_reply: string
  reviewer_name: string
  order_no: string
  created_at: string
}

export function merchantStayReviews(): Promise<StayReview[]> {
  return request('GET', '/stays/me/reviews')
}

export function replyStayReview(id: number, reply: string): Promise<StayReview> {
  return request('POST', `/stays/me/reviews/${id}/reply`, { reply })
}

// ---------- 外卖:订单 ----------

export interface FoodOrderItem {
  dish_id: number
  name: string
  quantity: number
  price_cents: number
}

export interface FoodOrder {
  order_no: string
  status: string
  items: FoodOrderItem[]
  total_cents: number
  address: string
  remark: string
  pickup: boolean
  pickup_code: string
  self_delivery: boolean
  ready_late: boolean
  cancel_reason: string
  refund_cents: number
  refund_note: string
  created_at: string
  accepted_at: string | null
  scheduled_at?: string | null
}

export const FOOD_STATUS_LABELS: Record<string, string> = {
  pending_payment: '待支付', paid: '待接单', accepted: '制作中',
  ready: '待取餐', picked_up: '配送中', delivered: '已送达',
  completed: '已完成', cancelled: '已取消',
}

export function myFoodOrders(q?: string): Promise<FoodOrder[]> {
  return request('GET',
    q ? `/orders?limit=50&q=${encodeURIComponent(q)}` : '/orders')
}

export function foodTransition(
  orderNo: string, toStatus: string, reason = '',
): Promise<FoodOrder> {
  return request('POST', `/orders/${orderNo}/transition`, {
    to_status: toStatus, reason, verify_code: '', force: false,
  })
}

export function foodRefundItem(
  orderNo: string, dishId: number, quantity: number,
): Promise<FoodOrder> {
  return request('POST', `/orders/${orderNo}/refund-item`,
    { dish_id: dishId, quantity })
}

export function foodPickupVerify(orderNo: string, code: string): Promise<FoodOrder> {
  return request('POST', `/orders/${orderNo}/pickup-verify`, { code })
}

export function foodReprint(orderNo: string): Promise<void> {
  return request('POST', `/merchants/me/orders/${orderNo}/print`)
}

export function foodUrgeReply(orderNo: string, text: string): Promise<void> {
  return request('POST', `/orders/${orderNo}/urge-reply`, { text })
}

// ---------- 今日看板 / 待办 ----------

export interface DaySummary {
  orders: number
  gmv_cents: number
  ongoing: number
  done: number
  cancelled: number
  pickup_orders: number
}

export function merchantToday(): Promise<{ today: DaySummary; yesterday: DaySummary }> {
  return request('GET', '/merchants/me/today')
}

export interface Todos {
  pending_orders: number
  after_sales: number
  bad_reviews_unreplied: number
  /** 其中超过 24 小时还没回的(差评 24h 内必回是行业口径) */
  bad_reviews_overdue: number
  coupon_batches_low: number
  flash_expiring: number
  messages_unread: number
}

export function merchantTodos(): Promise<Todos> {
  return request('GET', '/merchants/me/todos')
}

// ---------- 营销效果 / 评分概览 ----------

export interface MarketingStats {
  days: number
  promo: { orders: number; give_cents: number; avg_ticket_cents: number }
  plain: { orders: number; avg_ticket_cents: number }
  coupon: {
    batches: number; issued: number; used: number
    use_rate: number; give_cents: number
  }
  flash: {
    dish_id: number; name: string; price_cents: number
    flash_price_cents: number; until: string; monthly_sales: number
  }[]
  total_give_cents: number
  note: string
}

export function marketingStats(days = 30): Promise<MarketingStats> {
  return request('GET', `/merchants/me/marketing-stats?days=${days}`)
}

export interface RatingWindow {
  count: number
  avg: number | null
  dist: Record<string, number>
  bad_unreplied: number
}

export interface RatingOverview {
  all_time: RatingWindow
  last_30d: RatingWindow
  last_90d: RatingWindow
  trend_30d_vs_earlier: number | null
}

export function ratingOverview(): Promise<RatingOverview> {
  return request('GET', '/merchants/me/reviews/overview')
}

// ---------- 开放接口凭证(POS 对接) ----------

export interface ApiKey {
  id: number
  name: string
  prefix: string
  revoked: boolean
  created_at: string
}

export function myApiKeys(): Promise<ApiKey[]> {
  return request('GET', '/merchants/me/api-keys')
}

/** 返回体里的 token 是唯一一次能拿到明文的机会 */
export function createApiKey(name: string): Promise<ApiKey & { token: string }> {
  return request('POST', '/merchants/me/api-keys', { name })
}

export function revokeApiKey(id: number): Promise<unknown> {
  return request('DELETE', `/merchants/me/api-keys/${id}`)
}

// ---------- 外卖:评价 ----------

export interface FoodReview {
  id: number
  merchant_rating: number
  rider_rating: number | null
  comment: string
  image_urls: string[]
  tags: string[]
  reply: string
  append_content: string
  append_images: string[]
  append_at: string | null
  append_reply: string
  customer_name: string
  created_at: string
}

export function myFoodReviews(opts: {
  maxRating?: number
  unreplied?: boolean
  before?: number
} = {}): Promise<FoodReview[]> {
  const params = new URLSearchParams()
  if (opts.maxRating !== undefined) params.set('max_rating', String(opts.maxRating))
  if (opts.unreplied) params.set('unreplied', 'true')
  if (opts.before !== undefined) params.set('before', String(opts.before))
  const qs = params.toString()
  return request('GET', `/merchants/me/reviews${qs ? `?${qs}` : ''}`)
}

export function replyFoodReview(id: number, reply: string): Promise<FoodReview> {
  return request('POST', `/merchants/me/reviews/${id}/reply`, { reply })
}

export function replyFoodAppend(id: number, reply: string): Promise<FoodReview> {
  return request('POST', `/merchants/me/reviews/${id}/append-reply`, { reply })
}

// ---------- 外卖:菜品 / 店内营销 ----------

export interface DishOptionItem { name: string; price_delta_cents: number }
export interface DishOptionGroup {
  name: string
  required: boolean
  items: DishOptionItem[]
}

export interface Dish {
  id: number
  name: string
  category: string
  price_cents: number
  /** 成本(分/份),0 = 没录过(不是成本为零)。**只商家自己的接口有这个字段** */
  cost_cents?: number
  /** 额外打包费(分/份);null = 用店铺的每单打包费。
   *  **在店铺每单打包费之外另加**,不是替代 */
  packing_fee_cents?: number | null
  stock: number
  daily_stock: number | null
  sold_out_today: boolean
  is_on_sale: boolean
  is_alcohol: boolean
  image_url: string
  sort: number
  description: string
  badges: string[]
  /** 套餐子项(非空 = 这是个套餐);自身 price_cents 即套餐价 */
  combo_items: { dish_id: number; quantity: number }[]
  combo_dishes: { name: string; quantity: number }[]
  combo_original_cents: number
  /** 供应时段 "06:00-10:30"(空 = 全天) */
  serve_window: string
  servable_now: boolean
  options: DishOptionGroup[]
  monthly_sales: number
}

// ---------- 规则中心 / 顾客分层 ----------

export interface Rules {
  sections: { title: string; items: string[] }[]
  note: string
}

export function merchantRules(): Promise<Rules> {
  return request('GET', '/merchants/me/rules')
}

export interface CustomerMix {
  days: number
  new: { customers: number; net_cents: number }
  repeat: { customers: number; net_cents: number }
  churned: { customers: number }
  total_customers: number
  note: string
}

export function merchantCustomers(days = 30): Promise<CustomerMix> {
  return request('GET', `/merchants/me/customers?days=${days}`)
}

// ---------- 流量漏斗 / 合规档案 ----------

export interface Funnel {
  days: number
  impression: number
  visit: number
  checkout: number
  ordered: number
  visit_rate: number
  checkout_rate: number
  order_rate: number
  overall_rate: number
  note: string
}

export function merchantFunnel(days = 7): Promise<Funnel> {
  return request('GET', `/merchants/me/funnel?days=${days}`)
}

export interface Compliance {
  shop_status: string
  reject_reason: string
  food_safety: {
    id: number; kind: string; status: string; order_no: string
    created_at: string
    actions: { action: string; note: string; at: string }[]
  }[]
  rejected_images: { id: number; url: string; note: string; created_at: string }[]
  appeals: {
    target_type: string; target_id: number; status: string; created_at: string
  }[]
  quality_30d: { cancelled: number; ready_late: number }
  used_for: string
  never_used_for: string
}

export function merchantCompliance(): Promise<Compliance> {
  return request('GET', '/merchants/me/compliance')
}

// ---------- 证照有效期与续证 ----------

/** unknown 未登记 / ok / soon(≤30天) / urgent(≤7天) / last(≤1天)
 *  / expired(已过期,宽限期内) / overdue(宽限期满,已停业) */
export type LicenseStage =
  | 'unknown' | 'ok' | 'soon' | 'urgent' | 'last' | 'expired' | 'overdue'

export interface LicenseRenewal {
  id: number
  status: 'pending' | 'approved' | 'rejected'
  license_no: string
  license_expires_at: string | null
  reject_reason: string
  created_at: string
  reviewed_at: string | null
}

export function myLicenseRenewal(): Promise<{ renewal: LicenseRenewal | null }> {
  return request('GET', '/merchants/me/license-renewal')
}

/** 提交续证材料。过审后资质字段一律锁死(能随手把到期日改成 2099 的话,
 *  整个到期闸门就是摆设),换新证只能走这条复审通道;核验期间照常营业。 */
export function submitLicenseRenewal(fields: {
  license_no: string
  license_image_url: string
  license_expires_at: string
  business_license_no?: string
  license_subject?: string
}): Promise<{ ok: boolean; note: string }> {
  return request('POST', '/merchants/me/license-renewal', fields)
}

/** 菜品标签白名单(与服务端 schemas.DISH_BADGES 一致) */
export const DISH_BADGES = [
  '新品', '招牌', '微辣', '中辣', '特辣', '不辣',
  '含花生', '含香菜', '素食', '儿童友好',
]

/** 批量写菜单顺序(小的在前);置顶 = 给一个比同分类现有最小值更小的 sort */
export function reorderDishes(
  items: { dish_id: number; sort: number }[],
): Promise<{ updated: number }> {
  return request('POST', '/merchants/me/dishes/reorder', { items })
}

export function myDishes(): Promise<Dish[]> {
  return request('GET', '/merchants/me/dishes')
}

export function createDish(fields: Record<string, unknown>): Promise<Dish> {
  return request('POST', '/merchants/me/dishes', fields)
}

export function updateDish(id: number, fields: Record<string, unknown>): Promise<Dish> {
  return request('PATCH', `/merchants/me/dishes/${id}`, fields)
}

export function sellOutDish(id: number, cancel: boolean): Promise<void> {
  return request('POST',
    `/merchants/me/dishes/${id}/sell-out${cancel ? '/cancel' : ''}`)
}

export interface PromoRule { threshold_cents: number; off_cents: number }
export interface GiftRule { threshold_cents: number; dish_id: number; name: string }

export interface ShopCouponBatch {
  id: number
  name: string
  /** shop 顾客主动领 / favorite 收藏即送 / referral / birthday / winback */
  trigger: string
  threshold_cents: number
  off_cents: number
  total: number
  issued: number
  per_user_limit: number
  valid_days: number
  active: boolean
}

export function shopCouponBatches(): Promise<ShopCouponBatch[]> {
  return request('GET', '/merchants/me/coupon-batches')
}

export function createShopCouponBatch(
  fields: Record<string, unknown>,
): Promise<ShopCouponBatch> {
  return request('POST', '/merchants/me/coupon-batches', fields)
}

export function toggleShopCouponBatch(id: number): Promise<ShopCouponBatch> {
  return request('POST', `/merchants/me/coupon-batches/${id}/toggle`)
}

// ---------- 对账中心 ----------

export interface Wallet {
  balance_cents: number
  total_earned_cents: number
  pending_withdrawal_cents: number
  withdrawn_cents: number
  deposit_required_cents: number
  deposit_held_cents: number
  withdrawable_cents: number
}

export function merchantWallet(): Promise<Wallet> {
  return request('GET', '/merchants/me/wallet')
}

export interface DayStat {
  day: string
  order_count: number
  food_cents: number
  commission_cents: number
  net_cents: number
}

export function financeDaily(days = 30): Promise<DayStat[]> {
  return request('GET', `/merchants/me/finance/daily?days=${days}`)
}

export interface FinanceOrder {
  order_no: string
  food_cents: number
  commission_cents: number
  net_cents: number
  created_at: string
}

export function financeOrders(day: string): Promise<FinanceOrder[]> {
  return request('GET', `/merchants/me/finance/orders?day=${day}`)
}

export interface Withdrawal {
  id: number
  amount_cents: number
  status: string
  reject_reason: string
  paid_note: string
  created_at: string
  processed_at: string | null
}

export function merchantWithdrawals(): Promise<Withdrawal[]> {
  return request('GET', '/merchants/me/withdrawals')
}

export function createWithdrawal(amountCents: number): Promise<Withdrawal> {
  return request('POST', '/merchants/me/withdrawals',
    { amount_cents: amountCents })
}

export interface CommissionTier {
  commission_rate: number
  tier_rate: number
  tiers: { from_orders: number; rate: number }[]
  last_month_completed: number
  this_month_completed: number
  next_tier_from: number | null
  next_tier_rate: number | null
  orders_to_next: number | null
}

export function commissionTier(): Promise<CommissionTier> {
  return request('GET', '/merchants/me/commission-tier')
}

export interface InvoiceFee {
  period: string
  commission_cents: number
  voucher_fee_cents: number
  stay_fee_cents: number
  total_cents: number
}

export interface InvoiceSummary extends InvoiceFee {
  requested: boolean
  period_ended: boolean
  title: string
  tax_no: string
  email: string
}

export function invoiceSummary(period: string): Promise<InvoiceSummary> {
  return request('GET', `/invoices/summary?period=${period}`)
}

export interface InvoiceRecord {
  id: number
  period: string
  amount_cents: number
  status: string
  title: string
  created_at: string
}

export function myInvoices(): Promise<InvoiceRecord[]> {
  return request('GET', '/invoices/mine')
}

export function applyInvoice(period: string, title: string, taxNo: string,
  email: string): Promise<InvoiceRecord> {
  return request('POST', '/invoices',
    { period, title, tax_no: taxNo, email })
}

// ---------- 店铺设置 ----------

export interface StaffMember {
  user_id: number
  name: string
  phone: string
}

export function myStaff(): Promise<StaffMember[]> {
  return request('GET', '/merchants/me/staff')
}

export function addStaff(phone: string, name: string): Promise<unknown> {
  return request('POST', '/merchants/me/staff', { phone, name })
}

export function removeStaff(userId: number): Promise<unknown> {
  return request('DELETE', `/merchants/me/staff/${userId}`)
}

export function restShop(hours: number | null, untilClose: boolean): Promise<Merchant> {
  return request('POST', '/merchants/me/rest',
    untilClose ? { until_close: true } : { hours })
}

export interface HotelProfileData {
  tier: string
  front_desk_phone: string
  checkin_from: string
  checkout_until: string
  facilities: string[]
  special_license_no: string
}

export function myHotelProfile(): Promise<HotelProfileData> {
  return request('GET', '/stays/me/profile')
}

export function updateHotelProfile(fields: Record<string, unknown>): Promise<unknown> {
  return request('PATCH', '/stays/me/profile', fields)
}

// ---------- 从业人员健康证台账 ----------

export interface HealthCert {
  id: number
  name: string
  role: string
  /** 列表里是打码的;只有刚提交返回的那一条回全号 */
  cert_no: string
  photo_url: string
  issued_at: string | null
  expires_at: string | null
  days_left: number | null
  stage: LicenseStage
  archived: boolean
}

export function healthCerts(includeArchived = false):
Promise<{ items: HealthCert[]; expiring: number; note: string }> {
  return request('GET',
    `/merchants/me/health-certs?include_archived=${includeArchived}`)
}

/** 录一张健康证。同名同岗视为换新证,更新原记录而不是堆两条。 */
export function saveHealthCert(fields: {
  name: string
  role?: string
  cert_no?: string
  photo_url?: string
  issued_at?: string
  expires_at: string
}): Promise<HealthCert> {
  return request('POST', '/merchants/me/health-certs', fields)
}

/** 离职:**归档不删除** —— 监管查的是"当时在岗的人有没有证"。 */
export function archiveHealthCert(id: number): Promise<unknown> {
  return request('DELETE', `/merchants/me/health-certs/${id}`)
}

// ---------- 进货查验台账(食品溯源) ----------

export interface PurchaseRecord {
  id: number
  name: string
  spec: string
  qty: string
  produced_on: string | null
  batch_no: string
  shelf_life_end: string | null
  purchased_on: string
  supplier_name: string
  supplier_address: string
  supplier_phone: string
  supplier_license_url: string
  receipt_url: string
  note: string
  /** 最短留存到期日:保质期满后六个月;没有明确保质期的两年。
   *  **平台不会替你删** —— 到期只代表法律上可以删,不代表该删。 */
  keep_until: string
  created_at: string
  /** 仅新建返回:还缺哪几项法定必记项(不拦,只是说清楚) */
  missing?: string[]
}

/** [q] 按食材名反查(出食安问题时用,不受默认时间窗限制)。 */
export function purchases(q?: string, days = 90):
Promise<{ items: PurchaseRecord[]; note: string }> {
  const qs = q ? `q=${encodeURIComponent(q)}` : `days=${days}`
  return request('GET', `/merchants/me/purchases?${qs}`)
}

export interface SupplierRow {
  name: string
  address: string
  phone: string
  license_url: string
  last_purchased_on: string
}

/** 用过的供货商(去重,最近在前) —— 免得同一家录第三次就没人录了。 */
export function purchaseSuppliers(): Promise<SupplierRow[]> {
  return request('GET', '/merchants/me/purchases/suppliers')
}

export function addPurchase(
  fields: Record<string, unknown>,
): Promise<PurchaseRecord> {
  return request('POST', '/merchants/me/purchases', fields)
}

export function deletePurchase(id: number): Promise<unknown> {
  return request('DELETE', `/merchants/me/purchases/${id}`)
}

// ---------- 连锁店群 ----------

export interface BrandShop {
  id: number
  name: string
  address: string
  status: string
  is_open: boolean
  in_brand: boolean
}

export interface MyBrand {
  brand: { id: number; name: string; logo_url: string; is_owner: boolean } | null
  shops: BrandShop[]
}

/** 我的品牌与门店列表。
 *
 * 单店商家也能调:brand 为 null、shops 一个元素 —— 门店选择器用同一份
 * 数据,客户端不用为"是不是连锁"分两套逻辑。 */
export function myBrand(): Promise<MyBrand> {
  return request('GET', '/brands/me')
}

export function createBrand(name: string, shopId: number): Promise<unknown> {
  return request('POST', '/brands/me', { name, shop_id: shopId })
}

export interface BrandShopStat {
  shop_id: number
  name: string
  status: string
  is_open: boolean
  orders: number
  net_cents: number
  ready_late: number
  rating_avg: number | null
  bad_unreplied: number
}

export interface BrandOverview {
  days: number
  shops: BrandShopStat[]
  total: { shops: number; orders: number; net_cents: number; bad_unreplied: number }
  note: string
}

export function brandOverview(days: number): Promise<BrandOverview> {
  return request('GET', `/brands/me/overview?days=${days}`)
}

export function openBrandShop(fields: Record<string, unknown>): Promise<Merchant> {
  return request('POST', '/brands/me/shops', fields)
}

export interface MenuSyncResult {
  from_shop: number
  dishes: number
  results: { shop_id: number; name: string; created: number; updated: number }[]
  note: string
}

/** 菜单下发:把源门店在售的菜应用到目标门店(按菜名匹配)。
 *  库存与上下架不覆盖 —— 那是各店当天的经营决策。 */
export function syncBrandMenu(
  fromShop: number, toShops: number[],
): Promise<MenuSyncResult> {
  return request('POST', '/brands/me/menu-sync',
    { from_shop: fromShop, to_shops: toShops })
}

export interface BrandMemberRow {
  id: number
  user_id: number
  role: string
  name: string
  phone: string
  shop_ids: number[]
  created_at: string
}

export function brandMembers(): Promise<BrandMemberRow[]> {
  return request('GET', '/brands/me/members')
}

export function addBrandMember(phone: string, shopIds: number[]): Promise<unknown> {
  return request('POST', '/brands/me/members', { phone, shop_ids: shopIds })
}

export function removeBrandMember(id: number): Promise<unknown> {
  return request('DELETE', `/brands/me/members/${id}`)
}
