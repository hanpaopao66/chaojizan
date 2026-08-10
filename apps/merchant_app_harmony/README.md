# 超级赞商家端 · 鸿蒙原生版(ArkTS)

鸿蒙 NEXT 之后**彻底移除了 AOSP 兼容层,APK 装不上去**,所以这不是"适配",
是一个独立的原生应用。提示词见
[docs/DEV-PROMPTS-28.md](../../docs/DEV-PROMPTS-28.md)。

## 先说最要紧的一件事:鸿蒙不给后台保活

安卓商家端靠**前台服务**把进程钉在前台优先级,做到"锁屏不丢单"。
鸿蒙不给这条路 —— 长时任务只认 `dataTransfer` / `audioPlayback` /
`audioRecording` / `location` / `bluetoothInteraction` /
`multiDeviceConnection` / `voip`(`taskKeeping` 只给 2in1,
`wifiInteraction` 只给系统应用),**"听订单"一种都不沾**。

声明 `audioPlayback` 再播静音音频保活是钻空子:系统会校验声明的模式和
实际行为是否一致,上架审核这一条也是明写的。更要命的是**它不可靠** ——
拿一个随时可能被收走的机制去兑现"锁屏不丢单",等于在午高峰押注。

所以这一版的听单口径是:

```
前台   → WebSocket 实时 + 15 秒轮询兜底 + 语音催单 + 屏幕常亮
后台   → 系统通知(推送)
回前台 → 立刻全量拉一次,补上后台期间漏掉的
```

服务端**本来就是这么设计的** —— `server/app/services/push.py` 里
`notify_new_order` 的注释原话:「新订单推给商家老板(离线也能听到,
替代只在前台有效的 WebSocket)」。安卓端的前台服务是锦上添花。

**结论**:没有华为开发者账号时,这个应用能做到「应用开着能接单、能打印、
能核销」;有了账号接上推送,才是「锁屏不丢单」。后者才是商家端存在的理由。
详见 `common/PushChannel.ets`。

## 状态

**这一版是盲写的,没有经过编译。** 本仓库的开发机上没有 DevEco Studio
和鸿蒙 SDK,`.hap` 构建和 CI 都跑不了。代码按华为官方文档
(Stage 模型、Network Kit、Connectivity Kit、ArkData、Media Kit)写成,
**第一次在 DevEco 里打开必然要修一批类型和 API 签名** ——
这是选择盲写的必然代价,不是质量问题。

**与安卓商家端完全对齐**:功能对照 31 项全有,接口 **99/99**,
共 11553 行 ArkTS、23 个页面文件。

安卓端有的,鸿蒙端都有了:

| | |
|---|---|
| 接单 | 隐私门 → 登录 → 入驻/选店 → 订单列表(听单/状态灯/催单/自动出票)→ 接单/出餐/自送/核销 → 详情 |
| 配送 | 骑手位置、自送地图(距离 + 拉起系统地图导航) |
| 菜品 | 分类分组、上下架、估清/补货、长按置顶、批量 |
| 对账 | 钱包提现、阶梯佣金、按日账单、提现记录、开发票 |
| 评价 | 三档筛选、回复与追评回复、售后同意/拒绝、判责申诉 |
| 店铺 | 营业开关、临时歇业、公告、打印设置 |
| 营销 | 满减 / 满赠 / 店铺券、推广物料 |
| 经营 | 看板(8 周趋势 + 流失漏斗)、经营分析、老客召回、店员、节假日、出餐承诺、明厨亮灶 |
| 合规 | 团购券核销、进货台账、健康证、许可证续期、平台规则 |
| 收款 | 微信特约商户进件(敏感字段只回尾号) |
| 连锁 | 多店切换、品牌汇总、升级成品牌 |
| 住宿 | 客房订单确认/拒单/入住/退房、房型、批量改价关房、评价、售后 |

四个底部页签:订单 / 菜品 / 对账 / 店铺 —— 和安卓端同一套顺序,
商家换机器时肌肉记忆能接上。**订单页常驻**(用 `Visibility.None` 隐藏而不是
销毁):它持有 WebSocket、轮询和催单定时器,切到菜单页就销毁的话,
商家在看菜单时就听不到单了 —— 而看菜单恰恰是午高峰前最常做的事。

接口层 `common/MerchantApi.ets` 覆盖安卓商家端在用的 **99/99** 个接口。

本机能做的检查都做了:39 个 .ets 的跨文件导入全部解析、无未使用导入;
23 个页面的错误态与重试路径齐全、无空 catch;
GBK 编码算法拿 Python 的 cp936 **全量对拍 21887 个可编码字符,零差异**;
小票版式与安卓端 `flutter test` 的输出**逐行比对一致**。
**但这些不等于能编译** —— ArkTS 的类型检查、装饰器规则、UI 语法
都要 DevEco 才验得了。

## 还剩的几处「请在别的端完成」

不是整块功能缺失,是几个**要拍证照原件或填一长串资料**的动作,
在手机上做体验很差,界面里直说了:

- 食品经营许可证换证的**提交**(状态、到期提醒都有,只是提交那一步);
- 连锁**开分店**(切店、品牌汇总、升级成品牌都有);
- 住宿**新增房型**(改价、关房、上下架都有);
- 老客召回的**发券**动作(人数、频控说明都有)。

## 微信进件这一页要特别看一眼

它碰身份证号和银行账户,是整个商家端最敏感的一段。三条规矩写死在
`ApplymentPage.ets` 的注释里:

1. **客户端永远拿不到明文** —— 服务端 Fernet 加密落库,只回尾 4 位。
   输入框里回填不了完整值,只能在 placeholder 显示「已保存,尾号 1234」;
2. **空输入框 ≠ 清空** —— 只提交本次真填了的字段。把空串发上去会把
   服务端已存的银行账户抹掉,而商家完全不知道;
3. **不在客户端留任何副本** —— 不存 preferences、不放 AppStorage、不打日志,
   提交完立刻从内存清掉。

## 怎么跑起来

1. 装 **DevEco Studio 6**(HarmonyOS SDK API 20);
2. `File > Open` 选中 **本目录**(`apps/merchant_app_harmony`),
   不要选仓库根目录 —— 根目录是 Flutter/Python 的工程,DevEco 认不出来;
3. 等 `hvigor` 同步完依赖;
4. `File > Project Structure > Signing Configs` 里配一次调试签名
   (需要登录华为开发者账号,自动签名即可);
5. 起模拟器或连真机,Run。

后端地址在 `entry/build-profile.json5` 的 `buildProfileFields.SUPERZ_API`,
默认指向线上。要连本机后端就改成 `http://<你的内网 IP>:8010` ——
注意**不能用 `127.0.0.1`**,那在模拟器里指的是模拟器自己。

**蓝牙打印要真机**,模拟器没有蓝牙。而且**配对要先去系统设置里做** ——
鸿蒙侧应用内直接配对经典蓝牙的路子不通畅,应用里只负责从已配对列表中选。

## 几条定死的规矩

Flutter 端踩过坑才立的,鸿蒙版直接照做,别再走一遍:

- **网络只有一个出口**(`common/Api.ets`)。任何页面都不许自己
  `http.createHttp()` —— 一旦开口子,超时、鉴权、401、错误文案就会各写一套;
- **隐私门在最外层**,同意之前一个请求都不许发;
- **金额全程用「分」的整数**,客户端不做浮点运算;
- **中文名用服务端下发的**(`status_label` / `fee_part_labels`),
  不在客户端另写映射 —— 否则会出现"骑手端说爬楼费、顾客端说远距离费";
- **订单列表拉失败绝不清空、绝不静默**。`orders` 同时驱动列表和催单语音,
  拉不到时列表是空的、语音不响,商家看到「一切正常,今天没单」,
  而单在往里进。午高峰漏一单,这个平台赔不起;
- **空列表和加载失败不能长得一样**。这是商家端最危险的歧义;
- **切店要一次切干净**:`X-Shop-Id` 请求头、持久化的门店 id、店铺对象、
  WebSocket、详情页。漏一处就是"切到二店,屏幕上还是总店的单";
- **自动打印必须去重**。轮询 15 秒一次,不去重就是一单出十几张票 ——
  纸是商家自己买的。

## 目录

```
entry/src/main/ets/
├── common/
│   ├── Api.ets           唯一网络出口(含 X-Shop-Id 与 CSV 纯文本出口)
│   ├── Session.ets       token / 门店 / 隐私同意版本,存 preferences
│   ├── MerchantApi.ets   84 个接口,方法名与 Flutter 端一一对应
│   ├── Listen.ets        听单:WS + 轮询 + 前后台 + 列表新鲜度
│   ├── PushChannel.ets   推送抽象(现为空实现,等开发者账号)
│   ├── Announcer.ets     语音催单 + 振动兜底
│   ├── Gbk.ets           GBK 编码(TextDecoder 反查建表)
│   ├── Escpos.ets        小票排版,逐行搬自安卓端
│   ├── BtPrinter.ets     蓝牙 SPP 传输
│   ├── DataSource.ets    LazyForEach 的数据源
│   ├── Upload.ets        photoAccessHelper 选图上传
│   └── Money.ets         分转元
├── model/                Models.ets / Params.ets
├── entryability/         EntryAbility.ets(前后台与推送点击转发)
└── pages/
    ├── Index.ets         根页面:隐私门 / 登录 / 选店 / 四个页签
    ├── LoginPage.ets     短信登录
    ├── OrdersPage.ets    接单主流程(常驻,持有听单)
    ├── OrderDetailPage.ets
    ├── DishesPage.ets    菜品管理
    ├── FinancePage.ets   对账与提现
    ├── ReviewsPage.ets   评价与售后
    ├── PrinterPage.ets   打印设置(蓝牙 + 云打印)
    ├── ShopPage.ets      店铺
    ├── VoucherPage.ets   团购券核销(Scan Kit)
    ├── PurchasesPage.ets 进货台账
    ├── CertsPage.ets     资质(许可证 + 健康证)
    ├── AnalyticsPage.ets 经营分析 + 老客召回
    └── MessagesPage.ets  消息中心
```

## 本机能跑的校验

没有 DevEco 就编译不了,但这三样是纯逻辑,能在本机验 ——
而它们恰好是最容易错、错了又最难发现的:

```bash
python3 tools/verify_gbk.py        # GBK 建表:和 Python cp936 全量对拍
python3 tools/verify_ticket.py     # 小票版式:和安卓端 flutter test 的输出逐行比对
python3 tools/check_imports.py .   # 跨文件导入导出
python3 tools/check_error_states.py .  # 空列表和加载失败长得一样
```

改了 `Gbk.ets` 或 `Escpos.ets` 就跑一遍。GBK 表建错了小票整张印成乱码,
**不抛异常、不报错**,只有商家拿到那张纸时才知道。

`check_error_states.py` 查的是这个仓库反复出现的一类 bug:
拉失败被显示成「这一栏没有评价」「还没有菜品」「平台还未开通云打印」——
每一条都会让商家照着错误的结论做决定。安卓端为此改过一整批
(DEV-PROMPTS-27 #240),这个脚本让同类问题能被机器查出来,
而不是靠下一次 review 撞见。

三个脚本都验过**能真抓到缺陷**,不是只验它不报警:
往 `FinancePage` 里注入"去掉错误态字段 + 塞一个空 catch",脚本报两处。
