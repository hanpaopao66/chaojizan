# 外部服务联调清单(微信支付 / 极光推送 / 腾讯云短信)

三个服务的代码已全部就位,**没有 Key 时自动降级**,拿到 Key 后填 `server/.env` 即可逐个点亮:

| 服务 | 未配置时的行为 | 配置后 |
|---|---|---|
| 微信支付 | `/pay/wechat` 返回 503,客户端自动走模拟支付 | 真实收款 |
| 极光推送 | 静默跳过,WebSocket 前台通道照常 | 退后台也能收到新单/状态通知 |
| 腾讯云短信 | 验证码随接口返回并自动填入(开发模式) | 真实短信 |

## 1. 微信支付(依赖:公司营业执照 → 微信支付商户号)

**你要准备的**:
1. 微信开放平台注册 App,拿 `AppID`(注意是开放平台,不是公众平台)
2. ~~微信支付商户平台开户,拿 `商户号(mchid)`~~ **已办**(2026-07,号码在 server/.env)
3. 商户平台 → API 安全:设置 `APIv3 密钥`、下载商户证书(得到 `apiclient_key.pem` 和证书序列号)
4. ~~HTTPS 域名~~ **已备**:回调地址 `https://chaojizan.cc/payments/wechat/notify`(已填 .env)

**代码侧已就位**:
- 服务端:`app/services/wechat_pay.py`(统一下单/验签解密/分账占位)、
  `POST /orders/{no}/pay/wechat`、`POST /payments/wechat/notify`(幂等入账,和模拟支付同一入口)
- 客户端:`user_app/lib/payment_service.dart`,联调时:
  1. `pubspec.yaml` 加 `fluwx` 依赖
  2. `main()` 里 `registerWxApi(appId: 'wxXXXX', universalLink: ...)`
  3. 把 `payment_service.dart` 里的 TODO 换成 `payWithWeChat(...)`(参数字段已对好)
- 分账(平台自动扣佣金)需要**服务商资质**,`request_profit_sharing` 已留位;
  没有服务商资质前,可先用普通商户收款 + 线下结算给商家过渡

**联调步骤**:填 `.env` → 重启 → 用户端下单会拿到真实 prepay 参数 → 接 fluwx 拉起支付 →
微信回调 `/payments/wechat/notify` → 订单自动变已支付(商家听单照常触发)

## 2. 极光推送(依赖:极光开发者账号,免费版即可起步)

**你要准备的**:jiguang.cn 注册 → 创建应用 → 拿 `AppKey` 和 `Master Secret`;
Android 各厂商通道(小米/华为/OPPO...)在极光后台按引导逐个开通(可后补)。

**代码侧已就位**:服务端 `app/services/push.py` 直调 JPush REST API,
推送点已挂好:支付成功→推商家老板;订单状态变更→推用户。别名规则 `u{user_id}`。
每次真实推送尝试记入 `push_logs` 表(排查"没收到提醒"的第一现场)。

**客户端也已就位**(shared 的 `push_service.dart`,登录 setAlias/登出 deleteAlias 已挂):
拿到 AppKey 后两处填 Key 即点亮:
1. 各 App `android/gradle.properties` 加 `JPUSH_APPKEY=你的Key`
2. 构建命令加 `--dart-define=SUPERZ_JPUSH_KEY=你的Key`
任一处没配都整体静默降级,WebSocket/轮询主通道不受影响。

**商家端锁屏听单已不依赖推送**:前台服务保活(常驻通知"正在听单")+
真人语音循环播报(`listen_service.dart`),锁屏/退后台时 WebSocket 和轮询照常跑。
推送配好后是第二重保险(进程被杀也能到达)。

## 3. 腾讯云短信(依赖:已备案域名或小程序/公众号做签名资质)

**你要准备的**:腾讯云开通短信 → 创建签名(需资质,个人可用公众号)→
创建模板(内容形如「您的验证码是{1},5 分钟内有效」)→ 拿五个参数填 `.env`。

**代码侧已就位**:`app/services/sms.py`(TC3-HMAC-SHA256 签名已实现,非 SDK、零额外依赖)、
`POST /auth/sms-code`(60 秒防重发,5 分钟有效)、`POST /auth/sms-login`(新号自动注册为用户)。
客户端 `SmsLoginPage` 已是用户端默认登录页,配好 Key 后开发模式提示自动消失,无需改代码。

## 联调顺序建议

短信(最简单,半天)→ 推送(1 天)→ 微信支付(资质到位后 1-2 天)。
每接通一个,跑一遍 `make test` 确认没破坏现有行为。
