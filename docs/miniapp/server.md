# 服务端:验签与会话

页面把 `SuperZ.WebApp.initData`(原串)发给你的后端,后端验签通过才算「这是超级赞里的这个 open_id」。

**不要信任页面里的任何身份信息** —— `initDataUnsafe`、页面自己报的昵称,用户都能改。只信验签过的 initData。

## 两种验法,任选其一

| 方法 | 用什么 | 适合 |
|---|---|---|
| 验 `hash` | 你的 AppSecret | 你的后端本来就保管密钥 |
| 验 `signature` | 平台公钥 `GET /.well-known/superz-webapp-keys.json` | 不想碰任何密钥;一次拉公钥缓存起来 |

算法和 Telegram 同构,不同在三处:常量换成 `SuperZWebAppData`(故意和 Telegram 的 `WebAppData` 分开,签名串不能互相冒用)、
密钥是你的 AppSecret、hash 的 data_check_string 也不含 `signature`(Telegram 的 hash 只去掉 `hash` 本身)。
从 Telegram 搬过来的后端改的就是这一处,见[从 Telegram 迁移](telegram.md#最小例子):

```text
data_check_string = 除 hash、signature 外的全部字段,按键名字典序排序,
                    每个写成 key=value(value 是 URL 解码后的原文),用 \n 连接
secret_key = HMAC_SHA256(key = "SuperZWebAppData", msg = AppSecret)
hash       = hex(HMAC_SHA256(key = secret_key, msg = data_check_string))
signature  = base64url(Ed25519_sign(平台私钥[sig_kid], "<app_id>:SuperZWebAppData\n" + data_check_string))   # 无填充
```

验签时必须同时检查:

1. `app_id` 等于你自己的 AppID —— 别的应用的包拿过来,签名是真的,但不是给你的;
2. `auth_date` 不超过 **600 秒**;
3. 比较用常量时间比较;字段缺失、重复、被改、过期、`app_id` 不符,一律当同一种失败,不要区分原因返回给前端;
4. (建议)`launch_id` 做一次性校验(存 10 分钟),挡住重放;
5. `env=sim` 的包来自开发者后台的模拟器,**区分对待测试流量**。

平台公钥:

```json
{"keys": [{"kid": "56475aa7", "alg": "Ed25519", "public_key": "<base64url 的 32 字节>", "not_before": null, "not_after": null}]}
```

按包里的 `sig_kid` 挑公钥。平台轮换签名钥时新旧 kid 会并存一段时间(至少覆盖一个 600 秒的有效期)。

## Python(已用测试向量验证)

```python
# 超级赞小程序 initData v2 验签(Python 3.10+)。两种验法任选其一:
#   verify_hash —— 持有 AppSecret 的后端用它;
#   verify_signature —— 不想碰密钥,用平台公钥(需要 pip install cryptography)。
# 这份代码被 server/tests/unit/test_miniapp_docs_examples.py 拿测试向量跑过,和文档里的一字不差。
import base64
import hashlib
import hmac
import time
from urllib.parse import parse_qsl

MAX_AGE = 600  # 秒:超过 10 分钟的包一律拒绝


def _fields(init_data: str) -> dict:
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("字段重复")
    return fields


def _check_string(fields: dict) -> str:
    return "\n".join(f"{k}={fields[k]}" for k in sorted(fields) if k not in ("hash", "signature"))


def _fresh(fields: dict, app_id: str, now: float | None) -> bool:
    if fields.get("app_id") != app_id:
        return False
    age = (time.time() if now is None else now) - int(fields.get("auth_date", "0"))
    return 0 <= age <= MAX_AGE


def verify_hash(init_data: str, app_id: str, app_secret: str, now: float | None = None) -> bool:
    try:
        fields = _fields(init_data)
        given = fields["hash"]
    except (ValueError, KeyError):
        return False
    secret_key = hmac.new(b"SuperZWebAppData", app_secret.encode(), hashlib.sha256).digest()
    want = hmac.new(secret_key, _check_string(fields).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, given) and _fresh(fields, app_id, now)


def verify_signature(init_data: str, app_id: str, public_key_b64url: str, now: float | None = None) -> bool:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    def b64d(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    try:
        fields = _fields(init_data)
        message = f"{fields['app_id']}:SuperZWebAppData\n{_check_string(fields)}".encode()
        Ed25519PublicKey.from_public_bytes(b64d(public_key_b64url)).verify(b64d(fields["signature"]), message)
    except Exception:
        return False
    return _fresh(fields, app_id, now)
```

## Node.js(已用测试向量验证)

```js
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
```

## Go(未验证)

> 这段代码**没有**进 CI 跑测试向量,用之前请先拿下面的向量自测。

```go
package superz

import (
	"crypto/ed25519"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"
)

func checkString(v url.Values) string {
	keys := make([]string, 0, len(v))
	for k := range v {
		if k != "hash" && k != "signature" {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	lines := make([]string, len(keys))
	for i, k := range keys {
		lines[i] = k + "=" + v.Get(k)
	}
	return strings.Join(lines, "\n")
}

func fresh(v url.Values, appID string) bool {
	ts, err := strconv.ParseInt(v.Get("auth_date"), 10, 64)
	age := time.Now().Unix() - ts
	return err == nil && v.Get("app_id") == appID && age >= 0 && age <= 600
}

func VerifyHash(initData, appID, appSecret string) bool {
	v, err := url.ParseQuery(initData)
	if err != nil {
		return false
	}
	m := hmac.New(sha256.New, []byte("SuperZWebAppData"))
	m.Write([]byte(appSecret))
	h := hmac.New(sha256.New, m.Sum(nil))
	h.Write([]byte(checkString(v)))
	want := hex.EncodeToString(h.Sum(nil))
	return hmac.Equal([]byte(want), []byte(v.Get("hash"))) && fresh(v, appID)
}

func VerifySignature(initData, appID, publicKeyB64url string) bool {
	v, err := url.ParseQuery(initData)
	if err != nil {
		return false
	}
	pub, err1 := base64.RawURLEncoding.DecodeString(publicKeyB64url)
	sig, err2 := base64.RawURLEncoding.DecodeString(v.Get("signature"))
	if err1 != nil || err2 != nil || len(pub) != ed25519.PublicKeySize {
		return false
	}
	msg := v.Get("app_id") + ":SuperZWebAppData\n" + checkString(v)
	return ed25519.Verify(ed25519.PublicKey(pub), []byte(msg), sig) && fresh(v, appID)
}
```

## Java(未验证)

> 同上,**未进 CI**。Java 15+ 自带 Ed25519。

```java
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.spec.X509EncodedKeySpec;
import java.util.*;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

public final class SuperZInitData {
  static Map<String, String> fields(String initData) {
    Map<String, String> out = new TreeMap<>();
    for (String pair : initData.split("&")) {
      int i = pair.indexOf('=');
      String k = URLDecoder.decode(pair.substring(0, i), StandardCharsets.UTF_8);
      String v = URLDecoder.decode(pair.substring(i + 1), StandardCharsets.UTF_8);
      if (out.put(k, v) != null) throw new IllegalArgumentException("字段重复");
    }
    return out;
  }

  static String checkString(Map<String, String> f) {
    StringJoiner j = new StringJoiner("\n");
    f.forEach((k, v) -> { if (!k.equals("hash") && !k.equals("signature")) j.add(k + "=" + v); });
    return j.toString();
  }

  static boolean fresh(Map<String, String> f, String appId) {
    long age = System.currentTimeMillis() / 1000 - Long.parseLong(f.getOrDefault("auth_date", "0"));
    return appId.equals(f.get("app_id")) && age >= 0 && age <= 600;
  }

  static byte[] hmac(byte[] key, String msg) throws Exception {
    Mac m = Mac.getInstance("HmacSHA256");
    m.init(new SecretKeySpec(key, "HmacSHA256"));
    return m.doFinal(msg.getBytes(StandardCharsets.UTF_8));
  }

  public static boolean verifyHash(String initData, String appId, String appSecret) {
    try {
      Map<String, String> f = fields(initData);
      byte[] secretKey = hmac("SuperZWebAppData".getBytes(StandardCharsets.UTF_8), appSecret);
      String want = HexFormat.of().formatHex(hmac(secretKey, checkString(f)));
      return MessageDigest.isEqual(want.getBytes(), f.getOrDefault("hash", "").getBytes()) && fresh(f, appId);
    } catch (Exception e) {
      return false;
    }
  }

  public static boolean verifySignature(String initData, String appId, String publicKeyB64url) {
    try {
      Map<String, String> f = fields(initData);
      byte[] raw = Base64.getUrlDecoder().decode(publicKeyB64url);
      byte[] der = new byte[12 + raw.length];
      System.arraycopy(HexFormat.of().parseHex("302a300506032b6570032100"), 0, der, 0, 12);
      System.arraycopy(raw, 0, der, 12, raw.length);
      PublicKey key = KeyFactory.getInstance("Ed25519").generatePublic(new X509EncodedKeySpec(der));
      Signature s = Signature.getInstance("Ed25519");
      s.initVerify(key);
      s.update((f.get("app_id") + ":SuperZWebAppData\n" + checkString(f)).getBytes(StandardCharsets.UTF_8));
      return s.verify(Base64.getUrlDecoder().decode(f.get("signature"))) && fresh(f, appId);
    } catch (Exception e) {
      return false;
    }
  }
}
```

## PHP(未验证)

> 同上,**未进 CI**。需要 PHP 7.2+ 自带的 sodium 扩展。

```php
<?php
function sz_fields(string $initData): array {
    $out = [];
    foreach (explode('&', $initData) as $pair) {
        [$k, $v] = array_map('rawurldecode', explode('=', $pair, 2));
        if (array_key_exists($k, $out)) throw new InvalidArgumentException('字段重复');
        $out[$k] = $v;
    }
    return $out;
}

function sz_check_string(array $f): string {
    unset($f['hash'], $f['signature']);
    ksort($f, SORT_STRING);
    $lines = [];
    foreach ($f as $k => $v) $lines[] = "$k=$v";
    return implode("\n", $lines);
}

function sz_fresh(array $f, string $appId): bool {
    $age = time() - (int)($f['auth_date'] ?? 0);
    return ($f['app_id'] ?? '') === $appId && $age >= 0 && $age <= 600;
}

function sz_verify_hash(string $initData, string $appId, string $appSecret): bool {
    try { $f = sz_fields($initData); } catch (Exception $e) { return false; }
    $secretKey = hash_hmac('sha256', $appSecret, 'SuperZWebAppData', true);
    $want = hash_hmac('sha256', sz_check_string($f), $secretKey);
    return hash_equals($want, $f['hash'] ?? '') && sz_fresh($f, $appId);
}

function sz_verify_signature(string $initData, string $appId, string $publicKeyB64url): bool {
    try { $f = sz_fields($initData); } catch (Exception $e) { return false; }
    $b64 = fn($s) => base64_decode(strtr($s, '-_', '+/') . str_repeat('=', (4 - strlen($s) % 4) % 4));
    $msg = ($f['app_id'] ?? '') . ":SuperZWebAppData\n" . sz_check_string($f);
    return sodium_crypto_sign_verify_detached($b64($f['signature'] ?? ''), $msg, $b64($publicKeyB64url))
        && sz_fresh($f, $appId);
}
```

## 测试向量

用这组固定的数自测你的实现(`now` 取 `1790000005`,即签发后 5 秒):

| 项 | 值 |
|---|---|
| AppID | `sz0123456789abcdef` |
| AppSecret | `SuperZTestVectorAppSecret0123456789abcdefgh` |
| 平台私钥 | Ed25519 种子 = 字节 `00 01 02 … 1f`(32 字节递增) |
| 平台公钥 | `A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg`(kid `56475aa7`) |
| auth_date | `1790000000` |

initData 原串:

```text
app_id=sz0123456789abcdef&auth_date=1790000000&launch_id=AAAAAAAAAAAAAAAAAAAAAA&sig_kid=56475aa7&start_param=note42&user=%7B%22language_code%22%3A%22zh-CN%22%2C%22open_id%22%3A%22o_testvectoropenid000000000%22%7D&hash=797f9baf84dafc57c34179e83285670329947fc09314d2093bec14d1a975515a&signature=Yd_TNpAvseblIJL5TPzdFhcduSLDXZJnqYovzx8nFNNH3UGqHp-sxmmJRiK6wvdS57vdAo7hEdGmzE621rQICQ
```

data_check_string:

```text
app_id=sz0123456789abcdef
auth_date=1790000000
launch_id=AAAAAAAAAAAAAAAAAAAAAA
sig_kid=56475aa7
start_param=note42
user={"language_code":"zh-CN","open_id":"o_testvectoropenid000000000"}
```

期望:两种验法都通过;把 `note42` 改成 `note43`、把 AppID 换成别的、`now` 取 `1790000601`,都失败。
平台自己的测试(`server/tests/unit/test_mini_app_v2.py`)锁的是同一组数 —— 协议一旦有第三方接入就不再改。

## 会话建议

验签通过后,用 `open_id` 在你的系统里建或找用户,**发你自己的会话**(cookie 或 token),之后的请求走你自己的会话;
不要每个请求都带 initData —— 它 10 分钟就过期,本来就不是给长会话用的。页面重新打开会拿到新的 initData,再换一次即可。

## 密钥轮换

AppSecret 泄露或定期更换,在后台「开发设置」两步走:

1. **生成新密钥**:只显示这一次。此时平台**照旧用旧密钥签发**;
2. 把新密钥部署到你的服务端 —— 过渡期间新旧两把都能验;
3. 点**切换到新密钥**:之后平台只用新密钥签发,旧密钥签的包再也验不过。

不想管这件事的话,只验 `signature`(平台公钥),AppSecret 轮换对你没有任何影响。

## 服务器域名

页面只能连后台声明过的服务器(托管页 CSP 的 `connect-src`、`img-src`、`media-src`)。只收 https 的 origin
(`https://api.example.com`,不带路径),不收 IP 和 localhost;每月最多改 50 次,改完只对新启动生效。
没声明就发请求,浏览器会拦下来,并上报到平台(模拟器的日志里看得到)。
