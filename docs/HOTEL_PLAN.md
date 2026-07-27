# 酒店住宿垂类开发方案

> 状态：已拍板，开发提示词见 **docs/DEV-PROMPTS-5.md**（#66–#83，商业化上线版，非 MVP）。
> 定位遵循平台三原则：低抽成、账目透明、不烧钱补贴。
>
> **拍板记录（2026-07-27）**：① 佣金 = 订单实付 5%，离店（核销）才计佣；② 架构走平行竖井（照团购券先例）+ `Merchant.biz_type` 复用经营主体，不抽公共订单层；③ 金刚区永远 8 格：点外卖、**住宿（第 2 位）**、超值团购、打车、家政、维修、货运、零工——**跑腿移除**。

## 一、商业化调研（携程为主）

### 1.1 携程商家侧：eBooking 功能清单

携程酒店商家后台叫 **eBooking**（网页 + 独立商家 App），核心模块：

| 模块 | 功能 | 我们是否需要（MVP 判断） |
|---|---|---|
| 订单管理 | 实时接单/拒单/修改预订、新订单提醒、未处理数角标 | ✅ 必须 |
| 房态管理 | 按日历开关房、保留房、限量售卖、每日房型房态表 | ✅ 必须（简化为"日历×房型×余量"） |
| 房价管理 | 日历式房价、单条/批量改价 | ✅ 必须 |
| 收益管理 | 数据看板、出租率、AI 调价建议（"生意通"） | ⏭ 后置（只做基础统计） |
| 营销活动 | 促销报名、金字塔/云梯竞价推广 | ❌ 不做竞价推广（违背三原则） |
| 点评管理 | 回复点评 | ⏭ 二期 |
| 结算 | 对账、佣金账单 | ✅ 必须（复用账本链，透明对账是我们的差异化） |
| 附加产品 | 早餐券、延迟退房等加购 | ⏭ 二期 |

### 1.2 携程的抽成与商家分级（我们要反着做的部分）

- 佣金率普遍 **12%–20%**：金牌 12%、特牌 15%–20%，稀缺资源可达 30%；开通"金字塔/云梯"推广再加 5%–30%。
- **特牌 = 全网独家**：签特牌就不得在美团/飞猪/booking 报价（排他条款，正是"吸血中介"的典型手法）。
- 2021 年携程因"二选一"等被处罚，行业对高佣金+排他普遍不满 → 这是我们的进入窗口。
- 参照系：京东 2025-06 以"最高三年 0 佣金"杀入酒旅，两天收到 ~5 万家申请，但要求房价打 85 折（羊毛出在商家身上）。**我们不搞 0 佣金噱头，直接给长期低费率、无排他、无竞价位。**

### 1.3 携程用户侧预订流程（客户端要对标的骨架）

搜索（城市/日期/关键词）→ 酒店列表（价格/评分/距离筛选）→ 酒店详情（房型列表，每个房型标注**取消政策**）→ 下单（入住/离店日期、入住人、到店时间）→ 支付（**在线预付** 或 **到店付**两种模式）→ 商家确认 → 入住 → 离店后可点评。

关键机制：
- **取消政策是房型级属性**：免费取消（限时）/ 付费取消 / 不可取消，预订时即锁定规则。
- 到店付本质是"免费预订"，可随时取消；预付单退款按取消政策扣款。
- 携程还有信用卡担保模式——我们**不做**（不碰用户卡信息）。

### 1.4 商家入驻资质（审核项）

酒店/民宿上线需要：**营业执照** + **特种行业许可证（旅馆业，公安核发）** + **消防验收** + **卫生许可证**；含餐饮再加食品经营许可证。平台入驻审核至少收营业执照 + 特种行业许可证两证照片，其余承诺制。

### 1.5 我们的商业化定价（建议，待拍板）

- 佣金：**订单实付的 5%，离店（核销）后才计佣**（对齐团购券"核销才收费"的心智；现行外卖 5%（见证节点恒等式 `fee <= food × 5%`、客户端 `five_percent.dart`）、团购 2%（`config.py: voucher_commission_rate = 0.02`），酒店定 5% 与外卖持平，对外一句话："住宿 5%，离店才收，取消分文不收"）。
- 取消/未入住（noshow）不收佣金；到店付订单同样按 5% 计佣（离店后从商家余额扣）。
- 无排他、无竞价排名、无年费；排序只按距离/价格/评分等客观因子。
- 账目透明：每笔订单的"房费—佣金—商家实收"三行账写入账本链，商家可在对账页逐单核对（对标 eBooking 结算模块，但做到链上可验证——这是携程做不到的差异化）。

## 二、产品范围（MVP）

### 商家版（酒店商家）
1. 入驻：填酒店信息 + 上传两证 → 平台审核。
2. 房型管理：房型名称、床型、面积、可住人数、图片、设施标签。
3. 房价/房态日历：按日设价、设余量、开关房（合并成一张"日历×房型"编辑表，学 eBooking 新版合并交互）。
4. 订单管理：新单提醒 → 确认/拒单 → 入住登记（核销）→ 离店。
5. 取消政策设置：房型级三选一（免费取消截止 X 点 / 扣首晚 / 不可取消）。
6. 对账：逐单佣金明细，链上凭证。

### 客户端（消费者）
1. 首页金刚区"住宿"入口点亮（已占位）。
2. 城市+日期+关键词搜索 → 酒店列表（距离/价格/评分排序）。
3. 酒店详情：图集、设施、位置地图、房型卡片（价格+取消政策）。
4. 下单：日期区间、间数、入住人姓名+手机号、预计到店时间。
5. 支付：在线预付（微信支付，复用现有支付模块）；到店付二期。
6. 订单中心：待确认/待入住/已入住/已离店/已取消，取消申请与按政策退款。
7. 离店后点评（二期）。

### 明确不做（MVP）
- 钟点房、小时房；信用卡担保；竞价推广位；PMS 直连/渠道直连（Channel Manager）；会员等级价。

## 三、技术实现方案

### 3.0 架构决策：竖井 vs 抽象（建议：竖井，但把"横向接入"固化成清单）

现状调研结论：仓库**没有多业态抽象**——`Order`/`Merchant`/`Dish`/`OrderStatus` 全是外卖语义（全仓 grep `biz_type|vertical|scene` 零命中），唯一的第二业态"团购券"走的是**平行竖井**：独立表 + 独立 router + 独立费率，然后在对账/发票/税务/账本链/见证节点/大屏六处各接一刀。

酒店的订单语义（日历库存、连住、取消政策、入住人、无骑手无配送）与外卖差异极大，强行抽公共订单层要动账本链 schema 和现网外卖主流程，风险远大于收益。**建议照团购券先例开第三个竖井**，但做两件事控制熵增：

1. `Merchant` 表加一列 `biz_type`（`'food'` 默认 / `'hotel'`），**经营主体复用 Merchant**——钱包、提现、微信分账（`sub_mchid`）、发票、税务全部白拿；酒店专属字段放新表 `hotel_profiles`，不污染 Merchant。
2. 把团购踩出来的"六处横向接入"写成本文档 3.4 的核对清单，作为今后每个新垂类（打车等）的验收项。

### 3.1 后端：数据模型（`models.py` 追加 + `alembic/versions/0061_hotel.py`）

```
hotel_profiles      — merchant_id(唯一), 星级/档次, 详细地址, 前台电话,
                      checkin_from/checkout_until(如 14:00/12:00), 设施标签JSON,
                      特种行业许可证号+照片, 卫生许可证照片(可选)
room_types          — merchant_id, 名称, 床型, 面积, 可住人数, 图片JSON,
                      设施标签JSON, cancel_policy(枚举, 见下), free_cancel_hours,
                      上/下架, sort
room_calendar       — room_type_id, date, price_cents, total_qty, sold_qty,
                      closed(开关房)   UNIQUE(room_type_id, date)
stay_orders         — order_no, user_id, merchant_id, room_type_id,
                      checkin_date, checkout_date, nights, rooms_qty,
                      guest_name, guest_phone, arrival_note,
                      nightly_prices(JSON快照), total_cents, fee_cents(5%),
                      cancel_policy快照, status, 各状态时间戳,
                      wx_transaction_id, refund字段
StayOrderStatus     — created → paid → confirmed → checked_in → completed
                      分支: created→closed(超时), paid→cancelled(按政策退款),
                      paid→rejected(商家拒单全额退), confirmed→cancelled,
                      confirmed→noshow(免佣)
```

取消政策三档（房型级，下单时快照进订单）：`free`（入住日前 X 小时免费取消，之后扣首晚）/ `first_night`（取消扣首晚）/ `strict`（不可退）。

**库存并发**：下单对区间内每一天执行原子 `UPDATE room_calendar SET sold_qty = sold_qty + :n WHERE date IN (...) AND closed = false AND sold_qty + :n <= total_qty`，影响行数 ≠ 天数即回滚；超时未支付/取消回补（团购券已有先例：超时关闭回补库存，照抄 `routers/vouchers.py` 的做法）。

### 3.2 后端：API 与服务

- 新增 `server/app/routers/stays.py`（`prefix="/stays"`），`main.py` 注册。端点分三组：
  - 商家自助 `/stays/me/*`：房型 CRUD、日历批量设价/设量/开关房、订单列表、确认/拒单、办理入住（核销）、办理离店、noshow 标记
  - 消费端：城市/关键词/日期搜索（复用现有 geo 距离排序）、酒店详情+房型报价（按日期区间聚合每晚价）、下单、取消、我的住宿订单
  - 公开：透明中心费率说明
- 支付照团购路径：`stays.py` 内自建微信下单 + 回调（调 `services/wechat_pay.py`），**不复用外卖 `payment_core.mark_order_paid`**（其内含骑手/配送语义）；离店时计佣入账走 `services/settlement.py` 新增 `settle_stay_order`
- 状态自动流转挂进 `services/auto_flow.py`：超时未支付关单回补库存、离店日次日自动 completed、入住日过后未入住未取消自动 noshow（免佣）
- `config.py` 加 `stay_commission_rate: float = 0.05`
- 入驻审核：`ApplyShopPage` 对应的后端审核流加业态分叉——酒店必传 **营业执照 + 特种行业许可证**（不是食品经营许可证），字段进 `hotel_profiles`

### 3.3 三端改动

**共享库（先改这里，三端共用）**：`packages/shared/lib/src/api_client.dart` 加 `/stays` 方法组；`models.dart` 加 `HotelProfile / RoomType / RoomDay / StayOrder` DTO。

**商家端 `apps/merchant_app/`**：
- 入驻页 `ApplyShopPage`（main.dart:155-350）加业态选择（餐饮/酒店），酒店走两证上传
- `biz_type == 'hotel'` 时 4 tab 换内容：住宿订单（对标现订单 tab，含新单语音提醒，复用 `listen_service.dart`）/ 房型房价（新 `room_manage_page.dart` 对标 `dish_manage_page.dart` + 新 `room_calendar_page.dart`：日历×房型网格，批量改价改量开关房，学 eBooking 合并交互）/ 对账（**直接复用 `finance_page.dart`**，钱包共用）/ 店铺（`shop_tab.dart` 按业态隐藏起送价/打包费/出餐时长/满减等餐饮项）

**客户端 `apps/user_app/`**：
- 金刚区（main.dart:518-548，现 8 格 4 列）加"住宿"：建议放第 3 位（点外卖、团购、住宿、打车…），共 9 格自然换行为 4+4+1 难看，**顺手把零工/货运合并一格或再补一个占位凑 10 格**（UI 细节实现时定）
- 新增 `hotel_pages.dart`（列表+筛选）、`hotel_detail_page.dart`（图集/设施/地图/房型卡片，取消政策标签用账目绿/警示色明示）、`stay_checkout_page.dart`（日期区间、间数、入住人，**不复用外卖 `checkout_page.dart`**——配送费/地址簿语义全不适用）、住宿订单详情（时间线 + 资金流卡片，对标现有 `_OrderTimeline`/`_MoneyFlowCard`，展示"房费—佣金—商家实收"）
- 支付复用 `payment_service.dart`

**骑手端**：不涉及。

### 3.4 横向接入清单（团购券踩出的六处，逐一打勾）

| # | 系统 | 改动点 |
|---|---|---|
| 1 | 钱包/对账 | `routers/merchants.py` 余额明细与对账 CSV 加住宿行 |
| 2 | 发票 | `routers/invoices.py` 支持住宿订单开票（发票内容"住宿服务费"） |
| 3 | 税务导出 | `routers/tax.py` 加住宿列 |
| 4 | **账本链** | `services/ledger.py::build_day_payload` 加 `stay_rows`；payload `schema` 1→2 需设**切换日**（历史锚点永不重算，切换日前锚点仍按 v1 校验） |
| 5 | **见证节点** | `witness/superz_witness.py::verify_rows` 加住宿恒等式 `fee == gross × 5%` 且 `net == gross - fee`；**同步 `witness/go/` 版本**；已分发的旧版见证节点要兼容 v1/v2 双 schema |
| 6 | 大屏/透明中心 | `routers/screen.py` 加住宿指标，`routers/transparency.py` 费率页加住宿 5% |

### 3.5 测试与里程碑

e2e 照惯例写 `server/tests/e2e_stays.py`（入驻→建房型→设日历→下单→支付→确认→入住→离店→结算恒等式）+ `e2e_stays_cancel.py`（三档取消政策退款金额、超时回补、noshow 免佣），加入 `Makefile` 的 `test` 目标；回归必须查退出码。

| 里程碑 | 内容 | 依赖 |
|---|---|---|
| **H1 后端闭环** | 模型+迁移 0061、`routers/stays.py`、库存并发、支付回调、状态机+auto_flow、两个 e2e 全绿 | 无 |
| **H2 商家端** | 入驻分叉、房型管理、房价房态日历、住宿订单页、shop_tab 业态隐藏 | H1 |
| **H3 客户端** | 金刚区入口、搜索列表、详情选房、下单支付、订单中心与取消 | H1 |
| **H4 横向打通+上线** | 3.4 六项清单、大屏、witness 双版本、部署、真机回归、首批商家入驻 SOP | H1–H3 |

H1 与 H2/H3 可部分并行（共享库 DTO 定稿后前端即可动工）。风险最高的是 **#4/#5 账本链 schema 升版**——切换日机制要先设计评审再动手。

## 四、信息来源

- [携程 eBooking 官网](https://ebooking.ctrip.com/)（商家后台功能：房态/房价/订单/结算/点评）
- [携程佣金与商家分级报道（网易）](https://www.163.com/dy/article/L2PSB2V80556HBFC.html)、[澎湃：酒店与 OTA 佣金之争](https://m.thepaper.cn/newsDetail_forward_30267324)
- [京东三年 0 佣金杀入酒旅（证券时报）](https://stcn.com/article/detail/2291215.html)、[21 经济网分析](https://www.21jingji.com/article/20250620/herald/68daac145c620b0270e14ad2debbd77a.html)
- [携程酒店平台规则](https://hotels.ctrip.com/hotelspecification.html)、[取消政策优化报道（环球旅讯）](https://m.traveldaily.cn/article/126690)
- [旅馆业特种行业许可证办理](http://www.jiudianrong.com/newsdetail/id/11915.html)、[宾馆行业综合许可办事指南（武汉洪山区政府）](https://www.hongshan.gov.cn/gzfw/yyyz/lg/202410/P020241016573588834384.pdf)

