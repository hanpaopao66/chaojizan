from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://superz:superz@localhost:5432/superz"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-in-production"
    # 敏感字段(收款账号等)对称加密密钥;不配置时从 jwt_secret 派生。
    # 生产务必单独配置,且一经使用不可更换(见 services/crypto.py)
    crypto_key: str = ""
    # 7 天 + 客户端自动续期(/auth/refresh):商家端长期挂机也不会掉线,
    # 但被泄露的旧 token 一周后自然作废
    jwt_expire_minutes: int = 10080

    # 接口限流(Redis 固定窗口,按 分钟 计):防爆破/防刷,不为限制正常用户
    rate_limit_enabled: bool = True
    rate_limit_login_per_minute: int = 30      # 同一手机号密码尝试
    rate_limit_sms_per_minute: int = 5         # 同一手机号请求验证码(另有 60 秒重发限制)
    rate_limit_order_per_minute: int = 20      # 同一用户下单

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
    # 恶劣天气加价:管理员在后台一键开关(platform_flags.weather_surcharge),全归骑手
    delivery_weather_surcharge_cents: int = 200

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

    # 防刷单风控:同收货位置 24h 内达到 N 单(且多账号)触发标记
    risk_addr_orders_24h: int = 4
    # 骑手同时在途上限(ACCEPTED/READY/PICKED_UP,追加单随原单不占额度)
    rider_max_active_orders: int = 3
    auto_confirm_hours: int = 24       # 送达后超时未确认 → 自动完成
    sweep_interval_seconds: int = 30   # 清扫任务运行间隔
    auto_flow_enabled: bool = True     # 测试时可关掉后台任务,手动调 sweep_once

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

    # 高德 Web 服务 Key(POI 输入提示用,与客户端 SDK Key 是两种 Key)
    # 不配置时 /geo/tips 返回演示数据,开发期可跑通全流程
    amap_web_key: str = ""

    # 天地图服务端 Key(逆地理解析城市,多城市隔离用)。
    # 不配置时 city 留空人工填(空 city 不参与隔离,功能可降级)
    tianditu_server_key: str = ""

    # ===== 以下三组为待联调的外部服务,拿到资质/Key 后填 .env 即可启用 =====

    # 微信支付 V3(服务商模式前先用普通商户直连跑通)
    wxpay_app_id: str = ""            # 开放平台 App 的 AppID
    wxpay_mchid: str = ""             # 商户号
    wxpay_api_v3_key: str = ""        # APIv3 密钥
    wxpay_cert_serial_no: str = ""    # 商户证书序列号
    wxpay_private_key_path: str = ""  # apiclient_key.pem 路径
    wxpay_notify_url: str = ""        # https://你的域名/payments/wechat/notify

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
    def insurance_configured(self) -> bool:
        return bool(self.insurance_app_id and self.insurance_secret)

    @property
    def sms_configured(self) -> bool:
        return bool(self.sms_secret_id and self.sms_secret_key
                    and self.sms_sign_name and self.sms_template_id)


settings = Settings()
