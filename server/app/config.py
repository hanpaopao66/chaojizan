from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://superz:superz@localhost:5432/superz"
    redis_url: str = "redis://localhost:6379/0"

    # ---- 连接池 ----
    # **这两个数字乘上进程数必须小于 PostgreSQL 的 max_connections。**
    # 原先 api 以 --workers 4 起,4 × (10 + 20) = 120 > PG 默认的 100,
    # 高峰期后来的连接直接被库拒掉,表现是随机 500 而不是变慢 ——
    # 最难查的那种故障:日志里每条都不一样,压测又复现不出来。
    # 现在 api 单进程、清扫独立一个进程,30 + 30 = 60,留足给
    # psql/pg_dump/迁移容器。改这里记得同步 deploy 里 PG 的 max_connections
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # 启动时自动跑 alembic upgrade。本地开发/单机保持 True(起服务即最新);
    # 生产由独立的一次性 migrate 容器跑,api 与 sweeper 都关掉 ——
    # 多个进程同时 upgrade 会抢 alembic_version 的锁,轻则等待重则半途报错
    run_migrations_on_startup: bool = True
    jwt_secret: str = "change-me-in-production"
    # 敏感字段(收款账号等)对称加密密钥;不配置时从 jwt_secret 派生。
    # 生产务必单独配置,且一经使用不可更换(见 services/crypto.py)
    crypto_key: str = ""
    # 小程序 initData 签名密钥;不配置时从 jwt_secret 带命名空间派生
    # (见 services/mini_app.py)。有第三方小程序接入后再换要通知所有验签方
    mini_app_secret: str = ""
    # 7 天 + 客户端自动续期(/auth/refresh):商家端长期挂机也不会掉线,
    # 但被泄露的旧 token 一周后自然作废
    jwt_expire_minutes: int = 43200  # 30 天;客户端>1天龄自动续期,活跃用户不掉线

    # 同一出口 IP 每日验证码上限。生产 20 是给"一个网吧/一栋写字楼"留的量,
    # 不要为跑测试调低它。**只在本地/CI 调高** —— 全套 e2e 从同一个
    # 127.0.0.1 发几十条注册短信,撞的是这条,不是产品缺陷。
    sms_daily_ip_limit: int = 20

    # CORS 白名单(#130)。原先是 allow_origins=["*"],注释自己写着"上线前收紧"。
    # 注意:**原生 App 不发 Origin 头,不受 CORS 约束** —— 收紧只影响
    # 官网/管理后台这类浏览器页面,三端 App 不会因此挂掉。
    # 逗号分隔;留空则用下面的默认值
    cors_origins: str = ""

    # ---- 对象存储(#124/#125)----
    # local:落本地磁盘,仅供本地开发。生产一律 minio。
    # 切成 minio 后连不上会让上传**明确失败**,不会静默退回磁盘 ——
    # 一半文件在桶里一半在磁盘上,事后根本对不齐
    storage_backend: str = "local"
    minio_endpoint: str = "minio:9000"       # compose 内网,不经公网
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_secure: bool = False               # 内网 http;对外由 nginx 上 TLS

    # 对外可访问的站点地址:店铺短链、海报二维码、分享文案里用。
    # 默认就是生产域名 —— 海报是印出来贴墙上的,漏配一次就是一批废二维码,
    # 宁可默认指向线上。本地联调想指到自己机器时再在 .env 覆盖
    public_base_url: str = "https://chaojizan.cc"

    # 管理员密码登录开关:生产关闭(ADMIN_PASSWORD_LOGIN=false),
    # 管理员只能手机验证码登录;本地开发与 e2e 保持默认开启
    admin_password_login: bool = True

    # 模拟支付开关:生产必须关闭(MOCK_PAY_ENABLED=false),否则
    # /orders/{no}/pay/mock 能让任何用户白嫖下单;本地开发与 e2e 保持默认开启
    mock_pay_enabled: bool = True

    # 接口限流(Redis 固定窗口,按 分钟 计):防爆破/防刷,不为限制正常用户
    rate_limit_enabled: bool = True
    rate_limit_login_per_minute: int = 30      # 同一手机号密码尝试
    rate_limit_sms_per_minute: int = 5         # 同一手机号请求验证码(另有 60 秒重发限制)
    rate_limit_sms_login_per_minute: int = 10  # 同一手机号验证码登录尝试
    rate_limit_order_per_minute: int = 20      # 同一用户下单
    # 同一串验证码连错几次就作废它。**光限速挡不住爆破**:6 位码 300 秒有效,
    # 按每分钟 10 次算,一个窗口期还能试 50 次,而正常人手滑不会超过两三次。
    # 作废之后要重新发码,而发码那边有 60 秒冷却 + 每日 8 条 + 第 3 条起滑块
    sms_login_max_wrong: int = 5

    # 配送费按距离计价:2km 内 ¥3,每超 1km 加 ¥1(向上取整),距离部分封顶 ¥10。
    # 配送费(含下面的加价)100% 归骑手,平台分文不取 —— 审计恒等式强制校验
    delivery_base_fee_cents: int = 300
    delivery_base_km: float = 2.0
    delivery_per_km_cents: int = 100
    delivery_max_fee_cents: int = 1000
    # 配送半径:超出不接单(商业规则:与其 10 元封顶让远单没人接,不如不做远单)
    delivery_max_km: float = 4.0
    # 夜间加价(21:00–06:00,北京时间):夜里跑腿更辛苦,加价全归骑手
    delivery_night_surcharge_cents: int = 200
    delivery_night_start_hour: int = 21
    delivery_night_end_hour: int = 6
    # 恶劣天气加价:按区县自动判定(services/weather.py),全归骑手。
    # 管理员保留手动**强制开**的能力(自动判定漏了也能救),
    # 但不保留强制关 —— 天气恶劣却关掉加价,没有正当理由
    delivery_weather_surcharge_cents: int = 200

    # 等餐超时补偿(#145):骑手到店后餐没好的那段时间,原先完全没有收入。
    # 平台承担,不转嫁商家或用户 —— 转嫁商家会让商家宁可晚点按「出餐」(数据失真),
    # 转嫁用户则是让用户为商家的慢买单。这属于履约成本,不是营销补贴
    # 上门难度费(顾客付,全额归骑手)。**只对无电梯的高楼层收** ——
    # 等电梯的时间已经在 ETA 里补过,再收钱就是同一件事收两次。
    # 起收楼层取 5:骑手的原话是"爬 1–4 楼勉强能被派费覆盖,
    # 从 5 楼开始就不合理了"
    door_fee_free_floor: int = 4        # 4 楼及以下不收
    door_fee_per_floor_cents: int = 100  # 超出部分每层 ¥1
    door_fee_max_cents: int = 500       # 封顶 ¥5

    delivery_wait_free_minutes: int = 15    # 前 15 分钟不补(正常出餐区间)
    delivery_wait_per_min_cents: int = 30   # 超出部分每分钟 ¥0.3
    delivery_wait_max_cents: int = 600      # 封顶 ¥6

    # 配送费改用骑行路径距离(#145)。**直接改钱,默认关**,
    # 灰度验证(新旧口径在真实订单上对比)后再开
    delivery_use_route_distance: bool = False

    # 平台起送价下限:低于它的购物车不接单(单太小,佣金连支付通道费都覆盖不了)。
    # 商家可以设更高的起送价,但不能低于这个下限
    min_order_floor_cents: int = 1500

    # 订单超时自动流转
    pay_timeout_minutes: int = 15      # 超时未支付 → 自动关单
    accept_timeout_minutes: int = 5    # 商家超时未接单 → 自动取消(全额退款)
    # 无人接单兜底(抢单模式的红线,预约单以预约时间为基准):
    # 提醒线:推送在线骑手催抢单 + 告知商家,每单一次
    # 取消线:全额退款;商家已出餐的,平台按商家应收全额赔付餐损(佣金不收)
    no_rider_alert_minutes: int = 10
    no_rider_cancel_minutes: int = 30
    # 骑手转单:每天免责次数(超出仍可转,只计数供考核参考,不拦截)
    transfer_free_times_per_day: int = 2
    # 上报「到店未出餐」满 N 分钟仍没出餐的,转单不占当日次数(无责转单)
    pickup_wait_free_transfer_minutes: int = 10
    # 转单软约束:同一自然日非免责转单达 N 次,当日暂停抢单(不罚钱不封号,
    # 次日自动恢复;免责转单与事故释放永不计入)
    transfer_daily_suspend_threshold: int = 5

    # 跑腿平台服务费(万分比)。200 = 2%,与团购券同口径。
    #
    # **外卖的配送费一分不抽**(平台收入来自商家佣金),跑腿没有商家,
    # 这 2% 是平台在这条业务上唯一的收入。两个口径同时存在,
    # 界面上必须讲清楚,否则就是"你不是说配送费不抽吗"。
    # 账单上单列一行,不藏在总价里
    errand_service_fee_bps: int = 200

    # 新骑手保护期:实名认证起 N 天内**且**完成单不足 M 单时,
    # 转单的每日暂停阈值多给几次。头几天路不熟、进不去小区、拿错单,
    # 转单会比老手频繁 —— 达阈值就暂停抢单,等于第一周把人劝退。
    # 只放宽这一个软阈值,**不动派单权重**(公平性是公开承诺过的)
    rider_novice_days: int = 7
    rider_novice_orders: int = 20
    rider_novice_extra_transfers: int = 3

    # 防刷单风控:同收货位置 24h 内达到 N 单(且多账号)触发标记
    risk_addr_orders_24h: int = 4
    # 骑手同时在途上限(ACCEPTED/READY/PICKED_UP,追加单随原单不占额度)
    rider_max_active_orders: int = 3
    auto_confirm_hours: int = 24       # 送达后超时未确认 → 自动完成
    sweep_interval_seconds: int = 30   # 清扫任务运行间隔
    auto_flow_enabled: bool = True     # 测试时可关掉后台任务,手动调 sweep_once

    # ---- 运维日志保留期(天)。0 = 不清 ----
    # 只清**纯运维日志**。order_events 一天都不清:
    # 《网络餐饮服务食品安全监督管理办法》要求订单信息(含送餐人员、
    # 送达时间)自交易完成起保存不少于三年,见 docs/DEV-PROMPTS-20.md。
    #
    # push_logs 增长最快(1000 单/天 × 50 骑手 ≈ 5 万行/天),但它同时是
    # **消息中心的数据源**(services/message_center.py 直接翻这张表),
    # 所以保留期就是"用户能往回翻多久的站内消息",180 天不是随手写的。
    push_log_retention_days: int = 180
    # 自建埋点。产品分析窗口最长 30 天(routers/platform.py 是 7 天),
    # 留 180 天足够回看季度趋势;埋点数据留得越久隐私面越大,不宜再长
    app_event_retention_days: int = 180
    # 账务告警 / 风控处置留痕:量极小,清它不为省空间,只为不无限增长。
    # **下限卡在 12 个月以上**:透明中心公示的是最近 12 个月的风控月度聚合
    # (routers/transparency.py),保留期短于它会让已公示的数字凭空变空
    audit_alert_retention_days: int = 730
    risk_action_retention_days: int = 730

    # ---- 推送扇出 ----
    # 一批并发多少个。串行推 500 个骑手 ≈ 500 次串行 HTTPS,
    # JPush 超时(5s)时能堵 2500 秒;并发分批把它压到 batch 数 × 超时
    push_fanout_concurrency: int = 20
    # 单次扇出的人数上限(安全阀,不是业务规则)。在线骑手不该有这么多,
    # 真到了这个量级说明该改推送策略而不是继续无上限循环
    push_fanout_max_targets: int = 2000

    # 公开大屏演示模式:真实数据上叠加确定性模拟增量,响应带 demo=true,
    # 页面明示"演示数据"角标(见 routers/screen.py)。生产保持关闭
    screen_demo: bool = False

    # 工程透明(见 routers/transparency.py):
    # 最近更新流拉的 GitHub 仓库;token 选填(只为提升 API 限额,建议只读权限)
    github_repo: str = "hanpaopao66/chaojizan"
    github_token: str = ""
    # 运行版本号:发版脚本写 server/app_version.txt(git describe),env 可覆盖
    app_version: str = ""

    # 阶梯佣金:按商家「上个自然月完成单量」定档,每月 1 日凌晨自动重算。
    # [起始单量, 费率];任何档不得高于 5% 承诺上限(重算时强制钳制)。
    # 重算取 min(档位费率, 现费率):管理员手工调低的店绝不上调
    commission_tiers: list = [
        [0, "0.050"],      # 0-499 单:5%
        [500, "0.045"],    # 500-999 单:4.5%
        [1000, "0.040"],   # 1000+ 单:4%
    ]

    # 骑手提现
    min_withdrawal_cents: int = 1000  # 最低提现 ¥10

    # 邀请有礼:被邀请人完成首单后双方各得券(分);0=关闭活动。
    # 奖励挂完成单不挂注册(刷号无利可图);邀请人每自然月上限 N 人
    referral_reward_cents: int = 300
    referral_monthly_cap: int = 10

    # 订单超时安抚券(#34,平台承担):没有预算时可关(false=超时只致歉不发券)
    eta_compensation_enabled: bool = True

    # 平台拉新:首单立减(分),0=关闭。成本平台承担,订单上记 subsidy_cents,
    # 审计恒等式和透明账单都能看到这笔钱从平台流向了用户
    first_order_discount_cents: int = 0

    # 团购券核销服务费率(只在核销时收;券未使用平台分文不取)
    voucher_commission_rate: float = 0.02

    # 住宿佣金率(离店才计佣;取消/拒单/noshow 平台分文不取)
    stay_commission_rate: float = 0.05

    # 骑手保障金:每完成一单从平台佣金中计提(分),用于骑手意外险采购和
    # 骑手责任(洒餐/丢餐)的先行赔付 —— 不扣骑手工资的底气。逐日计提额
    # 写进公开账本(rider_fund 字段),社区可验证
    rider_fund_per_order_cents: int = 20

    # 灵活用工平台(骑手劳务代发+完税):拿到服务商后填 .env 启用。
    # 未配置时 T+1 打款照旧人工,骑手端显示个税自行申报提示
    flexwork_app_id: str = ""
    flexwork_secret: str = ""

    # 飞鹅云打印(商家听单小票):在 feieyun.cn 注册开发者号后填 .env 启用。
    # 不配置时云打印接口返回"未启用",商家端仍可用蓝牙小票机直连
    feie_user: str = ""    # 飞鹅后台的 USER(注册邮箱/账号)
    feie_ukey: str = ""    # 飞鹅后台的 UKEY

    # 腾讯地图 Key(#137)。一把 key 同时用于:
    #  - 服务端逆地理解析城市(services/geo_city.py,多城市隔离用);
    #  - 客户端配送地图底图瓦片(打包时 --dart-define=TENCENT_MAP_KEY 注入)。
    # 不配置时 city 留空人工填、地图退化成品牌网格示意,功能都不断。
    #
    # 换掉天地图的原因是坐标口径:腾讯用 GCJ-02,与本系统全局一致,
    # 而天地图是 WGS-84,每贴一次瓦片、每查一次城市都要转一道。
    tencent_map_key: str = ""

    # ===== 以下三组为待联调的外部服务,拿到资质/Key 后填 .env 即可启用 =====

    # 微信支付 V3(服务商模式前先用普通商户直连跑通)
    wxpay_app_id: str = ""            # 开放平台 App 的 AppID
    wxpay_mchid: str = ""             # 商户号
    wxpay_api_v3_key: str = ""        # APIv3 密钥
    wxpay_cert_serial_no: str = ""    # 商户证书序列号
    wxpay_private_key_path: str = ""  # apiclient_key.pem 路径
    wxpay_notify_url: str = ""        # https://你的域名/payments/wechat/notify
    # 2024 下半年后新开的商户号默认「微信支付公钥」验签(不再发平台证书)。
    # 商户平台 API 安全页若显示的是公钥,把 pub_key.pem 放 certs/ 并填公钥 ID;
    # 两项留空 = 老的平台证书模式(SDK 自动下载并缓存到 certs/platform)
    wxpay_public_key_path: str = ""   # 微信支付公钥 pub_key.pem 路径
    wxpay_public_key_id: str = ""     # 公钥 ID,形如 PUB_KEY_ID_0117...

    # 极光推送(JPush REST API,服务端直推)
    jpush_app_key: str = ""
    jpush_master_secret: str = ""

    # 阿里云号码隐私保护(AXB 中间号)。未配置时降级:
    # 商家/骑手侧界面与小票只显示打码号(138****0001),拨打走 privacy_phone 字段
    # (过渡期给真号,strict 模式不给);配置后绑定 AXB,看到与拨打的都是 X 号
    ali_pnp_key_id: str = ""
    ali_pnp_key_secret: str = ""
    ali_pnp_pool_key: str = ""      # 号池 PoolKey
    # 严格模式:未绑定中间号时不向商家/骑手下发真号(打码兜底,拨打按钮隐藏)
    privacy_phone_strict: bool = False
    # 订单完成/取消后多久自动解绑中间号
    privacy_phone_unbind_hours: int = 2

    # 骑手意外险(照支付桩模式)。未配置=登记模式:上线只落每日记录,
    # 保障金池兜底先行赔付;配置后每日首次上线自动投保
    insurance_app_id: str = ""
    insurance_secret: str = ""

    # 证照 OCR(入驻表单自动填充)。默认关闭;接的是**自部署的识别服务**
    # (本地模型起个 HTTP 服务),不走三方付费 API。配好 OCR_ENDPOINT 自动启用,
    # 未配置时 /ocr/license 返回 enabled=false,客户端静默跳过 ——
    # OCR 只是省几下手输,不是入驻流程的一环。
    # 对接契约见 routers/ocr.py 模块注释。
    ocr_endpoint: str = ""            # 如 http://127.0.0.1:18080/ocr
    ocr_timeout_seconds: float = 8.0  # 识别超时:超了就当没识别,不卡表单

    # 身份证二要素核验(姓名+证号一致性,照支付桩模式)。未配置走开发模式:
    # 格式与 GB 11643 校验位真实校验,通过即算实名;配置后调三方 API 核验一致性
    idcheck_api_url: str = ""
    idcheck_app_code: str = ""   # 三方核验服务凭证(如阿里云云市场 AppCode)

    # 阿里云短信(验证码)。AccessKey 建议用只授短信权限的 RAM 子账号
    sms_secret_id: str = ""       # 阿里云 AccessKey ID
    sms_secret_key: str = ""      # 阿里云 AccessKey Secret
    sms_sign_name: str = ""       # 已审核的短信签名,如「爱卡斯科技」
    sms_template_id: str = ""     # 短信模板 CODE,如 SMS_510415101
    sms_template_param: str = "code"  # 模板里验证码变量名(${code} 则填 code)
    sms_region_id: str = "cn-hangzhou"

    # 应用商店审核账号白名单:"手机号:固定码" 逗号分隔,如
    # "13900000001:246810,13900000002:135790"。命中的号码发码时不真发短信,
    # 登录时校验固定码即过(苹果海外审核员收不到国内短信,这是标准做法)。
    # 留空 = 功能关闭;固定码只放部署机 .env.prod,不进仓库。
    sms_review_accounts: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip():
            return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return [
            self.public_base_url.rstrip("/"),
            "https://www.chaojizan.cc",
            # 本地开发:官网 vite(5173)、商家后台(5174)、平台后台(5175)
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:5174", "http://127.0.0.1:5174",
            "http://localhost:5175", "http://127.0.0.1:5175",
            # 本地开发:Flutter web 三端(python -m http.server 或 flutter run -d chrome)
            #
            # ⚠️ 这几行是**必须的**,不是可选。原生 App 不发 Origin 头、
            # 不受 CORS 约束,所以三端在手机上一直好好的;
            # 一编成 web 就全变成跨域请求,不加白名单的表现是
            # **每一个接口都失败**,而浏览器控制台里只说 CORS,
            # 看不出来和后端配置有关。
            "http://localhost:5180", "http://127.0.0.1:5180",
            "http://localhost:5181", "http://127.0.0.1:5181",
            "http://localhost:5182", "http://127.0.0.1:5182",
            # 5183 是 .claude/launch.json 里 u-web 用的口。
            # 这两个文件要一起改 —— 少一行的表现是用户端 web 预览
            # 一个接口都不通,而控制台只说 CORS
            "http://localhost:5183", "http://127.0.0.1:5183",
            "http://localhost:5184", "http://127.0.0.1:5184",
            "http://localhost:8010", "http://127.0.0.1:8010",
        ]

    @property
    def flexwork_configured(self) -> bool:
        return bool(self.flexwork_app_id and self.flexwork_secret)

    @property
    def feie_configured(self) -> bool:
        return bool(self.feie_user and self.feie_ukey)

    @property
    def wxpay_configured(self) -> bool:
        return bool(self.wxpay_app_id and self.wxpay_mchid and self.wxpay_api_v3_key
                    and self.wxpay_cert_serial_no and self.wxpay_private_key_path)

    @property
    def jpush_configured(self) -> bool:
        return bool(self.jpush_app_key and self.jpush_master_secret)

    @property
    def ali_pnp_configured(self) -> bool:
        return bool(self.ali_pnp_key_id and self.ali_pnp_key_secret
                    and self.ali_pnp_pool_key)

    @property
    def idcheck_configured(self) -> bool:
        return bool(self.idcheck_api_url and self.idcheck_app_code)

    @property
    def ocr_configured(self) -> bool:
        return bool(self.ocr_endpoint)

    @property
    def insurance_configured(self) -> bool:
        return bool(self.insurance_app_id and self.insurance_secret)

    @property
    def sms_configured(self) -> bool:
        return bool(self.sms_secret_id and self.sms_secret_key
                    and self.sms_sign_name and self.sms_template_id)

    def sms_review_code(self, phone: str) -> str | None:
        """审核白名单:返回该手机号的固定验证码;不在白名单返回 None。"""
        for item in self.sms_review_accounts.split(","):
            p, _, code = item.strip().partition(":")
            if p == phone and code:
                return code
        return None


settings = Settings()
