/// 腾讯地图 SDK 的启动闸门(#138)。
///
/// ## 为什么必须有这一层
///
/// SDK 源码里写着:「必须在用户同意隐私政策后才能设为 true,**否则地图显示为空白**」。
/// 也就是说合规不是"应该做",是**不做就没有地图**,而且失败形态是静默的白板 ——
/// 没有异常、没有日志,只有一块空白,极容易被误判成 key 没配或网络问题。
///
/// 所以:
/// - 只能由 `PrivacyGate.onAgreed` 调用 [agreeAndStart],**不许在 main() 里
///   无条件调**。无条件调 = 用户还没点同意就初始化了地图 SDK,上架审核直接挂;
/// - 没走过这一步时 [ready] 为 false,地图组件走降级(网格示意),
///   而不是渲染一块白板。
library;

import 'package:flutter/foundation.dart';
import 'package:flutter_tencent_map/flutter_tencent_map.dart';

/// 腾讯地图 key。与服务端逆地理/POI 共用同一把,打包时注入:
/// `--dart-define=TENCENT_MAP_KEY=xxx`
///
/// **不写进代码、不进仓库**(安全扫描有腾讯 key 的形态规则拦着)。
const String kTencentMapKey = String.fromEnvironment('TENCENT_MAP_KEY');

/// SDK 是否已经可以用了。
///
/// 三个条件缺一不可:编进了 key、用户同意了隐私、SDK 启动成功。
/// 地图组件**必须**先看这个再决定渲染真地图还是降级图。
ValueListenable<bool> get mapReady => _ready;
final ValueNotifier<bool> _ready = ValueNotifier<bool>(false);

/// 这个平台有没有腾讯地图原生 SDK。
///
/// **只有 Android 和 iOS 有。** web 和三个桌面平台上,
/// `flutter_tencent_map` 没有对应实现 —— 调它的方法会抛
/// MissingPluginException,而那个异常会顺着 build 冒上去把整页炸掉。
///
/// 所以这里不是"能不能显示地图"的问题,是**碰都不能碰**:
/// [agreeAndStart] 在这些平台直接返回,`SzDeliveryMap` 走示意模式。
///
/// ## 为什么不上 web 版腾讯地图
///
/// 腾讯有 JavaScript API GL,web 上确实能做(HtmlElementView 嵌 div
/// 驱动 JS SDK)。但那是**另一套 API、另一份 key、另一套坐标与事件模型**,
/// 而桌面端腾讯根本没有原生 SDK —— 三个桌面平台还是要降级。
///
/// 现在的降级不是白板:方位和距离是真的,只是没有街道底图
/// (见 delivery_map.dart 开头那段)。先让五端都能跑,
/// web 版地图作为单独一件事再做。
bool get mapSdkSupported =>
    !kIsWeb &&
    (defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS);

bool _started = false;

/// 用户同意隐私后调用(挂在 `PrivacyGate.onAgreed` 里)。
///
/// 幂等:重复调用只生效一次 —— onAgreed 每次启动都会跑,而 SDK 的启动
/// 不该跟着跑第二遍。
Future<void> agreeAndStart() async {
  if (_started) return;
  _started = true;
  if (!mapSdkSupported) {
    // web / 桌面:插件没有这些平台的实现,调它会抛 MissingPluginException
    // 把整页炸掉。走示意模式(有方位有距离,只是没有街道底图)
    return;
  }
  if (kTencentMapKey.isEmpty) {
    // 没编 key 的包(开发/CI)不去动 SDK:调了也是白板,
    // 不如干脆走降级,让人一眼看出是"没配 key"而不是"地图坏了"
    return;
  }
  try {
    await TencentMapInitializer.setAgreePrivacy(true);
    await TencentMapInitializer.start();
    _ready.value = true;
  } catch (e) {
    // 起不来就降级,不让整个 App 崩在地图上 —— 地图是辅助信息,
    // 不是下单链路的一环
    debugPrint('腾讯地图 SDK 启动失败,降级为示意模式:$e');
    _ready.value = false;
  }
}

/// 用户**撤回**同意时调用(设置页里关闭地图功能等场景)。
///
/// SDK 侧只能设回 false;已经加载的地图会变白板,所以调用方要同时
/// 把 [mapReady] 观察到的降级状态反映到界面上。
Future<void> revokePrivacy() async {
  try {
    await TencentMapInitializer.setAgreePrivacy(false);
  } catch (_) {
    // 撤回失败不该阻断用户的撤回意图,本地状态照样置否
  }
  _ready.value = false;
  _started = false;
}

/// 传给 `TencentMap` widget 的 key 配置。两端用同一把。
TencentMapApiKey get tencentApiKey =>
    TencentMapApiKey(androidKey: kTencentMapKey, iosKey: kTencentMapKey);
