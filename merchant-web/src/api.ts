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
