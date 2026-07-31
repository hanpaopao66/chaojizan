# 地图与地理服务配置指南

> **2026-07-31 起地图服务改用腾讯位置服务**(此前是天地图,再之前是高德 3D SDK)。
> 高德 3D SDK 的 31MB .so 早已移除(APK 从 54MB 瘦到 ~22MB),方案仍是
> flutter_map 纯 Dart。高德只剩一个服务端用途:地址联想(AMAP_WEB_KEY,见第 3 节)。

## 0. 腾讯地图 Key(一把 key 两处用)

同一把 key 同时用于:

| 用途 | 在哪 | 不配的后果 |
|---|---|---|
| 客户端配送地图底图 | `packages/shared/lib/src/delivery_map.dart` | 退化为品牌网格示意,方位与距离仍真实 |
| 服务端逆地理解析城市 | `server/app/services/geo_city.py` | city 留空,不参与多城市隔离,管理后台人工填 |

1. [腾讯位置服务](https://lbs.qq.com/) 控制台申请 key。
2. 打包时注入:
   ```bash
   TENCENT_MAP_KEY=你的key scripts/release_apks.sh 0.7.1 2047 "更新说明"
   # 开发期:flutter run --dart-define=TENCENT_MAP_KEY=你的key
   ```
   服务端那份存 `server/.env`(本地,不入库)与部署机 `deploy/.env.prod`,
   变量名 `TENCENT_MAP_KEY`。

### 换掉天地图的两个理由

**坐标口径。** 腾讯是 GCJ-02,与本系统全局口径一致,直接传;
天地图是 WGS-84,原先每贴一次瓦片、每查一次城市都要转一道 ——
转换本身就是错误来源,少一层就少一类 bug。

**瓦片层数。** 腾讯的中文注记烘焙在同一层里;天地图要底图 `vec_w` +
注记 `cva_w` 贴两层,请求量翻倍。

### 踩过的坑:`tms: true` 不能省

腾讯瓦片的 y 轴是**自下而上**(TMS 口径),而 flutter_map 默认自上而下(XYZ)。
少这一行,请求照样返回 **HTTP 200** —— 只是给你一张地球另一边的空白瓦片,
表现为"地图一片灰"。极容易误判成 key 没生效或没配额。

判断方法:同一坐标按两种口径各取一张,**体积差十倍**的那张大的才是对的
(空白瓦片压缩率极高)。实测成都春熙路 z=16:TMS 17KB、XYZ 1.7KB。

## 0.1 外部地图导航跳转(无需 key)

骑手端「导航去取餐/送餐」唤起外部地图 App,支持腾讯/高德/百度,
装了哪些给哪些选、只装一个就直接跳。实现在
`packages/shared/lib/src/nav_launcher.dart`,**纯 URL Scheme,不接任何 SDK**。

两个必做的声明,漏了会静默失效(探测不到 = 当成没装,直接掉进网页版):

- Android:`AndroidManifest.xml` 的 `<queries>` 里声明各 scheme(11+ 起强制);
- iOS:`Info.plist` 的 `LSApplicationQueriesSchemes`。

坐标:腾讯与高德吃 GCJ-02 直接传;**百度吃 BD-09,必须转**
(`gcj02ToBd09`),不转会偏几百米,骑手照着导航跑到隔壁街。

---

以下为历史内容(服务端 AMAP_WEB_KEY 部分仍有效):


## 1. 申请高德 Key(免费,10 分钟)

1. 注册 [高德开放平台](https://lbs.amap.com/) 开发者账号(个人开发者即可起步)
2. 控制台 → 应用管理 → 创建新应用(名称随意,如 super-z)
3. 在应用下**添加两个 Key**:
   - **Android 平台** Key:
     - PackageName 填 `com.superz.rider_app`(即 `flutter create --org com.superz` 生成的包名,可在 `android/app/build.gradle` 的 `applicationId` 确认)
     - 发布版安全码 SHA1:开发期用 debug 证书的 SHA1,获取命令:
       ```bash
       keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android | grep SHA1
       ```
   - **iOS 平台** Key:Bundle ID 填 Xcode 里的 Bundle Identifier(默认 `com.superz.riderApp`)

## 2. 运行时注入 Key(不要把 Key 写进代码提交)

```bash
cd apps/rider_app
flutter run \
  --dart-define=SUPERZ_API=http://192.168.x.x:8010 \
  --dart-define=AMAP_ANDROID_KEY=你的AndroidKey \
  --dart-define=AMAP_IOS_KEY=你的iOSKey
```

没配 Key 时地图页会显示配置提示,其余功能(GPS 上报、抢单、外部导航)不受影响。

## 3. 平台目录配置(`flutter create` 之后做一次)

### Android:`android/app/src/main/AndroidManifest.xml`

`<manifest>` 根节点下加权限:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
<!-- 骑手端锁屏/后台持续定位:前台服务 + 常驻通知 -->
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_LOCATION" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
```

Android 11+ 要声明会唤起高德 App(canLaunchUrl 需要),`<manifest>` 下加:

```xml
<queries>
    <package android:name="com.autonavi.minimap" />
</queries>
```

### iOS:`ios/Runner/Info.plist`

```xml
<key>NSLocationWhenInUseUsageDescription</key>
<string>接单配送需要获取您的位置,用于向顾客展示配送进度</string>
<key>NSLocationAlwaysAndWhenInUseUsageDescription</key>
<string>配送途中锁屏也需要持续定位,顾客才能实时看到配送进度</string>
<key>UIBackgroundModes</key>
<array>
    <string>location</string>
</array>
<key>LSApplicationQueriesSchemes</key>
<array>
    <string>iosamap</string>
</array>
```

## 4. 坐标系约定(重要,别踩坑)

- 手机 GPS 原始输出是 **WGS-84**,高德地图显示用 **GCJ-02**(国家强制的加密偏移坐标)
- **Super-Z 全系统统一存储/传输 GCJ-02**:骑手端在 `LocationService` 里已经用 `wgs84ToGcj02()` 转换后才上报
- 商家/收货地址坐标将来从高德 POI 搜索/逆地理编码拿到的天然就是 GCJ-02,直接存即可
- 唤起高德导航的 URL 里 `dev=0` 表示"我传的已经是 GCJ-02,不要再转"

## 5. 上架前必须处理的合规项

- `amap_config.dart` 里现在是开发模式(默认同意隐私政策)。上架前必须做真实的**隐私政策弹窗**,用户点同意后再调 `AMapInitializer.updatePrivacyAgree`,否则应用商店审核不过、也违反个保法
- 息屏后持续定位已实现(`location_service.dart`:Android 前台服务 + 常驻通知,iOS Background Location + 蓝条指示),上面第 3 节的权限配置是它的前提;应用商店审核时要在隐私政策里说明后台定位用途
