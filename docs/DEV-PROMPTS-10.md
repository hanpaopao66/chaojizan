# 开发提示词 #122–#123:少发一次版

承接 docs/DEV-PROMPTS-9.md。这一批只解决一个问题:**想改点东西就得走一次三端发版**。

明确不做的:Dart 代码热更新(Shorebird 一类)。理由有三——只能改 Dart,救不了最麻烦的那类发版;
国内应用市场普遍禁止用热更新绕过审核改功能,iOS 侧 Apple 只明确放行 JavaScriptCore 那条路,
Dart AOT 打补丁是灰区;补丁分发依赖第三方 CDN,国内稳定性不可控。
刚做完上架整改,这个险不划算。

---

### 122. 该下发的下发:文案与配置从客户端搬到服务端

```
把「改一句话要发一次三端版」这件事消灭掉。先读 docs/DEV-PROMPTS-8.md 的「设计基线」。

现状:服务端已经有下发通道(GET /platform/config、/platform/announcements、
/platform/splash,以及 services/flags.py 的一批开关),但 /platform/config 只回了
一个 {"marketing": bool}。真正天天想改的东西全硬编码在客户端:
- 帮助中心 FAQ:apps/user_app/lib/help_page.dart 的 _faqs,10 来条静态元组;
- 各种引导/空状态文案,散在 main.dart、settings_page.dart、money_flow_page.dart;
- 首页金刚区三格(点外卖/住宿/超值团购)的标题与副标题。

业务规则(已拍板):
- **可下发的只有"说明性文案"**:FAQ、空状态、引导语、金刚区标题这类。
- **承诺类数字绝不做成自由文本下发**。「商家总负担 5% 封顶」「配送费 100% 归骑手」
  这种,必须由服务端**按真实配置算出来**再下发,不接受后台人工填写。
  理由:一旦是自由文本,任何人都能把它改成「3% 封顶」而实际照抽 5%——
  那就从"承诺"变成了"广告词",整个透明叙事的地基就没了。
  实现上:服务端读平台费率配置生成这句话,后台看得到但改不了。
- 客户端**必须保留一份完整的本地默认值**。首次启动、断网、接口挂了,
  用户看到的仍是完整内容而不是空白——下发只是"覆盖",不是"来源"。
- 不做通用 CMS。就是一个扁平的 key → 文案映射 + 一个 FAQ 列表,到此为止。
  需要富文本、多语言、AB 分流的时候再说,现在做进去就是负债。

技术要点:
- GET /platform/config 扩展为 {marketing, copy: {key: text}, faq: [{q, a}], rev},
  rev 是内容版本号(内容哈希即可),客户端可据此跳过无变化的重建;
- 新建 platform_copy 表(key/text/updated_at)+ admin 增删改接口,
  承诺类 key 由服务端注入、admin 接口拒绝写入(返回中文原因,别静默忽略);
- 客户端在 shared 里加一个 RemoteCopy:启动时拉一次、写 shared_preferences 落盘、
  取值时 remote[key] ?? local默认值。取值必须是同步的,不能让每处文案都变成 FutureBuilder;
- 配置拉取失败一律静默(与 update_checker 同口径:检查失败不打扰使用)。

验收:e2e_remote_copy.py —— 下发后客户端口径变化、承诺类 key 写入被拒(422 + 中文原因)、
承诺文案里的费率与 /platform/config 的真实费率一致、接口 500 时客户端仍有完整默认文案
(这条在客户端侧用单测或手动断网验证)。
```

---

### 123. 应用内下载并直接安装(仅自建分发渠道)

```
把更新从四步变一步。先读 docs/DEV-PROMPTS-8.md 的「设计基线」。

现状:packages/shared/lib/src/update_checker.dart 检测到新版后弹框,点「立即更新」
是 launchUrl 跳系统浏览器。用户要:等浏览器下完 20MB → 拉通知栏 → 找到 apk → 点安装 →
过一遍"未知来源"授权。中间掉两次人,弹框里那句"点击更新后在浏览器下载"就是在给流程打补丁。

业务规则(已拍板):
- 目标流程:弹框 → App 内下载(带进度)→ 下完直接拉起系统安装器 → 覆盖安装。
- **渠道感知,这条是硬约束**:应用商店明确禁止绕过审核自更新。
  编译期传 --dart-define=SUPERZ_CHANNEL=self|store,**store 渠道整个更新检查直接关掉**
  (连弹框都不弹),self 渠道才走上面的流程。默认值取 self(自建分发是当前主渠道)。
- 任何一步失败都要能退回老路:下载失败、校验失败、系统不给拉安装器,
  一律回退到"跳浏览器下载"并说明原因。绝不能让用户卡在一个转圈的进度条上。

技术要点:
- **必须校验 SHA-256**。发版脚本把三端 APK 的 sha256 写进 versions.json,
  客户端下完比对,不匹配就删文件并回退。不校验等于给中间人一个装任意 APK 的口子——
  这是这条需求里唯一不能省的部分。
- 下载落 getExternalFilesDir(应用私有目录),不需要任何存储权限;
- 安装走 FileProvider + Intent.ACTION_VIEW + application/vnd.android.package-archive
  + FLAG_GRANT_READ_URI_PERMISSION;
- Android 8+ 要用户授予"安装未知应用":先 canRequestPackageInstalls() 判断,
  没授权先弹**中文用途说明**再跳设置页——与 v0.4.0 整改立下的规矩一致
  (所有权限申请前先弹中文说明,同意后才调系统);
- 原生部分做成本地插件包 packages/apk_installer(path 依赖),照 packages/jpush_flutter、
  packages/mobile_scanner 的 vendor 先例。不要在三个 MainActivity 里各抄一份;
- **AndroidManifest 的取舍要写进注释**:三端 manifest 是为上架整改特意精简过的
  (一排 tools:node="remove"),现在要加回 REQUEST_INSTALL_PACKAGES 这个敏感权限。
  当前只做单一构建(权限常在,store 渠道靠 dart-define 不触发);
  **上架前必须拆 productFlavors(self/store)把该权限从 store 包里摘掉**,
  否则审核一定会问"你为什么需要安装其他应用"。这条作为待办写进 docs,别忘了。
- 断点续传不做:20MB 全量,失败重来即可,别为省几 MB 引入一套状态机。

验收:
- 服务端 e2e:/app/latest 返回 sha256 且与 appdist 里的实际文件一致;
- 客户端在模拟器上真跑一遍:正常升级路径、sha256 故意改错时能回退到浏览器、
  未授权"安装未知应用"时能弹说明并跳设置;
- store 渠道(--dart-define=SUPERZ_CHANNEL=store)编译出来的包完全不弹更新框。
```

---

## 执行记录(#122 / #123)

2026-07-30 一轮做完,全量回归 390 项通过。

### #122 配置与文案下发 — 已完成

- 新表 `platform_copy`(key→文案)与 `platform_faq`,迁移 `0066_platform_copy_faq`。
  **autogenerate 顺带扫出的 carts/merchant_staff/orders 的 alter_column 与 withdrawals
  索引改名已剔除** —— 那是既有的模型-库漂移,让它搭一趟顺风车,将来出事根本对不上是哪次改的。
- `GET /config` 扩为 `{marketing, copy, faq, rev}`。rev 是内容哈希,内容一变就变。
- **承诺类文案锁死**:`pledge.*` 由 `_pledge_copy()` 按 `settings.commission_tiers`
  算出来(5% 封顶 / 最低 4%),admin 改它、删它一律 422 并说明原因;
  即使库里被塞进脏数据,下发时也会被计算值覆盖。
- 客户端 `RemoteCopy`(shared):`loadCached()` 只读本地缓存(毫秒级)在 main() 里 await,
  网络刷新 `refresh()` 不阻塞冷启动。取值 `RemoteCopy.text(key, 本地默认值)` —— 
  **签名强制要求 fallback**,从 API 层面杜绝"下发挂了就变空白"。
- 已接入的点位:首页承诺条、商家卡费率标、空品类招商位、关于我们、帮助中心 FAQ 整块。
  help_page 的 `_faqs` 作为完整本地默认值保留。
- e2e:`e2e_remote_copy.py`(承诺锁定、改被拒后值未变、rev 随内容变、删除回退默认值、越权)。

### #123 应用内下载并直接安装 — 已完成

- 新本地插件包 `packages/apk_installer`(Android only):`canInstall` / `openInstallSettings`
  / `install`。下载与 SHA-256 校验都放 Dart 侧,原生面越小越好。
  插件**不自己 apply KGP**,走 Flutter 内置 Kotlin —— 否则会触发
  "Future versions of Flutter will fail to build" 警告(实测改完后 apk_installer
  已从警告名单里消失,只剩第三方的 package_info_plus / share_plus)。
- `REQUEST_INSTALL_PACKAGES` 与 FileProvider 声明在插件的 manifest 里,一处生效三端。
  FileProvider authority 带 `${applicationId}`,三端同装一台手机不冲突(实测
  `com.chaojizan.user.apkprovider`)。
- 渠道感知:`--dart-define=SUPERZ_CHANNEL=self|store`,默认 self。
  **store 渠道整个更新检查直接 return**,连弹框都不弹。
- 发版脚本 `release_apks.sh` 计算三端 sha256 写进 versions.json,
  并在上传后**复核部署机上的文件哈希**,传输途中出错就地中止。
  (没用 `declare -A`:macOS 自带 bash 3.2 不支持关联数组,会直接报错。)
- 失败一律退回浏览器:versions.json 没带 sha256、下载失败、校验不过、
  ROM 打不开授权设置页 —— 都会 launchUrl 并在弹框里说明原因。

**模拟器实测的四条路径**(e2e 覆盖不到,只能真跑):
1. 正常升级:2041 → 下载进度条 → 系统安装器 → 装完 `versionCode=2042`,全程没离开 App;
2. 未授权"安装未知应用":先弹中文用途说明,「去设置」精确跳到本应用的授权页
   (不是全局设置),回来后弹框提示"授权后请再点一次";
3. sha256 故意写错:下完校验不过 → 删掉坏包 → 自动打开浏览器;
4. store 渠道:服务端明明有更高版本,一个字都没弹。

**过程中修掉的一个真缺陷**:装完的旧 APK 留在私有目录里不清理(实测残留 91MB),
每更新一版积一个、永远不会自己消失。改为下载前清空该目录 —— 里面要么是已装完的包,
要么是上次失败的残骸,一律没用了。

---

## ⚠️ 上架应用商店前必做

`REQUEST_INSTALL_PACKAGES` 目前对三端全局生效(单一构建)。上架前必须拆
`productFlavors(self/store)`,在 store flavor 的 AndroidManifest 里把它摘掉:

```xml
<uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES"
                 tools:node="remove"/>
```

理由有二:一是审核一定会问"你为什么需要安装其他应用";二是商店渠道本来就禁止
绕过审核自更新,那个包也确实不该有这个能力。三端 manifest 里已有一排
`tools:node="remove"` 的先例,照抄即可。
