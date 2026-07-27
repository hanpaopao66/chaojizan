/**
 * 薄 API 客户端:fetch + token 注入 + 401 跳登录 + 中文错误透传。
 * 后端与商家 App 同一套接口,这里不做代码生成,按用到的接口手写类型。
 */

const TOKEN_KEY = 'superz_merchant_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
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
  const resp = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
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
}

export function myShop(): Promise<Merchant> {
  return request('GET', '/merchants/me')
}

export function updateShop(fields: Record<string, unknown>): Promise<Merchant> {
  return request('PATCH', '/merchants/me', fields)
}

/** WebSocket 地址(同源;dev 走 vite ws 代理) */
export function merchantWsUrl(merchantId: number): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/merchants/${merchantId}?token=${getToken()}`
}

// ---------- 图片上传 ----------

export async function uploadImage(file: File): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  const token = getToken()
  const resp = await fetch('/upload', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })
  if (!resp.ok) {
    let detail = `上传失败(${resp.status})`
    try {
      const data = await resp.json()
      if (typeof data.detail === 'string') detail = data.detail
    } catch { /* ignore */ }
    throw new ApiError(resp.status, detail)
  }
  return ((await resp.json()) as { url: string }).url
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

export function myFoodOrders(): Promise<FoodOrder[]> {
  return request('GET', '/orders')
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
  stock: number
  daily_stock: number | null
  sold_out_today: boolean
  is_on_sale: boolean
  is_alcohol: boolean
  image_url: string
  options: DishOptionGroup[]
  monthly_sales: number
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
