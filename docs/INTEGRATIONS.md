# 外部服务联调清单(微信支付 / 极光推送 / 腾讯云短信)

三个服务的代码已全部就位,**没有 Key 时自动降级**,拿到 Key 后填 `server/.env` 即可逐个点亮:

| 服务 | 未配置时的行为 | 配置后 |
|---|---|---|
| 微信支付 | `/pay/wechat` 返回 503,客户端自动走模拟支付 | 真实收款 |
| 极光推送 | 静默跳过,WebSocket 前台通道照常 | 退后台也能收到新单/状态通知 |
| 腾讯云短信 | 验证码随接口返回并自动填入(开发模式) | 真实短信 |

## 1. 微信支付(依赖:公司营业执照 → 微信支付商户号)

**你要准备的**:
1. ~~微信开放平台注册 App,拿 `AppID`~~ **已办**(2026-07,已填 .env)
2. ~~微信支付商户平台开户,拿 `商户号(mchid)`~~ **已办**(2026-07,号码在 server/.env)
3. ~~商户平台 → API 安全:设置 `APIv3 密钥`、证书序列号~~ **已办**(已填 .env);
   **仍缺**:证书工具产出的 `apiclient_key.pem`,放 `server/certs/`(目录已 gitignore)
   后把 `WXPAY_PRIVATE_KEY_PATH=certs/apiclient_key.pem` 填上——这是最后一块
4. ~~HTTPS 域名~~ **已备**:回调地址 `https://chaojizan.cc/payments/wechat/notify`(已填 .env)
5. 商户平台 → 产品中心 → **APP 支付** 申请开通;AppID 与 MCHID 需在商户平台完成**绑定**
6. 验签模式:本商户号**已实测确认是「微信支付公钥」模式**(2026-07-28,
   `GET /v3/certificates` 返回 `RESOURCE_NOT_EXISTS`,无平台证书可用)。
   公钥 ID 取自响应头 `Wechatpay-Serial`;`pub_key.pem` 与 `apiclient_key.pem`
   都已就位(`server/certs/`,gitignore + rsync 排除,手动上传部署机,见 deploy/README)

**2026-07-28 实测进度**:密钥链路已通(签名被微信接受、公钥验签通过,
`query` 探测返回预期的 `ORDER_NOT_EXIST`)。**唯一卡点**:统一下单返回
`403 NO_AUTH 商户号该产品权限未开通` —— 去商户平台 → 产品中心 **开通 APP 支付**
(顺带确认 AppID 与 MCHID 已绑定)。开通后无需改代码。

**密钥不放本地 dev**:`server/.env` 里整段注释掉,本地保持模拟支付。
开发机启用真实商户参数会让 e2e 的退款/分账用例直打微信生产 API(实测触发过
7 次真实退款请求),且回调地址是 chaojizan.cc,本地也验不了闭环。

> 老商户号(有平台证书)把 `WXPAY_PUBLIC_KEY_*` 两项留空即可,
> SDK 会自动下载平台证书并缓存到 `certs/platform`。

**上线前必做**:生产 `.env.prod` 设 `MOCK_PAY_ENABLED=false`。
`/orders/{no}/pay/mock` 是开发期的模拟支付口子(任何用户能把自己订单标成已付),
真实收款上线后不关等于白送订单。本地与 e2e 保持默认 true。

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
