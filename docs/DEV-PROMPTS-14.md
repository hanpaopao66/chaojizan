# 开发提示词 #138:地图改用腾讯官方 Flutter SDK

承接 docs/DEV-PROMPTS-13.md。这一辑只做一件事:**把地图从栅格瓦片换成官方原生 SDK**,
并把三端所有用得到地图的地方一次配齐 —— 包括现在有的和将来要加的。

## 为什么换(实测数据,不是听说)

现在是 `flutter_map` + 腾讯栅格瓦片。问题只有一个:**糊**。

根因实测过:**腾讯与高德的栅格瓦片都只有 256×256**,没有高清版
(试过 `scale=2` / `hidpi=1` / 高德 `size=2`,返回的都是同一张 256 图)。
手机像素密度 2.75~3 倍,256px 被拉到 700 多物理像素,必然糊。
**这跟换哪家厂商无关**,是栅格方案在高密度屏上的固有问题。

原生 SDK 是矢量渲染,任意缩放都锐利,这是它唯一但决定性的优势。

### 代价要写清楚,别自己骗自己

| | 栅格(现在) | 官方 SDK |
|---|---|---|
| 清晰度 | 高密度屏上糊 | 矢量,锐利 |
| APK 体积 | +0 | **+13.4 MB**(实测空壳 14.6 → 28.0 MB) |
| 原生依赖 | 无 | `libtxmapengine.so` 单 arm64 就 3.6MB |
| 授权 | 直连瓦片,条款存疑 | 官方 SDK,最干净 |

体积这条要正视:当初从高德 SDK 换到 `flutter_map`,就是为了甩掉 31MB 的 `.so`,
APK 从 54MB 瘦到 22MB。**这次等于把一半瘦身吐回去。** 这是已经拍板接受的代价,
但**不要再往上叠**:除地图外不要顺手引入别的原生 SDK。

## 选定的包

`flutter_tencent_map` **1.0.1**,主页 `lbs.qq.com`,官方出品。

⚠️ **它 2026-07-21 才发布,总共只有 1.0.0 / 1.0.1 两个版本。**
这意味着:遇到的坑很可能没人踩过、issue 区没有答案、下个版本可能带破坏性变更。
锁死版本号,不要用 `^` 让它自己升。

---

### 138. 三端地图切换到腾讯官方 SDK

```
把 packages/shared 的两个地图组件从 flutter_map 迁到 flutter_tencent_map,
并把三端所有地图入口接上。先读 docs/AMAP_SETUP.md 与
packages/shared/lib/src/{delivery_map,map_picker}.dart。

## 一、先解决构建(不解决这个后面全白搭)

**开箱编译失败**,实测报错:
`Execution failed for task ':flutter_tencent_map:checkDebugAarMetadata'`

原因:插件自己声明 `compileSdkVersion 31`(见 pub-cache 里它的
android/build.gradle),而它的传递依赖 flutter_plugin_android_lifecycle
要求编译到 36。

绕法:在三端各自的 android/build.gradle.kts 里强制抬所有子工程的 compileSdk。
**必须放在 `subprojects { project.evaluationDependsOn(":app") }` 之前** ——
那句会立刻求值子工程,之后再挂 afterEvaluate 会报
`Cannot run Project.afterEvaluate(Action) when the project is already evaluated`
(这个顺序我踩过)。

好消息:插件 `minSdkVersion 21`,**不用抬 minSdk**。
(第三方那个 tencent_map_flutter 要求 26,会砍掉一批老机型,所以没选它。)

## 二、隐私合规是硬门槛,不是可选项

SDK 源码里写着:「必须在用户同意隐私政策后才能设为 true,**否则地图显示为空白**」。

- `TencentMapInitializer.setAgreePrivacy(true)` 之后才能用地图;
- 本项目已经有 `PrivacyGate`(首次启动隐私弹窗),它的 `onAgreed` 回调本来就是
  「同意前不初始化任何收集类 SDK」的挂载点 —— 接在那里,不要在 main() 里
  无条件调用。无条件调 = 用户还没同意就初始化了地图 SDK,上架审核直接挂;
- 用户**拒绝**时:地图区域要给出可理解的降级,不能是一块白板。

## 三、Key 的注入方式变了

栅格方案是把 key 拼进瓦片 URL;SDK 是 `TencentMapApiKey(androidKey:, iosKey:)`
传给 `TencentMap` widget,或走原生 manifest。

沿用现有口径:`--dart-define=TENCENT_MAP_KEY` 注入,**不写进代码、不进仓库**。
scripts/release_apks.sh 已经在传这个参数,不用改。
安全扫描已有腾讯 key 的形态规则(5 组 5 位),别绕过它。

## 四、坐标系:仍然是 GCJ-02,不要转

腾讯 SDK 用 GCJ-02,与本系统全局口径一致 —— **直接传,一次转换都不要加**。
这是当初从天地图(WGS-84)换过来的主要收益,别在迁移中把它丢了。

例外只有一个:唤起**百度**导航时要转 BD-09(`gcj02ToBd09` 已有,有测试钉着)。

## 五、要迁的两个组件

### DeliveryMapView(配送地图,三端共用)

现状:`points`(商家/骑手/送达点)+ `pathThrough`(连线顺序),
未配 key 时降级成品牌网格示意。

迁移要点:
- 标点用 SDK 的 `Marker`,连线用 `Polyline`(都是声明式 Set,不是命令式 add);
- 自适应边界用 `CameraUpdate.newLatLngBounds`,不要自己算 zoom;
- **降级路径必须保留**:未配 key / 用户拒绝隐私 / SDK 起不来时,
  仍然画品牌网格 + 三点连线。方位与距离本来就是真的,
  「没有街道底图」不该等于「这个功能没了」。

### MapPickerPage(地图选点)

现状:图钉钉死在屏幕中心、拖地图、停 400ms 反查地址。

迁移要点:
- 中心图钉继续用 Flutter 层的 `IgnorePointer` 覆盖物,**不要**用 SDK 的 Marker
  —— Marker 是贴在地图上的,地图一动它跟着动,那就不是准星了;
- 相机停止用 `onCameraMoveEnd` 回调,比现在的 Timer 防抖更准
  (但**仍要保留防抖**:连续微调会连发事件,而反查是按次计费的);
- 反查结果回来时若相机又动了就丢弃 —— 否则地址栏和图钉对不上(现有逻辑保留);
- 回传**用户点的坐标**,不是反查匹配到的 POI 坐标。
  用户拖到自家单元门口,不该被吸附到几十米外的小区大门。

## 六、把「所有用得到地图的地方」一次配齐

现在有的:
1. 用户端 · 配送地图(看骑手到哪了)
2. 用户端 · 收货地址选点
3. 商家端 · 自配送地图(店 → 送达点)
4. 商家端 · 店铺位置选点(入驻时必填)
5. 骑手端 · 配送地图(取餐/送达/自身位置)

将来要加的,现在就把接口留出来(不是现在实现):
- 骑手端**实时轨迹**回放(纠纷仲裁用,OrderEvent 已有时间戳)
- 商家端**配送热力**(哪片区域单多,决定要不要自配送)
- 用户端**周边商家地图视图**(现在只有列表)
- 多点路径(顺路串单做出来之后,一次画多个取送点)

所以 `DeliveryMapView` 的入参保持「一组点 + 连线顺序」的通用形态,
不要为「商家/骑手/送达」三个角色写死三个字段。

## 七、验收

- 三端都能编译出 release 包,APK 体积增量记录在案;
- 地图出街道底图与中文注记,**放大不糊**(这是本辑的唯一目的,要截图对比);
- 未同意隐私时地图不初始化,且区域内有可理解的降级显示,不是白板;
- 未配 key 的包仍能跑,降级成网格示意;
- 五个地图入口逐个走一遍,标点位置与真实地址相符;
- 导航跳转(腾讯/高德/百度)不受影响,百度终点不偏;
- flutter analyze 四个包全清,dart 测试全绿,安全扫描通过。
```

---

## 执行记录

三端已迁完并真机验证。

### 实测数据

| | 空壳工程 | 三端实际(单 ABI arm64) |
|---|---|---|
| 迁移前 | 14.6 MB | user 21.4 / merchant 29.1 / rider 20.2 MB |
| 迁移后 | 28.0 MB | user 28.6 / merchant 36.5 / rider 27.2 MB |
| 增量 | +13.4 MB | **+7.0 ~ +7.4 MB** |

实际增量比空壳测的小一半 —— 发版用 `--target-platform android-arm64` 出单 ABI 包,
空壳那次带了 x86_64 与 armeabi-v7a 三份 `libtxmapengine.so`。

### 清晰度(本辑的唯一目的)

真机截图确认:街道名、店名都是矢量渲染,放大后笔画依然锐利。
自绘的品牌标点(白边圆环 + 图标 + 名签)按 `devicePixelRatio` 绘制,同样不糊 ——
如果标点自己糊了,这次迁移就很讽刺。

### 踩到的坑(按遇到顺序)

1. **开箱编译失败**:插件声明 `compileSdkVersion 31`,传递依赖要 36。
   在 android/build.gradle.kts 里强制抬所有子工程。
   用户端与骑手端**早就有这段**(历史上接高德时踩过同一个坑),只有商家端要补;
2. **`afterEvaluate` 位置**:必须放在 `evaluationDependsOn(":app")` 之前,
   否则报 `Cannot run Project.afterEvaluate when the project is already evaluated`;
3. **`newLatLngBounds` 的 padding 是位置参数**,不是命名参数;
4. **包要装在 app 工程而不只是 shared**:shared 的 public API 暴露了 SDK 类型,
   app 侧解析不到 `package:flutter_tencent_map` —— 报错发生在 Dart 编译阶段,
   信息只有一行 `Couldn't resolve the package`,不看全量日志根本看不见;
5. **Marker 吃图片不吃 Widget**:`flutter_map` 的 Marker 直接吃 Widget,
   SDK 只吃 `BitmapDescriptor`。改用 SDK 默认图钉的话三端标点会退化成
   一模一样的系统红气球,商家/骑手/送达靠颜色区分的设计就没了。
   新增 map_pin_bitmap.dart,用 Canvas 按设备像素比画。

### 隐私门闩

`agreeAndStart()` 挂在三端的 `PrivacyGate.onAgreed`,与推送 SDK 同级。
`mapReady` 是 `ValueListenable`,两个地图组件都监听它 ——
没同意 / 没编 key / SDK 起不来时走降级,**不渲染白板**。

降级不是"功能没了":配送地图仍按经纬度线性映射画出标点与连线,
方位和距离本来就是真的;选点页给一句"可以直接用上方搜索选地址"。

### 顺带清理

`flutter_map` 依赖已移除(无人再 import)。`latlong2` 保留 —— 还有别处在用。

## 明确不做的

- **不引入 SDK 的定位能力**。项目已有 `location_service`,再引一套原生定位
  是重复依赖,还多一份隐私公示义务;
- **不用 SDK 的 POI 搜索**。服务端已经代理了腾讯 WebService
  (`/geo/tips`、`/geo/reverse`),key 只在服务端 —— key 一旦进 APK 就等于公开,
  配额按次计费,被盗刷是迟早的事;
- **不为地图加缓存插件**(flutter_map_tile_caching 之类)。SDK 自己管缓存,
  再叠一层只会让「为什么这块图不刷新」变得无法排查。
