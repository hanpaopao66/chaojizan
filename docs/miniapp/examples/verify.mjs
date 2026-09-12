// 超级赞小程序 initData v2 验签(Node.js 18+,只用内置 crypto,不装任何包)。
//   verifyHash —— 持有 AppSecret 的后端用它;
//   verifySignature —— 不想碰密钥,用平台公钥。
// 这份代码被 scripts/check_sdk_docs.mjs 拿测试向量跑过,和文档里的一字不差。
import { createHmac, createPublicKey, timingSafeEqual, verify } from 'node:crypto'

const MAX_AGE = 600 // 秒:超过 10 分钟的包一律拒绝

function fields(initData) {
  const params = new URLSearchParams(initData)
  const out = {}
  for (const [k, v] of params) {
    if (k in out) throw new Error('字段重复')
    out[k] = v
  }
  return out
}

function checkString(f) {
  return Object.keys(f).filter((k) => k !== 'hash' && k !== 'signature').sort()
    .map((k) => `${k}=${f[k]}`).join('\n')
}

function fresh(f, appId, now) {
  if (f.app_id !== appId) return false
  const age = (now ?? Date.now() / 1000) - Number(f.auth_date || 0)
  return age >= 0 && age <= MAX_AGE
}

export function verifyHash(initData, appId, appSecret, now) {
  try {
    const f = fields(initData)
    const secretKey = createHmac('sha256', 'SuperZWebAppData').update(appSecret).digest()
    const want = createHmac('sha256', secretKey).update(checkString(f)).digest()
    const given = Buffer.from(f.hash || '', 'hex')
    return given.length === want.length && timingSafeEqual(want, given) && fresh(f, appId, now)
  } catch {
    return false
  }
}

export function verifySignature(initData, appId, publicKeyB64url, now) {
  try {
    const f = fields(initData)
    // Ed25519 公钥的 SPKI DER 前缀是固定的 12 个字节
    const der = Buffer.concat([Buffer.from('302a300506032b6570032100', 'hex'), Buffer.from(publicKeyB64url, 'base64url')])
    const key = createPublicKey({ key: der, format: 'der', type: 'spki' })
    const message = Buffer.from(`${f.app_id}:SuperZWebAppData\n${checkString(f)}`)
    return verify(null, message, key, Buffer.from(f.signature || '', 'base64url')) && fresh(f, appId, now)
  } catch {
    return false
  }
}
