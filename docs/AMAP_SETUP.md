# 地图与地理服务配置指南

> **2026-07-17 起客户端地图已切换到天地图**(flutter_map 纯 Dart 方案,
> 高德 3D SDK 的 31MB .so 从用户端/骑手端移除,APK 从 54MB 瘦到 ~22MB)。
> 高德保留两个用途:骑手跳转外部高德 App 导航(URI 协议,无需 Key)、
> 服务端地址联想(AMAP_WEB_KEY,见第 3 节)。

## 0. 天地图 Key(客户端街道底图,免费)

1. 注册 [天地图开放平台](https://www.tianditu.gov.cn/) → 控制台申请 Key。
   **App 打包必须用「服务器端」类型的 Key**——实测(2026-07)「浏览器端」Key
   对非浏览器请求一律 403(code 301012 权限类型错误,带 Referer 也没用),
   而服务器端 Key 未配 IP 白名单时瓦片畅通;浏览器端 Key 留给未来 Web 地图。
2. 打包时注入(不注入则地图自动进"示意模式":三点连线可用,无街道底图):
   ```bash
   TIANDITU_KEY=服务器端key scripts/release_apks.sh 0.4.0 4 "更新说明"
   # 或开发期:flutter run --dart-define=TIANDITU_KEY=服务器端key
   ```
   Key 本体存 server/.env(TIANDITU_SERVER_KEY / TIANDITU_BROWSER_KEY,
   不入库)与部署机 .env.prod,发版前 source 一下即可。
3. 免费配额:个人开发者 1 万次/天,够试运营;超量升企业配额(仍免费)

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
