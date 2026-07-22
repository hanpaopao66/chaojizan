# 超级赞 Super-Z · 待开发功能提示词库

> 用法:把「通用约定」+ 想做的那一条提示词一起贴给 AI(或让它先读本文件),按提示词开发。
> 每条提示词自带:现状(代码在哪)、业务规则(已拍板)、技术要点、验收标准。
> 建议开发顺序按编号;有依赖关系的在提示词里注明。

## 通用约定(每条提示词都默认遵守)

- 技术栈:FastAPI + SQLAlchemy(async) + PostgreSQL/PostGIS + Redis;三端 Flutter(apps/user_app、merchant_app、rider_app,共享包 packages/shared);管理后台是单文件 server/static/admin.html;官网 React 在 web/。
- 关键文件:模型 server/app/models.py;配置 server/app/config.py;订单状态机 server/app/state_machine.py;清扫任务 server/app/services/auto_flow.py;审计恒等式 server/app/services/audit.py;公开账本 server/app/services/ledger.py(每日 payload 冻结、哈希链,witness/ 目录的校验器逐行复算);推送 services/push.py;退款统一入口 services/wechat_pay.py 的 request_refund。
- 铁律:金额一律用「分」(int);流水只追加不修改(冲账=负数行);任何资金变动必须过 services/audit.py 的恒等式和公开账本 witness 校验(改动后跑 e2e_reversal_audit + e2e_p4_witness);错误信息用中文直接给用户看;推送/打印失败绝不阻塞主流程(只记日志)。
- 迁移:alembic 版本号递增(看 server/alembic/versions/ 最新号),表结构改动必须带迁移,存量数据回填写在迁移里。
- 测试:server/tests/ 下加 e2e_<功能>.py(HTTP 风格,用 tests.util 的 call/login;演示账号 13800000000 管理员 / 01 用户 / 02 商家 / 03 骑手);改动涉及资金必须跑回归:e2e_orders、e2e_wallet、e2e_merchant_wallet、e2e_reversal_audit。
- 平台口径:商家佣金 5% 封顶、团购核销 2%、配送费 100% 归骑手、提现 T+1 零手续费——任何新功能不得暗中违反;涉及费率展示的地方(官网/三端/协议/账本)保持同步。
- 完成后:flutter analyze 三端零问题;本地起服务跑通新 e2e + 回归;git commit(中文描述,不带 AI 署名);**不 push,等用户指令**。

---

## 1. 发票(平台服务费发票)

```
在 super-z 仓库开发「商家索取平台服务费发票」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:平台向商家收 5% 佣金和团购 2% 核销费,商家没有任何索票通道;客服工单(routers/tickets.py)里承诺过"发票疑问找客服"。
业务规则(已拍板):
- 商家在商家端按自然月申请开票,金额 = 当月平台佣金 + 团购服务费合计(从 merchant_earnings.commission_cents 与 voucher_purchases.commission_cents 按月聚合,系统算好不让商家填);
- 抬头信息(单位名/税号/邮箱)存在商家资料里,首次申请时填写,可改;
- 申请后进入管理后台「开票」面板,管理员线下开电子普票后把 PDF 链接/备注贴回,商家端可查可下载;一个月只能申请一次,金额为 0 不能申请。
技术要点:新表 invoice_requests(merchant_id, period 如 2026-07, amount_cents 系统算, title/tax_no/email 快照, status pending/issued/rejected, file_url, note, 时间戳);迁移;商家端对账页入口 + 申请页;管理后台新面板(参照「配送异常」面板的写法);金额聚合要排除冲账负数行对应的佣金(冲账行 commission 为负,直接 sum 即正确口径)。
验收:e2e_invoice.py——跑一单完成后按月聚合金额正确;重复申请 409;管理员标记 issued 后商家可见 file_url;金额为 0 的月份 422。
```

## 2. 阶梯佣金

```
在 super-z 仓库开发「阶梯佣金:单量越大费率越低」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:每家店的费率在 merchants.commission_rate(默认 0.050),下单时按店铺费率计佣(services/payment_core.py);5% 是承诺上限,只能降不能升。
业务规则(已拍板):
- 平台级阶梯,按商家「上个自然月完成单量」定档:0-499 单 5%,500-999 单 4.5%,1000+ 单 4%(档位存 config.py,可调但任何档不得高于 5%);
- 每月 1 日北京时间凌晨自动重算全体商家费率(auto_flow 里加月度任务,参照 maybe_run_daily_audit 的 Redis 防重手法);
- 商家端对账页显示当前档位、当月已完成单量、距下一档还差多少;费率变化推送商家。
技术要点:config 加阶梯表;auto_flow 月度 job 重算 UPDATE merchants.commission_rate;公开账本无需改(payload 的 commission_rate_max 仍是 5% 上限,witness 校验的是 ≤ 上限);历史订单佣金不动(下单时快照)。注意:管理员手工调过费率的店(低于档位价)不要上调——重算取 min(档位费率, 现费率)。
验收:e2e_tier_commission.py——直连 DB 造上月完成单量,手动调月度重算函数,断言费率降档、不上调手工优惠店、商家端接口返回档位信息;审计与 witness 回归绿。
```

## 3. 商家保证金

```
在 super-z 仓库开发「商家保证金」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:商家钱包(routers/merchants.py 的 _merchant_wallet)余额=外卖净额+团购核销净额-提现;售后商家责任退款靠冲账,商家余额不足时平台垫付无追偿手段。
业务规则(已拍板):
- 保证金额度平台统一 ¥500(config 可调),不强制预缴:从商家营收里自动留存——提现时校验「提现后余额 ≥ 未留足的保证金」,即先攒够保证金才能全额提;
- 保证金用途:售后冲账导致余额为负时自动抵扣;退店(注销店铺)时无纠纷全额退还(走一笔 merchant 提现);
- 商家端钱包卡明示:保证金已留存 X / 应留 500,可提余额口径同步调整。
技术要点:merchants 加 deposit_required_cents(server_default 50000,平台可按店调);钱包接口返回 deposit 字段,提现校验改为 balance - amount >= max(0, deposit_required - 已隐含留存) 的口径(实现上最简:可提额 = balance - deposit_required,不为负);审计 4b(商家余额不得为负)保持;auth.py 商家注销的余额检查同步。
验收:e2e_deposit.py——余额 600 时最多提 100;攒不够保证金时提现 409 且提示中文;调低 deposit_required 后可提额变大;回归 e2e_merchant_wallet。
```

## 4. 食品安全投诉

```
在 super-z 仓库开发「食品安全投诉(食安红线通道)」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:普通售后走 after_sales(商家先处理,拍照举证,可升级平台仲裁);食安问题(异物/变质/腹泻)混在普通售后里,没有专门通道和处置动作。
业务规则(已拍板):
- 用户端售后入口增加「食品安全」独立分类(异物/变质/食用后不适),强制拍照,可附医疗凭证;
- 食安投诉不经商家、直达平台(管理后台专属面板,标红加急);
- 平台处置动作:①先行全额退款(含配送费,fault=platform 垫付) ②可一键下架涉事菜品(dish.is_on_sale=false+备注) ③可暂停商家营业(is_open=false+approved 状态不变,附整改原因推送商家) ④记录处置留痕(监管检查时可导出);
- 同一商家 30 天内 ≥3 起成立的食安投诉,自动暂停营业待人工审核(auto_flow 或投诉成立时同步判断)。
技术要点:新表 food_safety_reports(order_id, customer_id, merchant_id, kind, desc, images JSONB, medical_urls, status open/confirmed/dismissed, actions JSONB 处置留痕, 时间戳);退款复用 request_refund + AfterSale(fault 记 'platform')以兼容审计规则6;管理后台面板;用户端售后页分流;商家端收到整改推送。
验收:e2e_food_safety.py——提交必须带图;confirmed 后退款流水齐、菜品可下架、商家可停业;第 3 起自动停业;dismissed 不动资金。
```

## 5. 骑手取餐交接异常

```
在 super-z 仓库开发「骑手取餐交接:取餐核验 + 交接异常」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:骑手到店后直接点「已取餐」(READY→PICKED_UP),没有任何核验,拿错单/餐不齐/到店发现根本没出餐都无通道;配送途中异常已有 delivery_issues(kind: cannot_contact/wrong_address/food_damaged/other)。
业务规则(已拍板):
- 取餐核验:小票上已印单号尾号 6 位,骑手点「已取餐」时输入尾号后 4 位核验(防拿错单);连续输错 3 次仍可强制取餐但记录标记;
- 交接异常:在 delivery_issues 上扩展两个 kind——not_ready(到店未出餐)/items_missing(餐不齐,需拍照)。上报 not_ready 自动给商家推送催单并把订单标记出餐延误一次;items_missing 走平台仲裁(复用现有 resolve 三选一,缺件金额可用缺货部分退款接口处理);
- 骑手在店等待超 10 分钟可无责转单(依赖 #9 转单,先留 TODO)。
技术要点:transition 接口 READY→PICKED_UP 时增加可选 verify_code 参数(尾号4位,错误 422,强制取餐传 force=true 并写 OrderEvent 备注);delivery_issues.kind 加两个取值(varchar 无需迁移,更新 schemas Literal 与骑手端选项、admin.html 的 DI_KIND);商家端收到 not_ready 推送。
验收:e2e_pickup_handover.py——错码 422、对码通过、force 留痕;not_ready 上报后商家收推送记录;items_missing 必须带图。
```

## 6. 订单取消规则

```
在 super-z 仓库开发「订单取消规则分级」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:状态机(state_machine.py)允许用户在 PAID 任意时刻取消、商家 PAID/ACCEPTED 取消;取消已统一全额退款。没有时间分级,商家已备餐被用户随意取消会亏料。
业务规则(已拍板):
- 用户自助取消:支付后、商家接单前——随时免费;商家接单后 2 分钟内——免费(反悔窗口);接单 2 分钟后——自助取消关闭,页面引导走「售后/联系商家」,商家同意后由商家端取消(全额退);出餐(READY)后不可取消,走售后;
- 商家取消(拒单)规则不变(必须填原因,全额退款),但每月拒单次数进店铺统计,管理后台可见;
- 取消原因枚举化:用户取消时选原因(点错了/不想要了/信息填错/其他),存 cancel_reason。
技术要点:transition 接口对 customer+CANCELLED 加时间判断(用 OrderEvent 里 accepted 的时间,查不到按可取消处理);用户端订单页按钮随状态/时间切换(倒计时可选);商家拒单计数用 SQL 聚合即可不加表;错误提示中文说明为什么不能取消。
验收:e2e_cancel_rules.py——接单前可取消;接单后 2 分钟内可取消(backdate 手法控制时间);超窗 403 且提示;READY 后 403;退款流水回归。
```

## 7. 用户催单

```
在 super-z 仓库开发「用户催单」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:用户着急只能打电话;商家端有本店未接单语音循环,但用户没有主动触达手段。
业务规则(已拍板):
- 订单在 PAID/ACCEPTED/READY/PICKED_UP 时,用户可点「催一下」:催商家(未出餐时)或催骑手(已取餐时),系统自动判定对象;
- 每单最多催 3 次,两次间隔 ≥3 分钟(Redis 限流,参照 ratelimit.py);
- 催单推送:商家端(语音播报「有用户催单」+橙色标记该订单卡)/骑手端推送;商家可一键回复预设话术(马上好/高峰期稍等),回复推送给用户;
- 催单与回复都写 OrderEvent(to_status 用 'urged'/'urge_reply' 这类事件型值,注意用户端时间轴 _OrderTimeline 按状态取时间,要兼容忽略未知事件)。
技术要点:POST /orders/{no}/urge(customer)、POST /orders/{no}/urge-reply(merchant,带话术枚举);Redis 键控频;商家端 WS 消息类型加 'urge'(参照 new_order 的处理:语音+横幅);三端 UI 小改。
验收:e2e_urge.py——正常催单推送记录落库;3 次上限 429;间隔限制 429;取消/完成态 409;时间轴不因事件型 OrderEvent 崩溃。
```

## 8. 商家出餐超时提醒

```
在 super-z 仓库开发「商家出餐超时提醒与考核」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:商家接单(ACCEPTED)后没有出餐时限;骑手到店等餐无数据;无人接单兜底只管没骑手的情形。
业务规则(已拍板):
- 商家可设「承诺出餐时长」5-60 分钟,默认 15(merchants 加字段);预约单以预约时间前推出餐时长为基准;
- 清扫任务:ACCEPTED 超过承诺时长未 READY → 推送商家(语音级)+每单提醒一次;超过承诺时长 1.5 倍 → 再推送一次并给用户推送致歉安抚(「商家出餐慢了,已催促」);
- 出餐超时率(超时出餐单/总完成单,近 30 天)在商家端对账页展示,管理后台商家列表可见,供将来排序降权用(本期只统计展示)。
技术要点:merchants.promise_ready_minutes 迁移;orders 加 ready_alerted_at(参照 no_rider_alerted_at 的每单一次手法,两档提醒可用同字段存档位或加一列);auto_flow 新 sweep 段;超时判定基准=accepted 事件时间(orders.updated_at 会被其他流转刷新,需查 OrderEvent 或加 accepted_at 列——拍板:orders 加 accepted_at 列,transition 到 ACCEPTED 时写入,顺便给 #6 取消规则用);统计 SQL 聚合。
验收:e2e_ready_timeout.py——backdate accepted_at 触发两档提醒各一次不重复;READY 后不再提醒;超时率接口口径正确。
```

## 9. 骑手转单

```
在 super-z 仓库开发「骑手转单」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:骑手抢单后(rider_id 落库)无法退出,突发状况只能上报异常等仲裁;抢单池 available-orders 只看 rider_id IS NULL。
业务规则(已拍板):
- 已抢但未取餐(ACCEPTED/READY 且属于自己):可自助转单——rider_id 置空回抢单池,推送在线骑手「有转出的单」;每骑手每天免责转单 2 次,超出仍可转但计数(后台可见,将来接考核);
- 已取餐(PICKED_UP)不可自助转单(餐在手上),只能走配送异常仲裁;
- 转单写 OrderEvent(actor=rider, 备注转单原因枚举:车坏了/身体不适/顺路冲突/其他);用户与商家不推送(无感,避免焦虑),但订单详情时间轴对用户隐藏该事件;
- 转出的单重新计入无人接单兜底的计时(以转单时刻为基准——实现:转单时刷新 orders.updated_at 并清空 no_rider_alerted_at,同时把无人接单兜底的即时单计时基准从 created_at 改为 GREATEST(created_at, 最近一次进入无骑手状态的时间),最简做法:orders 加 rider_pool_since 列,下单支付、转单时都写)。
技术要点:POST /riders/transfer/{order_no};每日计数用 Redis(自然日过期);auto_flow._sweep_no_rider 计时列替换为 rider_pool_since(迁移+回填=created_at);骑手端订单卡加「转单」按钮+原因弹窗。
验收:e2e_rider_transfer.py——转单后回池、他人可抢;PICKED_UP 转单 409;第 3 次转单仍成功但计数=3;转单后兜底计时从转单时刻起算(backdate 验证)。
```

## 10. 多骑手调度(顺路多单)

```
在 super-z 仓库开发「骑手多单与顺路调度(保持抢单制)」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:抢单池按下单时间排序,骑手可无限接单(无并发上限),没有距离/顺路信息;骑手位置在 Redis(RIDER_LOC_KEY)。
业务规则(已拍板):
- 并发上限:骑手同时在途(ACCEPTED/READY/PICKED_UP)最多 3 单,抢第 4 单 409(提示先送完手头的);
- 抢单池排序改为「综合分」:距商家距离(骑手最近位置)+ 等待时长加权,新单不再永远垫底;返回字段加 distance_m、顺路标记 same_shop(与手头单同商家)、same_way(与手头某单收货点距离 <800m);
- 骑手端抢单大厅显示距离和「顺路」徽标,我的配送页按建议顺序排(同商家先取、收货点近的连送);
- 不做强制派单,不做超时罚款——抢单制是产品立场。
技术要点:available-orders 查询后在 Python 层算分排序(池子 ≤50 条,不用上 PostGIS 排序);骑手位置从 Redis 取不到时退化为按等待时长;grab 接口加并发上限校验(count 在途单);顺路判断用 pricing.haversine_m。
验收:e2e_multi_order.py——3 单在途后第 4 单 409;池子返回 distance_m 与 same_shop 标记正确(造两单同商家);无位置时不报错。
```

## 11. 订单改地址

```
在 super-z 仓库开发「订单改地址」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:下单后地址不可改,填错只能取消重下(取消规则收紧后更需要);配送费按距离算(pricing.py),改地址会影响配送费与骑手收益。
业务规则(已拍板):
- 骑手取餐前(PAID/ACCEPTED/READY):用户可自助改地址,限同商家配送半径内;新配送费重算——变贵补差价(走一笔补价支付,mock 通道直接成功;微信通道未接前允许"欠差价禁止改贵"的降级:配送费不允许变贵,只许平移或变便宜并退差价),变便宜自动退差价(request_refund);
- 骑手已取餐(PICKED_UP):自助通道关闭,提示电话联系骑手,骑手可上报 wrong_address 异常走仲裁;
- 每单限改 1 次;改址推送商家(小票地址变了,建议补打)与骑手;OrderEvent 留痕(旧址→新址)。
技术要点:POST /orders/{no}/change-address(新地址三件套);重算 delivery_fee_parts;差价退款复用 request_refund,orders.total_cents/delivery_fee_cents 同步调;审计注意:配送费只进不冲的恒等式口径(rider_earnings 结算时用最终 delivery_fee_cents,订单未结算前改没有冲账问题,确认 audit 逐单校验用的是订单当前值);补打小票提示复用云打印。
验收:e2e_change_address.py——改近退差价流水正确;半径外 409;PICKED_UP 后 403;二次修改 409;总额恒等式回归绿。
```

## 12. 加菜改单

```
在 super-z 仓库开发「加菜(追加单)」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:支付后订单内容不可改;用户想加一瓶可乐只能重新下一单再付一次配送费。
业务规则(已拍板):
- 做「追加单」而不是改原单(原单金额/佣金/账本已冻结,改单会把资金口径搅乱——这是架构决定,不要改原单);
- 商家出餐前(原单 PAID/ACCEPTED),用户可从同商家追加下单:免配送费(delivery_fee=0)、免起送价校验、备注自动带「追加到订单#原单尾号」;追加单 parent_order_no 关联原单;
- 追加单是独立订单独立支付独立佣金(账本天然正确),但配送侧绑定:原单骑手自动获得追加单(rider_id 同步,不进抢单池),状态由商家出餐后随原单一起送;商家小票打印追加单时标注「追加单,随 #尾号 一起出」;
- 原单已出餐/已取餐后不可追加(提示重新下单)。
技术要点:orders 加 parent_order_id(迁移);下单接口加 append_to 参数(校验原单状态/同商家/同用户);抢单池排除有 parent 的单;原单骑手抢单后,追加单 rider_id 跟随(下追加单时若原单已有骑手直接继承,原单后抢到时同步 UPDATE 子单);结算正常走各自订单;用户端原单详情页加「加菜」入口,商家端/骑手端订单卡显示关联标记。
验收:e2e_append_order.py——追加单免配送费免起送价;原单骑手继承;出餐后追加 409;两单各自结算佣金正确;审计回归。
```

## 13. 电话脱敏(隐私号)

```
在 super-z 仓库开发「电话号码保护(隐私中间号)」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:订单接口把用户 contact_phone 明文给商家和骑手,小票也整段打印;这是投诉与合规高风险点。
业务规则(已拍板):
- 接入阿里云号码隐私保护(AXB 中间号)——照微信支付的桩模式做:config 留 ali_pnp_* 密钥字段,未配置时降级为「界面与小票只显示尾 4 位 + App 内一键拨打仍用真号」,配置后绑定 AXB,商家/骑手看到与拨打的都是 X 号;
- 绑定时机:支付成功(配送单)绑定 用户↔骑手 与 用户↔商家 两组;订单完成/取消后 2 小时自动解绑(过期时间参数化);
- 接口脱敏:orders 系列接口对 merchant/rider 角色返回 contact_phone 时,未配置隐私号则返回打码(138****0001)+新增 privacy_phone 字段(有中间号给中间号,没有给真号——过渡期开关 config.privacy_phone_strict,严格模式打码不给真号);小票(cloud_print 与商家端蓝牙票)只印中间号或打码号。
技术要点:services/privacy_phone.py 桩(bind/unbind,未配置直接返回 None);orders.py 的 order_out 按请求角色处理(order_out 目前无角色上下文,需要把 viewer 角色传进去——改 order_out 签名并全量排查调用点);解绑挂 auto_flow;脱敏逻辑写测试防回归泄漏。
验收:e2e_privacy_phone.py——严格模式下商家/骑手拿到的 contact_phone 是打码;customer 本人看真号;小票内容函数不含真号;非严格模式行为不变。
```

## 14. 未成年人保护与实名

```
在 super-z 仓库开发「用户实名认证(为酒类等受限品类做年龄核验)」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:用户手机号注册即用,无实名;骑手已有实名体系(RiderProfile,身份证+审核,routers/riders.py)可参照;#15 酒类限制依赖本功能。
业务规则(已拍板):
- 用户实名是「按需触发」不是注册门槛:只有购买受限品类(酒类)时要求完成一次实名;
- 实名方式:姓名+身份证号,对接三方二要素核验 API——照微信支付桩模式:config 留 idcheck_* 字段,未配置时走「开发模式」(格式校验通过即算实名,身份证校验位算法要真实校验),配置后调真实 API;
- 从身份证号解析出生日期计算年龄,≥18 才通过酒类核验;实名信息落库加密存(至少身份证号用对称加密,密钥进 .env,不明文入库不出接口——接口只回 verified: true/false 与 is_adult);
- 注销账号时实名数据一并删除(auth.py 注销流程补一刀)。
技术要点:新表 user_identities(user_id 唯一, real_name, id_no_encrypted, birth_date, verified_at);crypto 用 cryptography 库 Fernet(requirements 加依赖);POST /auth/verify-identity、GET /auth/identity-status;用户端「我的」页入口+受限下单时弹实名引导页。
验收:e2e_identity.py——非法身份证 422(校验位);合法且成年 verified=true is_adult=true;未成年 is_adult=false;接口任何响应不含身份证号明文;注销后记录删除。
```

## 15. 酒类限制

```
在 super-z 仓库开发「酒类商品销售限制」(依赖 #14 实名)。先读 docs/DEV-PROMPTS.md 通用约定。

现状:菜品(dishes)无品类风控标记,任何人可买任何商品;#14 提供 is_adult 判定。
业务规则(已拍板):
- 菜品加 is_alcohol 标记,商家上架/编辑时自助勾选(法律义务在商家,平台提供工具与拦截);
- 下单拦截:购物车含酒类 → 需已实名且成年,否则 422 引导实名;未成年实名用户直接拒绝(明确文案:依法不向未成年人售酒);
- 交付提示:含酒订单的小票与骑手端订单卡显示「含酒精饮品,查验收件人」提示行;
- 时段限制:平台可配置酒类禁售时段(config,默认不禁;留 platform_flags 开关按需启用);
- 用户端菜品卡与详情显示「酒」角标及"未成年人禁止购买"提示。
技术要点:dishes.is_alcohol 迁移(server_default false);DishIn/DishPatch/DishOut 加字段;create_order 校验(items 快照顺便记 is_alcohol,供小票判断);cloud_print 与商家端蓝牙小票加提示行;三端 UI 小改。
验收:e2e_alcohol.py——未实名购酒 422;成年实名通过;未成年 422;非酒商品不受影响;小票函数输出含提示行。
```

## 16. 深夜自动打烊与临时歇业

```
在 super-z 仓库开发「深夜安全打烊 + 临时歇业」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:商家有 open_time/close_time 每日自动开关店(auto_flow.sync_business_hours,窗口触发式,不干扰手动开关);没有"临时歇业到某时刻"与"深夜强制窗口"。
业务规则(已拍板):
- 临时歇业:商家端一键「歇业到今天打烊/歇业 N 小时」,到点自动恢复营业(区别于纯手动关店忘了开);
- 平台深夜保护窗(可选,platform_flags 开关+时段,默认关):窗口内全平台停止接新单(下单 409 文案友好),已有订单正常履约——为夜间运力/安全兜底,管理后台一键开关;
- 打烊前 15 分钟仍营业的店,用户端点单页顶部提示「商家即将打烊,尽快下单」。
技术要点:merchants 加 closed_until(timestamptz,迁移);手动/自动开店时清空;sync_business_hours 尊重 closed_until(未到点不自动开);create_order 校验平台窗口(flags 读取参照 weather_surcharge_on);商家端店铺页加临时歇业按钮组;用户端提示用 close_time 计算。
验收:e2e_business_hours2.py——歇业 2 小时内自动开店不生效、到点恢复(backdate);平台窗口开启时下单 409;窗口关闭恢复;原自动开关店回归(e2e_pricing_hours)。
```

## 17. 节假日营业设置

```
在 super-z 仓库开发「商家节假日营业计划」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:营业时间只有每日一段 open_time/close_time;春节歇业十天只能每天手动关店。
业务规则(已拍板):
- 商家可维护「特殊日期计划」列表:某日期或日期区间 → 歇业 / 特殊时段(如除夕只营业 10:00-15:00);最多 20 条,过期自动清理;
- 优先级:特殊日期计划 > 每日 open/close > 手动开关;当天有歇业计划时,自动开店跳过、且凌晨清扫时若在营业则关店;
- 用户端店铺页对"今天有特殊计划"的店显示提示(今日营业至 15:00 / 春节歇业至 2/12);
- 不内置法定节假日日历(商家自己填日期,避免维护日历数据的负担)——界面上给"明天/后天/自定义区间"快捷入口即可。
技术要点:merchants.holiday_plans JSONB([{from:"2026-02-05",to:"2026-02-12",closed:true} 或 {date,open,close}]),迁移;sync_business_hours 读计划判定当日有效时段;MerchantPatch 校验(区间合法、条数上限);商家端店铺页管理 UI;过期条目在月度任务里清理。
验收:e2e_holiday.py——歇业计划日自动开店不生效且在营业会被关;特殊时段按计划开关;计划外日期回归正常;非法区间 422。
```

## 18 + 19. 库存每日重置 与 菜品估清(一起做)

```
在 super-z 仓库开发「库存每日回满 + 一键估清」(两个功能耦合,一次做完)。先读 docs/DEV-PROMPTS.md 通用约定。

现状:dishes.stock 是一个只减不增的数(下单扣、取消回补),卖完要商家手动改;没有"今日售罄"概念。
业务规则(已拍板):
- 每日回满:菜品可设 daily_stock(空=不启用,沿用现状),启用后每天北京时间 04:00 stock 重置为 daily_stock(auto_flow 里挂,Redis 防重参照每日审计);
- 估清:商家端菜品列表每个菜加「估清」按钮=stock 置 0 并打 sold_out_today 标记;用户端显示「今日售罄」灰态(区别于下架);次日回满任务同时清掉估清标记(未启用每日回满的菜,估清次日也自动恢复 stock 为估清前值——estimated 前值存起来);
- 防误伤:估清瞬间已在购物车/支付中的单按现有扣库存逻辑自然失败,提示文案改为「该菜品今日已售罄」。
技术要点:dishes 加 daily_stock(nullable int)、sold_out_today(bool)、stock_before_soldout(nullable int),一个迁移;每日任务一条 UPDATE 搞定两类恢复;POST /merchants/me/dishes/{id}/sell-out 与撤销;DishOut 带 sold_out_today,用户端菜品卡灰态+徽标;下单 409 文案区分售罄/下架。
验收:e2e_daily_stock.py——估清后下单 409 文案正确;手动调用每日任务后:有 daily_stock 的回满、估清的恢复;连续两次任务幂等;库存回补回归(e2e_auto_flow)。
```

## 20. 满赠

```
在 super-z 仓库开发「满赠活动」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:营销工具只有商家满减(merchants.promo_rules,阶梯取最大一档,成本商家承担、平台按折后计佣)和平台首单立减;没有赠品能力。
业务规则(已拍板):
- 商家可配满赠:满 X 元赠指定菜品 1 份(最多 2 档,与满减可同时生效——满减动钱、满赠动货,互不冲突);赠品必须是本店在售菜品,赠品也扣库存(库存不足时该档满赠自动失效,不拦下单);
- 赠品以 price_cents=0 的行进入订单 items 快照(name 前缀「[赠]」),金额口径零影响:food_cents/佣金/账本全不变——这是本功能资金安全的关键,佣金基数自然不含赠品;
- 用户端结算页明示「已享:满 30 赠可乐」;商家小票赠品行照常打印(后厨要备货);售后缺货退款不允许选赠品行(price 0 无款可退,422)。
技术要点:merchants.gift_rules JSONB([{threshold_cents, dish_id, name快照}]),迁移;create_order 在满减计算后追加赠品行(扣库存用与正常菜同一条件 UPDATE,失败则跳过该档并在 promo_note 注明);refund-item 排除 price 0 行;商家端店铺页配置 UI(选菜弹窗);结算页/订单明细展示。
验收:e2e_gift.py——满足门槛出现赠品行且总额/佣金不含赠品;赠品库存不足时下单成功但无赠品行;缺货退款选赠品行 422;审计回归绿。
```

## 21. 骑手与商家申诉

```
在 super-z 仓库开发「判责申诉通道(骑手/商家)」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:平台单方面裁决的场景已有三类——售后判责(after_sales.fault)、配送异常裁决(delivery_issues.resolution)、差评(reviews);被判方无申诉通道,只能发客服工单自由文本。
业务规则(已拍板):
- 结构化申诉表 appeals:申诉人(rider/merchant)、类型(after_sale/delivery_issue/review)、目标 id、理由(必填)、证据图(可选)、status open/upheld(维持原判)/overturned(改判)、复核备注;
- 时限:被裁决后 72 小时内可申诉,每个目标只能申诉一次;
- 改判动作(本期只做资金可逆的两种):①配送异常曾判 rider 责先行赔付 → 改判为用户/平台原因:不追用户款(平台认亏),但给骑手消掉责任记录并推送正名;②售后曾判商家责冲账 → 改判:给商家补一条正向调整行(merchant_earnings,note 写明申诉改判,金额=被冲的净额),账本恒等式兼容(参照无人接单赔付行的写法:net==food-commission 口径);差评申诉成立则该评价隐藏(reviews 加 hidden 标记)不参与均分;
- 骑手端/商家端在对应记录旁给「申诉」入口,管理后台新面板复核。
技术要点:appeals 表迁移;三端入口(骑手:异常记录列表;商家:售后记录与差评);admin.html 面板;评分聚合改为排除 hidden(rating_sum 反规范化的,改判时同步扣减)。
验收:e2e_appeal.py——超时 422、重复 409;三种类型各走一遍:改判后商家补偿行金额正确、差评隐藏且评分回调、骑手记录消责;审计与 witness 回归。
```

## 22. 提现失败处理

```
在 super-z 仓库开发「提现打款失败闭环」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:withdrawals 状态只有 pending/paid/rejected,管理员线下打款后手动标记;打错了/银行退票没有状态,只能口头处理;将来接微信商家转账 API 需要失败回调落点。
业务规则(已拍板):
- 状态机扩展:paid 之后允许进入 failed(打款被退回):余额自动回到可提(余额是算出来的——failed 不计入已提现即可),给申请人推送「打款失败请核对收款信息」,并自动创建一条客服工单关联;
- failed 的申请可由申请人重新发起(新建一条,旧条留痕不复用);
- 管理后台:已打款的记录出现「标记退票」按钮(需填原因);列表状态筛选加 failed;
- 为将来 API 打款预留:withdrawals 加 channel(manual/wechat)与 channel_ref(转账单号),本期都是 manual。
技术要点:WithdrawalStatus 加 failed;钱包计算三处(riders/_wallet、merchants/_merchant_wallet、auth 注销校验、audit 4/4b)统一改为「非 rejected 且非 failed 计入已出」——注意 failed 是从 paid 回退,口径=不计入;迁移加两列;admin.html 与 e2e_wallet 断言更新;推送+自动工单(tickets 表直接插一条)。
验收:e2e_withdrawal_failed.py——paid→failed 后余额恢复、审计绿;failed 不可再改状态;重新申请成功;工单自动生成;骑手与商家两侧都验。
```

## 23. 对公结算(收款账户登记)

```
在 super-z 仓库开发「商家/骑手收款账户登记与打款风控」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:提现打款全靠管理员线下认人(演示阶段可行);没有收款账户信息,规模化后必然打错;#22 已给 withdrawals 留了 channel 字段。
业务规则(已拍板):
- 收款账户表 payout_accounts(user_id, role, kind: bank_corporate 对公/bank_personal 对私/wechat/alipay, 户名, 账号(加密存,接口只回尾4位), 开户行, verified bool, 时间戳);商家鼓励对公(个体户可对私),骑手默认微信/支付宝收款码信息;
- 提现申请时必须已登记账户,申请快照冻结账户信息(withdrawals 加 account_snapshot JSONB,打款照快照打,改账户不影响在途申请);
- 风控:新登记或修改账户后 24 小时内发起的提现,管理后台标黄「账户刚变更」,提示人工电话核实后再打款(只提示不拦截);
- 管理后台提现面板显示收款账户(尾4位+户名+开户行),一键复制打款信息。
技术要点:账号加密复用 #14 的 Fernet 工具(若 #14 未做,先在本任务里建 services/crypto.py);迁移两张表改动;商家端钱包页/骑手端钱包页加「收款账户」管理入口;提现接口校验+快照;admin.html 展示与黄标(created_at 比 account.updated_at 判断)。
验收:e2e_payout_account.py——未登记账户提现 422;登记后申请携带快照;改账户不影响在途快照;24h 内申请接口返回 recently_changed=true;接口无完整卡号泄漏。
```

## 24. 税务合规

```
在 super-z 仓库做「税务合规基础设施」(文档+报表+灵工桩,不接真实税务系统)。先读 docs/DEV-PROMPTS.md 通用约定。

现状:平台收入(佣金+团购服务费)有完整流水;骑手所得是个人劳务性质,无代扣与完税安排;协议(server/static/legal-terms.html)无税务条款;#1 发票解决商家侧索票。
业务规则(已拍板):
- 骑手灵活用工:对接灵工平台(代发+完税)照桩模式——config 留 flexwork_* 字段,未配置时提现流程不变,但骑手端提现页与协议加提示「收入需依法申报个税」;配置后 T+1 批量打款改为调灵工平台 API(本期只写 services/flexwork.py 桩:submit_payout(批次)→未配置 raise 已配置留 TODO);
- 平台税务报表:管理后台加「税务导出」——按月导出 CSV:①平台收入明细(佣金/团购费逐笔) ②骑手所得汇总(按人月度,配送费+打款记录) ③商家结算汇总(净额/提现);财务拿去报税用,口径与公开账本一致;
- 协议更新:用户协议与新增的商家入驻协议条款里补税务责任条款(商家自行开票纳税、骑手个税提示、平台代收代付性质说明)——文案写清楚放 legal-terms.html,别自创法律承诺,用"依法""相关规定"表述;
- README/docs 加 docs/TAX.md 说明当前税务安排与待接入项(灵工平台候选、服务商模式分账后的变化)。
技术要点:三个导出接口(admin 角色,StreamingResponse CSV,参照 merchants.py 的 statement.csv);报表 SQL 聚合注意冲账负数行(直接 sum 即净口径,单独列出冲账笔数);flexwork 桩;协议 HTML 与 docs。
验收:e2e_tax_export.py——三份 CSV 表头与金额口径正确(造一单完成+一笔冲账验净额);非 admin 403;导出金额与钱包/账本接口对得上。
```

---

## 25. 加急小费(用户驱动,平台零补贴)

```
在 super-z 仓库开发「无人接单加急小费」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:_sweep_no_rider(auto_flow.py)两档兜底——先告警广播找骑手,再超时取消+全额退款+安抚券;没有"难单加钱找人"的撮合。orders.tip_cents 已存在(下单时可设,100% 归骑手、不计佣金基数、结算 settlement 已按此分账),但下单后不能追加。抢单池 available-orders 排序 = 距离 − 等待时长加权。
业务规则(已拍板):
- 加急小费完全由用户出,平台不出一分补贴(平台目前没运营预算,绝不假装有);
- 触发时机:订单进入"无人接单告警"档(no_rider_alerted_at 已置),用户端订单页出现「加急小费,更快有人接」入口(未告警的单不打扰);已支付订单追加小费=一次补收款,补差价支付未接入前走 mock 降级(参照改地址对"补差价支付暂未开通"的处理:结构预留微信补收,dev 用 mock_pay 那套幂等入账),补收成功才把 tip_cents/total_cents 抬上去;
- 加了小费即时广播给在线骑手(push+WS,文案带金额)并让抢单池排序把 tip 计入权重(有加急的往前提),但不改半径规则(顺路仍豁免);
- 取消退款口径:tip 计入 total_cents,取消时随 total 一起退(现有退款链天然覆盖,补 e2e 断言即可);自取单/商家自送单不允许加急小费(无骑手环节)。
技术要点:POST /orders/{no}/boost-tip(校验:本人、非自取/自送、状态在无人接单窗口、金额区间);补收走 mock 幂等入账并预留微信补收扩展点;available-orders 排序权重加入 tip_cents;auto_flow 兜底取消时 tip 一并退(已在 total);后台运力看板(dispatch-overview)对有加急小费的待抢单打标(见 #28)。
验收:e2e_boost_tip.py——非告警窗口加急被拒;加急后 tip/total 抬升且抢单池该单排序上移;骑手抢到后结算含小费(100%归骑手不计佣);无人接单兜底取消时小费随全额退;审计与 witness 回归绿。
```

## 26. 天气停运后台开关(补按钮)

```
在 super-z 仓库补「极端天气停运」的后台开关按钮。先读 docs/DEV-PROMPTS.md 通用约定。

现状:后端 weather_shutdown flag 已全线接好——orders 下单 409(weather_shutdown_on)、兜底取消线缩短、三端横幅,且已在 _KNOWN_FLAGS 白名单;但 admin.html 头部只有"天气加价(weatherToggle)"和"深夜宵禁(curfewToggle)"两个按钮,停运只能裸调 API,运营没法一键操作。
业务规则(已拍板):
- 后台头部加第三个开关 shutdownToggle,与加价/宵禁并排,红色系警示样式(这是最重的一档:全平台停接新单);
- 开启需二次确认(文案说明:此后全平台暂停接新单,已下订单尽力履约,兜底取消线缩短);关闭同样确认;
- 三个开关互不冲突,各读各的 flag(加价=配送费+¥2、宵禁=时段停接、停运=立即全域停接)。
技术要点:纯前端——照 weatherToggle/curfewToggle 的 render/load/onclick 三段式复制一份 shutdownToggle,调 POST /admin/flags/weather_shutdown {value:on/off};loadShutdownFlag 挂进初始化;后端无需改动。
验收:后台点开停运→用户下单返回 409(现有 weather_shutdown 逻辑);点关→恢复接单;按钮状态与 GET /admin/flags 一致。可加轻量 e2e 断言 flag 读写,主要靠手测三端横幅。
```

## 27. 骑手考试成绩后台可见

```
在 super-z 仓库补「骑手考试成绩后台可见」。先读 docs/DEV-PROMPTS.md 通用约定。

现状:RiderExam(题库20抽10、80过)与 /exam/* 已完整,抢单前置已能按 rider_exam_required flag 卡"必须考过"(riders.py 的 _exam_passed);但后台骑手视图 AdminRiderProfileOut 只有 transfer_count_30d 和 online_7d_minutes,看不到"是否考过/最高分/考试时间",运营开了强制开关也无法核对谁没过、谁该催考。
业务规则(已拍板):
- 后台「骑手认证」模块每个骑手显示考试状态:已通过(分数+日期)/未通过(最高分)/未参加;
- 只读展示,不在后台代考代判;强制开关(rider_exam_required)本就在平台 flag,后台可顺带给个总开关按钮(可选,不做也行)。
技术要点:admin/rider-profiles 查询带出该骑手最新/最高 RiderExam(exam_passed/exam_best_score/exam_at);AdminRiderProfileOut 加这三个字段;admin.html 骑手行渲染考试徽标。
验收:e2e 或手测——考过的骑手后台显示"已通过 90 分";没考的显示"未参加";字段不影响现有骑手列表回归。
```

## 28. 在线时长考勤明细(后台只读)

```
在 super-z 仓库补「骑手在线时长考勤明细」后台视图。先读 docs/DEV-PROMPTS.md 通用约定。

现状:RiderSession 记在线开/闭区间,骑手端 me/worklog 可查,后台骑手视图只有"近7天在线分钟数"一个汇总数字;没有按天/按区间的出勤明细,运力规划只能看总量。当前定位是"只统计不考核"。
业务规则(已拍板):
- 后台「运力」或「骑手认证」模块提供某骑手的在线时长明细:按天列出在线区间与当日累计时长,可选日期范围(默认近14天);纯只读,不做考勤扣款/奖惩;
- 汇总:区间内总在线时长、日均、活跃天数——供运力规划,不与结算挂钩。
技术要点:GET /admin/riders/{id}/worklog?days=14 聚合 RiderSession(未闭合区间按当前时间截止);admin.html 点骑手弹出明细面板或复用现有骑手详情。
验收:e2e_admin_worklog.py——造两天在线记录后聚合的总时长/活跃天数正确;未闭合区间计到当前;越权(非 admin)403。
```

## 建议开发顺序

资金安全线(先):22 提现失败 → 23 对公结算 → 3 保证金 → 21 申诉 → 1 发票 → 24 税务
体验线:6 取消规则 → 7 催单 → 8 出餐超时(带 accepted_at) → 11 改地址 → 12 加菜 → 20 满赠
运力线:9 转单 → 10 多单调度 → 5 取餐交接
合规线:13 电话脱敏 → 14 实名 → 15 酒类 → 4 食安
商家经营线:16 深夜/临时歇业 → 17 节假日 → 18+19 库存/估清 → 2 阶梯佣金
运力后台补全线:26 停运按钮(最小) → 27 考试成绩 → 28 考勤明细 → 25 加急小费(最重,含补收款)

依赖关系:15 依赖 14;8 产出的 accepted_at 被 6 复用;9 改的计时基准影响无人接单兜底;23 复用 14 的加密工具(谁先做谁建 services/crypto.py)。25 依赖无人接单告警档(no_rider_alerted_at)已存在,且补收款走改地址同款"补差价未开通"降级;25 的加急标记要落到 28/dispatch-overview 的看板上。
