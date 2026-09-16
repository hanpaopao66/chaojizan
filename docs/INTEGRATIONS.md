# 外部服务联调清单(微信支付 / 推送 / 腾讯云短信)

三个服务的代码已全部就位,**没有 Key 时自动降级**,拿到 Key 后填 `server/.env` 即可逐个点亮:

| 服务 | 未配置时的行为 | 配置后 |
|---|---|---|
| 微信支付 | `/pay/wechat` 返回 503,客户端自动走模拟支付 | 真实收款 |
| 推送(苹果 APNs 自建) | 静默跳过,WebSocket 前台通道照常 | 退后台、锁屏也能收到 |
| 推送(国内安卓厂商通道) | **还没接**:push_logs 里写明,不假装成功 | 下一批 |
| 腾讯云短信 | 验证码随接口返回并自动填入(开发模式) | 真实短信 |

## 1. 微信支付

> ⚠️ **2026-08-09 更新:服务商资质已下来,下面「直连商户」那套记录作废一半。**
>
> 拿到服务商资质意味着**钱的流向整个换了**,不是"接个 SDK":
>
> - 直连:货款进平台商户号 → 平台人工打款给商家。这在监管口径上是**二清**
>   (平台归集用户资金再向下游结算,需要支付业务许可证)。
> - 服务商:官方文档写明「微信支付 → 子商户结算账户,**服务商账户不直接收款**」。
>   钱直接进商家账户,平台的 5% 通过**分账**拿。
>
> 这正是路线图里那句「货款直达商家不经平台沉淀」——它不是优化,是把一个真实的
> 法律风险拆掉。
>
> **动代码之前必须先问微信一个问题:我们是「普通服务商」还是「电商平台服务商」?**
> 普通服务商进件走 `/v3/applyment4sub/`,而官方在这个接口上明确写着
> 「银行、支付机构、**电商平台**不可用」;电商平台要走[平台收付通](https://pay.weixin.qq.com/doc/v3/partner/4012086891),
> 进件 `/v3/ecommerce/applyments/`、分账 `/v3/ecommerce/profitsharing/orders`。
> **两套 API 完全不通用。** 外卖平台大概率算电商平台,但这个不能猜——选错整套代码作废。
>
> 服务商模式下改动清单与已完成的部分,见 `docs/DEV-PROMPTS-24.md`。
>
> **三个不可逆的点,现在就记住:**
> 1. 下单必须带 `settle_info.profit_sharing=true`。漏了这个标记,资金直接结算给商家,
>    **那一单的佣金永远拿不回来**;
> 2. 分账有 **30 天窗口**,过期不能分;
> 3. 分账要传 `transaction_id`,而外卖订单此前根本没存这个字段。**已加(迁移 0102),
>    但存量已支付订单补不回来** —— 加字段之前的订单永远分不了账。

### 服务商模式实操顺序

代码之外的部分(在商户平台点开通、以及要商家配合的),按这个顺序走:

1. **确认服务商类目** —— 普通服务商还是电商平台。这一步不做完,进件和分账两大块都不能写;
2. **商户平台开通**:APP 支付产品、特约商户进件权限、服务商分账产品
   (分账还要**向特约商户发邀请**,平台单方面开通不够);
3. **配置密钥**:APIv3 密钥、商户证书、微信支付公钥。密钥只放部署机,
   `deploy/.env.prod` + `deploy/wxpay-certs/`(rsync 已排除,见 `deploy/README.md`);
4. **收商家资料** —— 营业执照照片、法人身份证、结算银行账户、超管联系人、经营场景照。
   ⚠️ **这是最耗时的一环,而且它不依赖类目答案,所以先做**(#203–#206 已完成);
5. **商家配合**:扫码确认联系信息 → 签约 → 验证结算账户打款金额 →
   在他自己的微信后台**授权分账并设置最大比例**。没有这一步,分账必报 `NO_AUTH`;
6. 写进件 API → 下单改服务商参数(带分账标记)→ 分账/查询/解冻 → 退款前先回退分账 → 对账。

**已知会踩的坑:**

- `NO_AUTH`:特约商户未授权分账,或服务商未开通分账产品。**两边都要查**;
- `APPID_MCHID_NOT_MATCH`:`sp_appid` 没绑到 `sp_mchid`;
- 跨主体绑定**不支持移动应用类型 AppID** —— 平台自有 App 不能当某个商家的 `sub_appid`,
  只能走 `sp_appid`/`sp_mchid`。因此 APP 拉起支付的 `partnerid` 填**服务商商户号**
  (官方:appId 与 partnerId 必须成对,不能交叉);
- 分账后不解冻(或不传 `unfreeze_unsplit`)→ 商家剩余资金长期冻结,会被投诉;
- 已分账订单退款要**先发起分账回退**,否则商家账上余额不足直接失败。
  而我们的退款调用点有 15 处,顺序约束现在一处都没有。
- **住宿「到店无房」的商家违约金还没有通道。** 那笔赔付要付给用户的钱
  等于「房费 + 首晚 30%」,**超过了他的实付额**,退款 API 按
  「退款额 ≤ 原支付额」直接拒。房费那一半照常走退款(`refunds` 里有流水),
  违约金那一半只能走**商家转账到零钱**(`/v3/transfer/batches`,
  需单独申请产品权限 + 用户确认收款)。在它接入之前,这笔钱是挂着的负债:
  商家余额已经扣了(`stay_orders.net_cents = -违约金`),用户没拿到。
  每日自检的 `stay_penalty_unpaid` 会把笔数和总额报出来(services/audit 规则 15),
  别把它当成账目错误去"修平"。

**下面是直连商户时期的记录,保留备查(收款链路的密钥配置部分仍然适用):**

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
- 分账(平台自动扣佣金)需要**服务商资质** —— **2026-08 资质已到位**,
  但接口形状取决于服务商类目(见本节开头的警告)。`profit_sharing.py` 维护本地台账,
  渠道调用未实现时记录停在 `pending` 并告警(#200 之前它是"假成功",
  已配置就把台账置 success 而一分钱没动 —— 那个坑已经填了)。
  过渡期仍是普通商户收款 + 线下结算给商家,而这正是要尽快离开的状态

**联调步骤**:填 `.env` → 重启 → 用户端下单会拿到真实 prepay 参数 → 接 fluwx 拉起支付 →
微信回调 `/payments/wechat/notify` → 订单自动变已支付(商家听单照常触发)

## 2. 推送

2026-09-16 起**自己接**,不再依赖聚合商。顺序:苹果 → 国内安卓厂商通道 → 其余靠长连接。

理由很简单:苹果和各家安卓厂商的推送**本身都是免费的**,聚合商卖的是"把六家包成一个接口"
这件事。代价是按量付费,以及一个第三方拿到「谁在什么时候收到了什么标题」。
Telegram 也不用聚合商(它走 Google 的 FCM 和苹果的 APNs)。

### 2.1 苹果(APNs)—— 已接好

**你要准备的**:苹果开发者后台 → Keys → 新建一个 **APNs Auth Key**,下载 `.p8`
(**只能下载一次**,丢了只能作废重建)。记下 Key ID(10 位)和 Team ID(10 位)。
一个 key 管你名下所有 App,三个端共用。

`.env.prod` 填五项(+ 三个 bundle id):

```
APNS_KEY_P8=-----BEGIN PRIVATE KEY-----\nMIGT...\n-----END PRIVATE KEY-----
APNS_KEY_ID=ABCDE12345
APNS_TEAM_ID=TEAM123456
APNS_TOPIC_USER=你的用户端 bundle id
APNS_TOPIC_MERCHANT=商家端 bundle id
APNS_TOPIC_RIDER=骑手端 bundle id
```

`.p8` 正文里的换行写成 `\n`(一行一个值的格式塞不下真换行,代码里会还原)。
**apns-topic 必须是 bundle id**,填错是静默收不到,没有任何报错。

**代码侧已就位**:
- 服务端 `app/services/push_channels/apns.py` 直连 APNs(HTTP/2 + ES256 的 JWT,
  令牌缓存 50 分钟 —— 换太勤苹果回 429,换太晚 403);
- 设备地址在 `push_devices` 表(`app/services/push_devices.py`),
  客户端 `POST /push/v1/devices` 登记、`/devices/remove` 下线;
- 选路在 `app/services/push.py`:**名下有自建设备就走自建,一台都没有才退回极光那条老路** ——
  可以一个端一个端地切,不用等三端都接完;
- 苹果回 410 Unregistered / 400 BadDeviceToken 时那台设备自动下线;其余失败连续 5 次才下线
  (一次机房抖动不该把全站设备下线一遍);
- 客户端 `ios/Runner/AppDelegate.swift` + `shared/apns_service.dart`:
  **不接任何 SDK**,token 由系统交给 App。

**沙箱和生产是两台服务器**:Xcode / TestFlight 装的包拿到的是沙箱 token,发到生产会回
`BadDeviceToken`。客户端按打包时嵌的 `aps-environment` 如实上报(不看 `#if DEBUG` ——
TestFlight 是 release 编的但用沙箱),服务端按设备选地址。这是"开发机怎么收不到推送"的头号原因。

**Xcode 里还要开一次**:Runner target → Signing & Capabilities → + Capability →
Push Notifications;后台送达要再加 Background Modes → Remote notifications。

### 2.2 国内安卓厂商通道(华为 / 小米 / OPPO / vivo)—— 服务端已接好

国内安卓上 App 被杀掉之后,**只有手机厂商自己的通道叫得醒它**。各家免费,
但要各自注册、各自过审、各自的载荷格式。服务端四家都实现了
(`app/services/push_channels/{hms,xiaomi,oppo,vivo}.py`),`.env.prod` 填上就生效:

```
# 华为(AppGallery Connect → 项目设置)
HMS_APP_ID=…
HMS_APP_SECRET=…
HMS_PACKAGE_USER=…            # 三个端各自的安卓包名
HMS_PACKAGE_MERCHANT=…
HMS_PACKAGE_RIDER=…

# 小米(开放平台 → 应用 → AppSecret)。不用换令牌,请求头直接带它
XIAOMI_APP_SECRET=…
XIAOMI_PACKAGE_USER=…
XIAOMI_PACKAGE_MERCHANT=…
XIAOMI_PACKAGE_RIDER=…

# OPPO(签名 SHA256,时间戳毫秒)
OPPO_APP_KEY=…
OPPO_MASTER_SECRET=…

# vivo(签名 MD5 —— 和 OPPO 不一样,最容易抄串)
VIVO_APP_ID=…
VIVO_APP_KEY=…
VIVO_APP_SECRET=…
VIVO_CLASSIFICATION=1          # 0 运营消息 / 1 系统消息,以你在后台申请到的为准
```

**每配好一家都要实发一条验一次**:

```bash
docker exec superz-api python -m scripts.push_probe --user 42 --list      # 看这个人有哪些设备
docker exec superz-api python -m scripts.push_probe --user 42 --channel hms
```

为什么非要实发:这几家的接口**只回一句笼统的错误**。签名算错、时间戳单位用了秒、
消息类别标错、包名填错,回来的都是「鉴权失败」「参数错误」。不实发一条到自己手机上,
根本看不出配没配对 —— 而"推送没到"这件事用户不会来报 bug,等发现时已经过去几周。

**还差客户端那一半**:拿 regid 要装各家的 SDK(闭源,要进隐私政策的 SDK 清单),
这一步还没做,见下面 2.4。在那之前安卓靠已有的 WebSocket 长连接:
App 活着就收得到,被杀掉才收不到。

荣耀(honor)还没接:通道名在 `push_devices.CHANNELS` 里占着位,
这类设备登记进来发不出去,push_logs 里写明「这条通道还没接」,不假装成功。

### 2.4 安卓客户端拿 token —— 还没做

厂商通道的 token 只能由各家自己的 SDK 提供,没有别的路。要做的:

1. 三个 App 的 `android/build.gradle.kts` 加各家的 Maven 源和依赖;
2. 各家的应用配置文件(华为要 `agconnect-services.json`);
3. 原生侧拿到 regid 之后走**已经铺好的那条通道**(`superz/push`,和 iOS 同一条),
   Dart 侧 `POST /push/v1/devices` 登记 —— 这一半已经写好了,不用改;
4. **合规**:这几个 SDK 是闭源的,按 COMPLIANCE-40 第 15 条要逐一列进隐私政策的
   SDK 清单(名称、目的、收集的信息),并且按第 14 条改版本号让老用户重新同意。

第 4 条是硬的:SDK 进了包就要公示,不能先上再补。

### 2.3 极光(过渡期保留)

#### 极光的老配置(依赖:极光开发者账号,免费版即可起步)

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
