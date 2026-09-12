# 小程序开放平台安全审计记录(DEV-PROMPTS-39 #335)

- 日期:2026-09-12;环境:本地开发库副本 + 本地 API(`APP_ENV=dev`,未配托管域名 —— 生产专属的
  那几条(Host 头、frame-ancestors、主域名挡内部路径)用单测按生产配置验);
- 方法:每一项先有一个能反复跑的检查,再**把被检查的保护弄坏一次**、确认检查真的会红,然后恢复。
  「守卫会响」一列写的就是那次破坏和红出来的那句话。检查一个都不瞎:探测器先拿真东西自检
  (比如先拿用户自己的登录 token 喂给 JWT 探测器,认得出来,「没扫到」才算数)。

跑法:

```bash
cd server && .venv/bin/python -m pytest tests/unit/test_miniapp_security_guards.py tests/unit/test_miniapp_switches.py
SUPERZ_API=http://127.0.0.1:8013 python -m tests.e2e_miniapp_security     # 另见 hosting / dev / storage / switches
MINIAPP_BROWSER_FIXTURE=/tmp/fx.json python -m tests.e2e_miniapp_security && FIXTURE=/tmp/fx.json node scripts/verify_miniapp_browser.mjs
cd apps/user_app && flutter test test/miniapp_bridge_test.dart
```

## 逐项

| # | 项 | 期望 | 怎么验 | 结果 | 守卫会响(弄坏 → 红) |
|---|---|---|---|---|---|
| 1 | token 隔离 | 页面看得到的一切里没有登录凭据 | `e2e_miniapp_security`:启动应答、托管页 HTML / 返回头 / 脚本、SDK、云存储五个操作、状态轮询、详情、授权后重签的 initData、模拟器启动,共 13 处扫登录 token 原文、JWT 形状、`Bearer`;`e2e_miniapp_identity` 另扫启动应答。手机端 WebView 只加载带启动片段的托管地址,不带 Authorization、不共享 cookie;网页版宿主的 localStorage(token 在那儿)和托管页不同源 | 通过 | 启动应答里塞一个 JWT → `启动应答 里有登录凭据:['JWT 形状的串']` |
| 2 | iframe 冒充桥 | 被丢弃 | 桥的会话令牌只发给主框架,不带或带错令牌的调用静默丢弃(`miniapp_bridge_test`「不带令牌、带错令牌的调用被静默丢弃」);网页版只认 `event.source === iframe.contentWindow` 且 origin 对的消息;托管页 CSP `frame-src 'none'`,页面里根本嵌不进第三方 iframe(浏览器检查:嵌 example.org 被 frame-src 拦下) | 通过 | 去掉令牌校验 → Dart 单测红;CSP 改 `frame-src 'self'` → 单测红 |
| 3 | 导航逃逸 | 不在容器内加载,弹离开确认 | 手机:WebView 导航回调只放行本应用的托管 origin(按 origin 比,不按前缀),外链先问「即将离开超级赞」再交系统浏览器(`miniapp_bridge_test`「导航白名单按 origin 比」)。**网页版原先没有防护**(跨域 iframe 里页面自己 `location.href = 别的站`,父页面拦不住也读不到地址),审计时补上:iframe 每次 load 后宿主发 ping(targetOrigin 是托管 origin,只有托管页收得到),8 秒没有 pong 就清空 iframe、报「页面跳到了这个小程序以外的地址」。实测:测试应用 2 秒后跳 example.org → 被停止显示;站内换页(每页引了 SDK)不误报;记事本、2048 不误报。托管服务只出静态文件,没有重定向 | 通过(网页版为本次新增) | 白名单改成按前缀比 → Dart 单测红;逃逸判定认任何 pong → Dart 单测红;官方小程序用旧 SDK 打的包 → 浏览器检查红「桥调用日志里有『没回应 ping』」 |
| 4 | CSP | 被拦并上报 | 浏览器检查(`scripts/verify_miniapp_browser.mjs`):托管页里请求没声明的域名、加载外部脚本、内联脚本、eval、嵌 iframe,五种都被浏览器拦下;声明过的域名不拦;违规报告送到了平台(开发者后台的 CSP 计数 0 → 5)。单测核 CSP 每条指令;`e2e_miniapp_hosting` 核返回头 | 通过 | CSP 放行 `unsafe-inline` / `unsafe-eval` → 浏览器检查红(`evalAllowed:true, inline:1`);单测改 script-src → 红 |
| 5 | 包校验 | 被拒 | `e2e_miniapp_hosting`:zip slip(`../evil.js`、`a/../../evil.js`)、符号链接、缺入口、缺清单、禁用扩展名、zip 炸弹、kind 不符,全部 422 且报告说清原因 | 通过 | 去掉「..」那条 → 红(「..」开头的段还会被「隐藏文件」那条拦下 —— 两层都在;测试改成断言具体那句话,才能证明每一层各自在守) |
| 6 | 存储型 XSS | 全部转义 | 服务端原样存取、不拼 HTML(`e2e_miniapp_security`);前端没有 HTML 写入口(单测扫 admin-web、developer-web、官网、官方小程序、SDK 的 `dangerouslySetInnerHTML` / `innerHTML =` 等,唯一例外是官网文档页 —— 放的是构建时从仓库 Markdown 转的 HTML,转换本身有「不透传原始 HTML、不出 javascript: 链接」的检查);真浏览器渲染五处:官网详情页、官网目录、开发者后台概览与展示信息、审核抽屉(更新说明、给审核员的话、描述、隐私政策)。App 端 Flutter `Text` 不解析 HTML | 通过 | 审核页用 `dangerouslySetInnerHTML` 放描述 → 单测红;官网详情把描述当 HTML → 浏览器检查红(`xss:2, img:1`) |
| 7 | IDOR | 拒绝 | `e2e_miniapp_dev`:别人的应用、版本、密钥、体验者、模拟器一律 404 | 通过 | `own_app` 不看开发者 → 红「别人的应用 GET … 应 404」 |
| 8 | open_id 不可关联 | 不同,推不出 user_id | `e2e_miniapp_identity`:按应用不同、同应用稳定;`e2e_miniapp_security`:删掉映射行再启动得到**新的** open_id —— 随机生成、表映射,不是从用户 id 算的 | 通过 | open_id 改成从用户 id 派生 → 红「删掉映射后还是同一个」 |
| 9 | 重放 | 开发者用 launch_id 挡;平台启动限流生效 | 服务端文档写了 `launch_id` 一次性校验(存 10 分钟);`e2e_miniapp_security`:同一用户每分钟启动 30 次放行、第 31 次 429(按撞上 429 的那一分钟数,不怕跨整分) | 通过 | 限流放宽到 1000 → 红(32 次全 200) |
| 10 | 密钥 | 日志、错误、响应里没有 AppSecret | AppSecret 只出现在创建、轮换那一次的应答里;另外 16 个开发者 / 管理 / 公开 / 用户接口(含一个错误应答)里都没有;库里只有密文。小程序相关的日志只有 CSP 报告、托管文件读取失败、公钥发布失败、签发失败四处,都不带密钥 | 通过 | 开发者应用详情带上 AppSecret → 红「开发者 · 应用 里出现了 AppSecret」 |
| 11 | 云存储隔离与配额 | 拒绝 / 4006 / 4005 | `e2e_miniapp_storage`:A 应用读不到 B 应用、甲读不到乙;1024 键与 5 MB 恰好成功、多一点 4006;每分钟 120 次、超了 4005 | 通过 | 读不按应用过滤 → 红「别的应用读不到」 |
| 12 | 隔离即时生效 | 立即 404 | `e2e_miniapp_hosting`:紧急隔离后同一地址立即 404、启动与云存储回 4009、目录里消失;`e2e_miniapp_switches`:拉「托管小程序」闸后文件立即 404 | 通过 | 可出版本不看隔离标记 → 红;入口 HTML 改成缓存一小时 → 红「入口 HTML 要每次回源」;托管文件不看急停闸 → 红 |
| 13 | 点击劫持 | `frame-ancestors` 拦下 | 单测按生产配置核:只有主站和配置的宿主 origin,没有 `*`。开发环境(`APP_ENV=dev` 且没配托管域名)是 `*`,本地联调用 | 通过 | frame-ancestors 退回 `*` → 单测红 |
| 14 | Host 头伪造 | 严格正则拒绝 | 单测按生产配置过中间件:大小写变体、带端口、多一级子域名、15 / 17 位、非十六进制、裸托管域名一律 404;托管域名下非 GET/HEAD、`/v/` 和 `/_sdk/` 以外的路径 404;生产主域名上的 `/_mini-host/` 404(没配托管域名时也 404,不退回同源托管)。`e2e_miniapp_hosting` 另核 appid 大小写变体 | 通过 | 正则不分大小写 → 红;带端口放行 → 红;放行 POST → 红;主域名开放内部路径 → 红 |
| 15 | 缓存投毒 | 缓存键含 host + 版本 | 执行时没有用 nginx `auth_request`(改成 API 直出,见 DEV-PROMPTS-39 执行记录),不存在那个缓存键。托管地址本身带 appid(子域名)和版本号(`/v/<版本>/`);入口 HTML `no-cache`,其余文件 `immutable`(地址带版本,内容永不变);上线文档里的 nginx 示例不缓存托管站点,要缓存时 `proxy_cache_key` 必须含 `$host` | 通过 | 同 12:入口 HTML 长缓存 → 红 |
| 16 | 日志卫生 | 不记请求体 | 全局异常留痕只记方法 + 路径;开放接口调用日志只记路径;小程序的云存储、启动不写日志;CSP 报告的日志只记被拦的 origin(单测喂一条带 open_id 和日记内容的被拦地址,日志里只剩 origin) | 通过 | CSP 日志记完整被拦地址 → 单测红 |

## §3 不变量的守卫(DEV-PROMPTS-39 §12 第 3 条)

每条不变量都有守卫测试,每个守卫都弄坏过一次、确认会红:

| 不变量 | 守卫 | 弄坏 → 红 |
|---|---|---|
| I1 登录 token 不进 WebView | `e2e_miniapp_security` 13 处扫描、`e2e_miniapp_identity` | 启动应答塞一个 JWT → 红 |
| I2 默认只给 open_id | `e2e_miniapp_security`(删映射再启动得到新的)、`e2e_miniapp_identity`(按应用不同) | open_id 改成从用户 id 派生 → 红 |
| I3 不卖位置 | `test_miniapp_catalog`:排序函数的输入字段、目录相关表的列名 | 目录表加 `boost` 列 → 红;排序输入加打开次数 → 红 |
| I4 审核的就是上线的 | `test_miniapp_invariants`:版本对象只写一次(已存在一个都不写)、版本路由上没有 PUT / PATCH / DELETE;`e2e_miniapp_hosting`:托管出去的字节就是上传的那份 | 去掉「已存在就拒绝」→ 红;加一条改文件的 PUT 路由 → 红(这条守卫第一版是空转的:新版 FastAPI 的 `include_router` 不再摊平路由,只扫 `app.routes` 一层什么都扫不到,弄坏一次才发现,已改成钻进 `original_router`,并断言至少扫到 8 条版本路由) |
| I5 处罚有原因、能申诉、换人复核 | `e2e_miniapp_review`:驳回必须带原因代码和说明、原结论人处理申诉 403 | 申诉不强制换人 → 红 |
| I6 不收钱、不接广告 | `test_miniapp_invariants`:SDK、宿主、服务端三张方法 / 能力表一致,且没有付款相关的名字;用户端没装广告 SDK | 能力表加「付款」→ 红 |
| I7 敏感能力逐次确认 | `test_miniapp_invariants`:定位、扫码、剪贴板、手机号不在可申请清单里,宿主和 SDK 没有对应方法;`e2e_miniapp_dev`:申请回「暂未开放」;昵称头像首次确认、可撤回(`miniapp_bridge_test`) | 定位直接可申请 → 红 |
| I8 用户的数据用户说了算 | `e2e_miniapp_storage`:看用量、导出、清空、注销级联删除;`test_miniapp_invariants`:开发者后台、管理后台碰云存储的只有模拟器,且只能是开发者自己的账号 | 注销不删云存储 → 红;开发者后台按任意用户读云存储 → 红 |

## 审计中发现并修掉的

1. **网页版导航逃逸没有防护**(第 3 项):补了 ping/pong。协议加了两种消息,SDK、App 网页版宿主、开发者后台模拟器、
   文档(SDK 参考、核心概念、故障排查)、DEV-PROMPTS-39 §5.4 一起改;SDK 2.0.0 还没发布(没 push、没部署),
   直接改在 2.0.0 上。代价:托管的每个 HTML 页都要引 SDK(文档已写明)。
2. **官方小程序把 SDK 打进了自己的包里**(`import … from packages/miniapp-sdk/src`):SDK 一改,记事本、2048 的包
   和 SHA-256 都要跟着重打。已重打并在开发库重新发布;浏览器检查加了「桥调用日志里不许有『没回应 ping』」,
   包里的 SDK 旧了会红。
3. **冷启动直达链接先于会话恢复**:从 `https://…/m/<appid>` 冷启动(安卓 App Links、网页版带 `#/m/…` 打开),
   落地页比 AuthGate 先跑,登录着的人也被带去登录页。落地页先恢复本地会话再打开。
4. **CSP 拦截计数的日期**:按 UTC 日期记、开发者后台按北京日期读,北京时间 0–8 点的拦截会记到前一天。改成北京日期。
5. **文档转换的链接**:`javascript:`、`data:` 这类协议原来会被当成相对路径拼到 GitHub 地址上(无害但不对),
   现在一律不出链接,检查脚本里加了探针。
6. zip slip 的测试原来分不清是哪一层在拦(见第 5 项),改成断言具体那句话。

## 没覆盖到的 / 剩下的风险

- **真机**:安卓模拟器(Android 16)上走过一遍(见 DEV-PROMPTS-39 执行记录):下拉抽屉、目录、记事本离线编辑后联网同步、
  2048 全屏与系统返回键、冷启动直达链接;手机端的导航拦截、令牌只注入主框架是 Dart 单测 + 代码走查。**真机那一遍还没做。**
- 同源的 iframe(开发者自己包里的页面)读得到令牌 —— 那本来就是开发者自己的内容;跨域第三方 iframe 被 `frame-src 'none'` 挡住。
- `style-src` 保留 `'unsafe-inline'`(前端框架常用内联样式;样式注入执行不了脚本)。
- 网页版的逃逸判定有 8 秒窗口:页面跳走后最多 8 秒内外站内容还显示在容器里(桥已经不认它了,拿不到任何身份和能力)。
- 托管域名、证书、nginx 都还没上生产(D1 未定),Host 头、frame-ancestors、主域名挡内部路径这几条是按生产配置跑的单测,
  上线后要在生产上照[上线文档](MINIAPP-ROLLOUT.md)的检查清单再验一遍。
