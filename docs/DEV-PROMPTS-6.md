# 超级赞 Super-Z · 待开发功能提示词库(第六辑:商家网页工作台 + 平台后台补齐)

> 背景:商家目前只有手机 App。但酒店前台的工作场景是电脑(携程 eBooking 的
> 主战场就是网页版),外卖商家批量改菜/对账/看报表也远比手机高效。
> 本辑做两件事:**A. 商家网页版工作台**(全业态,#84–#90)、
> **B. 平台管理后台 admin.html 住宿补齐**(#91)、**C. 导流收口**(#92)。
> 商家侧后端 API 三业态已齐备(App 在用的同一套 /merchants/me/* 与 /stays/me/*),
> 网页工作台以纯前端工程为主。
> 建议顺序:84 地基 → 87/88 酒店版(前台电脑刚需,优先) → 85/86 外卖版
> → 89/90 通用 → 91 admin 补齐 → 92 收口。

## 通用约定

先读 docs/DEV-PROMPTS.md 顶部通用约定(平台口径:外卖 5% 封顶/团购核销 2%/
住宿 5% 离店计佣/配送费 100% 归骑手;金额分存整数;中文报错;完成后不 push)。

## 本辑专属拍板(默认遵守)

- **工程形态:新建 `merchant-web/` 独立 Vite 工程**,技术栈 React 18 + Vite +
  TypeScript + Ant Design(全局默认栈);照 web/ 的先例
  **构建产物输出到 `server/static/merchant`,由 FastAPI 静态托管在 `/merchant`**,
  生产机无需 node,部署零新增进程。不改 admin.html 的技术形态(它是平台内部工具,
  vanilla 单文件继续用,只补内容)。
- **复用后端,不新增商家接口**:登录 `POST /auth/login`(role=merchant,支持密码)与
  `POST /auth/sms-code` + `/auth/sms-login`(role=merchant);业务全部走 App 同款
  `/merchants/me/*`、`/stays/me/*`、`/vouchers/*`、`/invoices/*` 接口。
  确需补充的只允许是"读接口缺字段"级别的小改。
- **业态分叉与 App 一致**:登录后 `GET /merchants/me` 按 `biz_type` 进入
  外卖工作台或酒店工作台;基础设施(登录态/布局/对账/设置)共用。
- **API 客户端**:手写一个薄 `api.ts`(fetch + token 注入 + 401 跳登录 +
  中文错误透传),类型定义按用到的接口手写 interface——不引代码生成器。
- **实时性**:网页端复用现有 WebSocket `/ws/merchants/{id}?token=`
  (new_order / new_stay_order / urge 消息),声音提醒用 Web Audio 播放提示音,
  加浏览器桌面通知(Notification API,用户授权后弹)。
- **验收统一含**:`npm run build`(tsc 零错误)通过;开发用 vite proxy 连本地
  8010 实测主链路;不做自动化 UI 测试(人工过一遍验收清单即可)。

---

## A. 商家网页工作台

### 84. 工作台地基:工程/登录/业态分叉骨架

```
在 super-z 仓库新建「商家网页工作台」工程。先读通用约定与 docs/DEV-PROMPTS-6.md 本辑拍板。

现状:商家只有 Flutter App;web/ 是官网(React+Vite 无 TS);admin.html 是平台后台。后端登录 /auth/login 已支持 role=merchant 与密码登录,验证码登录 /auth/sms-code(开发模式返回 dev_code)+ /auth/sms-login 也可用;商家资料 GET /merchants/me 带 biz_type。
业务规则(已拍板):
- 新建 merchant-web/(React 18 + Vite + TS + AntD,中文 locale);vite.config 参照 web/:base '/merchant/',build.outDir '../server/static/merchant',dev proxy 把 /auth /merchants /stays /vouchers /invoices /uploads /ws 代理到 127.0.0.1:8010(ws 要 ws:true);
- FastAPI 挂载:main.py 把 server/static/merchant 挂到 /merchant(照 /site 的挂法);
- 登录页:手机号+验证码(默认,开发模式直接展示 dev_code 便于本地)与手机号+密码两种方式,role 固定 merchant;token 存 localStorage,api.ts 统一注入 Authorization,401 清 token 回登录页;
- 登录后拉 /merchants/me:无店铺 → 引导页("请先在商家 App 完成入驻",附下载二维码,网页版不做入驻表单——证照拍照上传手机更顺);pending → 审核中页(轮询);approved → 按 biz_type 进入对应工作台路由(/food/* 或 /hotel/*);
- 布局骨架:AntD Layout 左侧菜单+顶栏(店名/营业开关 Switch/退出),菜单项按业态渲染,先放占位页;顶栏营业开关直接可用(PATCH /merchants/me is_open,酒店未过审拦截的报错原样弹出)。
技术要点:react-router;api.ts 错误统一 message.error(中文 detail);营业开关与 App 语义一致;确保 /merchant 刷新任意子路由不 404(FastAPI 静态托管 fallback 到 index.html,照 /site 处理或加 catch-all)。
验收:build 零错误;本地起 8010 后 vite dev 实测:验证码登录(dev_code)→ 外卖演示号 13800000002 进外卖骨架、新注册酒店号进酒店骨架;401 过期回登录;营业开关生效(App 端可见状态同步)。
```

### 85. 外卖版:网页接单台(实时听单)

```
在 merchant-web 开发「外卖接单台」。先读通用约定与本辑拍板。依赖 #84。

现状:App 接单页功能全(接单/拒单带原因/出餐/缺货退款/自取核销/催单回复/小票补打),接口都是现成的 /merchants/me/orders 与 /orders/{no}/* 系列(具体以 packages/shared/lib/src/api_client.dart 里 App 调用为准,照抄参数);WS /ws/merchants/{id} 推 new_order/urge。
业务规则(已拍板):
- 三栏看板(网页宽屏优势,对标轻量 KDS):待接单 / 进行中(制作中·待取餐) / 今日历史,卡片含菜品明细、备注、催单标记、备餐计时(接单后计时,超承诺时长红色高亮);
- 操作:接单、拒单(弹层必填原因)、出餐完成、缺货退款(选菜品+份数)、自取核销(输 4 位取餐码)、云打印补打、催单一键回复"马上好";
- 实时:WS 新单 → 声音循环提醒(有待接单每 15 秒响一次直到处理)+ 桌面通知 + 待接单栏红点;WS 断线轮询保底(15 秒),顶栏显示连接状态;
- 新单声音需用户先点一次"开启声音"(浏览器自动播放限制,横幅引导)。
技术要点:提示音打包一个短 mp3;桌面通知点击聚焦回页面;拒单/退款等资金操作二次确认;时间统一北京时间。
验收:build 零错误;本地实测:App 下单(或 e2e 造单)→ 网页 3 秒内响铃+通知+进待接栏;接单→出餐→(自取)核销全流程;拒单全额退款提示;断 WS 后轮询仍到单。
```

### 86. 外卖版:菜品批量管理 + 店内营销

```
在 merchant-web 开发「菜品管理与店内营销」。先读通用约定与本辑拍板。依赖 #84。

现状:App 有 dish_manage_page(单个编辑)与 shop_tab 满减/满赠/店铺券;接口 /merchants/me/dishes 系列、满减满赠走 PATCH /merchants/me、店铺券 /merchants/me/shop-coupons(以 App 实际调用为准)。网页价值 = 表格批量效率。
业务规则(已拍板):
- 菜品表格(AntD Table,行内编辑):名称/分类/价格/库存/每日限量/上下架/图,支持多选批量上下架、批量改分类;新增/编辑抽屉含规格组(与 App 同结构)、图片上传(/uploads);
- 估清与恢复一键操作(库存置 0/恢复默认);
- 满减(最多3档)/满赠(最多2档)/店铺券创建,表单校验与 App 相同(减额<门槛等),文案明示"成本商家承担,平台按券后实收计佣";
- 不做菜品 Excel 导入(饭馆菜单量级用不上,防脏数据)。
技术要点:行内编辑失焦保存,失败回滚并弹错;图片压缩到 1600px 再传;规格组编辑复用一个抽屉组件。
验收:build 零错误;实测:批量下架 3 个菜 App 菜单同步消失;新建带规格菜 → 用户端可点可下单;满减创建后用户端点单页出标签。
```

### 87. 酒店版:房态中控台(网页版核心,对标 eBooking)

```
在 merchant-web 开发「酒店房态中控台」。先读通用约定与本辑拍板。依赖 #84。这是酒店商家用网页的第一理由,交互精度对标携程 eBooking 网页版。

现状:接口全部现成:GET /stays/me/room-types、POST/PATCH 房型、GET /stays/me/calendar?from_date&days(≤90)、PUT /stays/me/calendar 批量(区间×多房型,留空不改,总量不能低于已售,首开必带价);App 里是 14 天小网格,网页要做大。
业务规则(已拍板):
- 主视图:横轴 30 天(可翻页/跳日期)、纵轴房型的大网格;单元格显示 价格/余量(总-售)/关房红标/未设价灰标;周末列头高亮;今天列钉左;
- 编辑:点单格弹小浮层改当日(价/量/开关房);**拖选区间**(同一房型行内横向拖多天)→ 批量浮层;工具栏"批量设置"弹窗(日期区间×多房型多选×价/量/房态三项留空不改);
- 键盘流:方向键移动焦点格,回车打开编辑,Esc 关闭——前台一只手就能操作;
- 房型管理页:表格 CRUD(名称/床型/面积/人数/取消政策三档+免费取消截止时刻/图片最多9张/上下架不删),政策改动提示"只影响新订单";
- 所有护栏报错(过去日期/低于已售/未设价)原样中文弹出。
技术要点:网格用虚拟化或直接渲染(30×房型数,量级不大直接渲染);拖选用 onMouseDown/Enter/Up 自实现;改动后只刷新受影响区间。
验收:build 零错误;实测:建 2 房型→批量设 30 天价量→拖选 5 天改价→关房 2 天;App 日历与用户端报价同步一致;键盘流可完整走一遍。
```

### 88. 酒店版:前台工作台(订单/入住离店/售后/点评)

```
在 merchant-web 开发「酒店前台工作台」。先读通用约定与本辑拍板。依赖 #84,建议接着 #87 做。

现状:接口现成:GET /stays/me/orders?state=pending|arriving|inhouse|leaving|all、confirm/reject/checkin/checkout、售后 GET /stays/me/aftersales + respond(协商退同意必须带 refund_cents)、点评 GET /stays/me/reviews + reply;WS 推 new_stay_order。
业务规则(已拍板):
- 今日看板首屏:待确认(角标)/今日预抵/在住/今日预离 四列卡片(前台每天开机第一眼),卡片含房型×间数、入离日期、入住人+电话、金额、取消政策;
- 操作:确认/拒单(必填原因,明示全额退)/办理入住(核对入住人弹窗)/办理离店(弹窗明示 实收=房费−5%佣金,离店后卡片显示实收);全部订单页带筛选分页;
- 新住宿订单:WS → 声音+桌面通知+待确认角标(与 #85 同一套提醒基建,复用);
- 售后页:待处理置顶,到店无房倒计时显示"剩 X 分钟自动成立",认罚/拒绝弹窗与 App 语义一致;协商退同意时填金额(0~全额);
- 点评页:列表+回复/追评回复;评分口径注明"近 180 天滚动均分,<3 条不出分"。
技术要点:四列看板与全部列表共用订单卡组件;倒计时用 created_at+2h 客户端算,到点自动刷新;售后拒绝必填说明。
验收:build 零错误;实测全链路:用户端下单→网页响铃→确认→(改库时间或当日单)办理入住→离店弹窗实收金额与对账一致;发起到店无房→网页处理;点评回复 App/用户端可见。
```

### 89. 通用:对账中心(全业态一张表)

```
在 merchant-web 开发「对账中心」。先读通用约定与本辑拍板。依赖 #84。

现状:接口现成:钱包 GET /merchants/me/wallet(余额已含 外卖+团购+住宿净额,含负余额)、流水 GET /merchants/me/earnings、对账单 CSV /merchants/me/finance/statement.csv?days=(已含 外卖入账/冲账/团购核销/住宿离店/住宿取消扣款/住宿违约金赔付 全类型行)、提现 /merchants/me/withdrawals、发票 /invoices/*、阶梯佣金 /merchants/me/commission-tier(以 App finance_page.dart 调用为准)。
业务规则(已拍板):
- 钱包卡:余额/累计/冻结/保证金留存/可提现,负余额(违约金)红字并解释成因;
- 流水表:AntD Table 按时间倒序,类型筛选(外卖/团购/住宿/冲账),每行 应收/佣金/实收 三列,佣金列鼠标悬停显示费率口径;CSV 一键下载(直接开 statement.csv 链接带 token?——fetch blob 下载,避免 URL 带 token);
- 提现:发起(校验最低额/可提现额,报错原样弹)+ 记录表(状态/打款凭证);
- 发票:按月可开票金额(外卖佣金+团购服务费+住宿服务费三行分列)+ 申请 + 记录;
- 阶梯佣金进度条(外卖业态显示;酒店业态隐藏,显示"住宿固定 5% 离店计佣")。
技术要点:金额展示统一 分→元 两位小数;CSV 下载用 fetch+Authorization 转 blob;表格分页服务端有 limit 就前端截断。
验收:build 零错误;实测:住宿离店后流水行出现且钱包同步;CSV 打开与页面合计一致;提现发起→admin 打款→记录状态流转;发票申请走通。
```

### 90. 通用:店铺设置 + 店员 + 公告(按业态渲染)

```
在 merchant-web 开发「店铺设置」。先读通用约定与本辑拍板。依赖 #84。

现状:接口现成:PATCH /merchants/me(公告/图集/营业时间/临时歇业/节假日计划/起送价/打包费/承诺出餐时长/自配送)、店员 /merchants/me/staff、云打印 /merchants/me/printer(以 App shop_tab.dart 调用为准);酒店专属字段在 hotel_profiles(目前无商家自助改接口——本条允许补一个小接口 PATCH /stays/me/profile 改 前台电话/入退房时刻/设施标签,两证与档次不可自改)。
业务规则(已拍板):
- 通用区:门头图集(≤9张)、公告、营业时间、临时歇业(N小时/到打烊)、节假日计划表格、店员管理(手机号添加,提示"对方需先用商家端登录过"——多角色账号语义)、联系客服工单;
- 外卖区(biz_type=food):起送价/打包费/承诺出餐时长/自配送开关/云打印绑定;
- 酒店区(biz_type=hotel):前台电话/入退房时刻/设施标签(走本条新增的 PATCH /stays/me/profile);两证信息只读展示+"变更资质请走客服工单";
- 两个业态互相看不到对方的设置区(分叉渲染,不是隐藏开关)。
技术要点:新接口 PATCH /stays/me/profile 只放开三个字段并加 e2e(服务端一起提交);表单脏检查,离开提示未保存。
验收:build 零错误 + 新接口 e2e 绿;实测:改公告/图集 App 与用户端同步;酒店改前台电话后用户端订单详情"联系酒店"号码更新;店员添加走通。
```

---

## B. 平台管理后台(admin.html)住宿补齐

### 91. admin.html:住宿模块(审核证照/订单/售后/看板)

```
在 super-z 仓库补齐「平台管理后台的住宿能力」。先读通用约定。admin.html 是 vanilla 单文件(server/static/admin.html,2300+ 行),保持现有技术形态与代码风格,不引框架。

现状:后端已齐:GET /admin/merchants 已回填 biz_type+特种行业许可证字段;GET /admin/stay-orders?status&merchant_id&day(资金三行);售后数据在 stay_after_sales(admin 暂无只读接口——本条补 GET /admin/stay-aftersales);数据看板 /admin/dashboard 的 pending 未含住宿售后。
业务规则(已拍板):
- 商家审核页:列表加业态徽标(外卖/酒店);酒店行展开显示 营业执照+特种行业许可证+卫生许可证 三张证照图(点击放大)与证号,审核员对照核验;驳回理由预置项加"特种行业许可证存疑";
- 新增「住宿订单」模块页签:筛选(状态/商家/入住日),表格含 单号/酒店/房型×间数/入离日期/入住人/状态/房费/佣金/实收/退款,金额列合计行;逐单可展开看取消政策快照与退款说明;
- 新增「住宿售后」区(并入现有售后仲裁页签):列表(类型/状态/发起时间/商家响应),pending 的到店无房标红倒计时;平台不直接改判(改判走工单人工+手工冲账),这里是监控视角;
- 数据看板:待办卡加"住宿售后待处理"数;指标区加 今日住宿单/间夜/在住(读 /screen/stats 的 stays 字段或补进 /admin/dashboard);
- 补的后端:GET /admin/stay-aftersales(status/merchant_id 筛选,limit 200)+ dashboard pending 加 stay_aftersales 计数,附 e2e。
验收:e2e(新接口)绿;浏览器实测:酒店待审商家能看到三证图;住宿订单页金额与 e2e_stays_settle 造的数据一致;售后监控可见 pending 与倒计时;看板出住宿待办。
```

---

## C. 收口

### 92. 商家网页版收口:部署托管/导流/文档

```
在 super-z 仓库收口「商家网页工作台上线」。先读通用约定。依赖 #84–#90 完成。

业务规则(已拍板):
- 部署:确认 FastAPI 静态挂载 /merchant 在生产 compose 里无需任何新服务;deploy/nginx 如有站点配置需要透传 /merchant 路径与 /ws WebSocket upgrade,一并检查;
- 导流:官网商家招募页(web/src/JoinPages.jsx)加"网页版商家后台 chaojizan.cc/merchant"入口与一句话说明(酒店前台电脑管理房态/外卖批量管菜);下载页商家端卡片加同款链接;商家 App 店铺设置页加一行"电脑上管店:chaojizan.cc/merchant"(纯文案行,可复制);
- 文档:README 架构图加 merchant-web/;DEV-PROMPTS.md 通用约定技术栈行补一句"商家网页工作台 merchant-web(React+TS+AntD)";
- 全链自查清单跑一遍:外卖商家(登录→接单→改菜→对账→设置)、酒店商家(登录→房态→接单→入住离店→售后→点评→对账→设置)各过一遍并截图留档 docs/(或口头确认)。
验收:web 与 merchant-web 双构建绿;本地 FastAPI 直开 http://127.0.0.1:8010/merchant 能登录使用(不经 vite);官网/README 文案就位;grep 确认无遗漏的"仅 App"文案误导。
```

---

## 附:为什么不把 admin.html 一起重写成 React

admin.html 是内部工具,用户只有你自己,vanilla 单文件的改动成本最低、部署零依赖;
商家网页工作台是**给商家用的产品**,才值得上 React+TS+AntD 的工程化。
哪天 admin 功能多到单文件维护不动了,再立一辑迁移——现在不动它。
