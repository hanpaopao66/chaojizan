import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 首页金刚区显示哪些频道 —— 后台配置,不用发版。
///
/// ## 为什么不是编译期常量
///
/// 项目里本来有 `feature_flags.dart` 那种编译期开关(应用商店审核用)。
/// 但「这次先只上外卖和团购」这种决定会反复变,每变一次发一版 App、
/// 等审核三天 —— 那不是开关该有的成本。
///
/// ## 三层取值,而且**都取保守值**
///
/// 1. 后台配的(拉到就用,并写进缓存);
/// 2. 上次拉到的缓存(冷启动先用它画,首页不能等这个请求);
/// 3. 内置兜底 [_fallback] —— 和服务端 `CHANNELS_FALLBACK` 一致。
///
/// 三层都保守是刻意的:「读不到就显示全部」看着友好,实际是把一次网络抖动
/// 变成「已下架的业务在首页复活」。宁可少显示。
class ChannelConfig {
  static const _key = 'sz_visible_channels';

  /// 和服务端 services/flags.py 的 CHANNELS_FALLBACK 一致。
  /// 两边都写死是没办法的事(冷启动拉不到网络时要有东西画),
  /// 但**取值必须一样** —— 不一样的话首启和二启看到的首页不同。
  static const List<String> _fallback = ['food', 'voucher'];

  static List<String>? _memo;

  /// 同步取当前该显示的 key。**不发请求** —— 首页每帧都可能读它。
  static List<String> get current => _memo ?? _fallback;

  /// 冷启动时调一次:先读缓存(立刻可用),再后台刷新。
  static Future<void> load(ApiClient api) async {
    try {
      final sp = await SharedPreferences.getInstance();
      final cached = sp.getStringList(_key);
      if (cached != null && cached.isNotEmpty) _memo = cached;
    } catch (_) {
      // 读缓存失败不影响启动 —— 回落到内置兜底
    }
    try {
      final fresh = await api.visibleChannels();
      // **空列表也是一种有效配置**(管理员想全关),照收 ——
      // 判空回落的话他会发现"怎么关不掉"
      _memo = fresh;
      final sp = await SharedPreferences.getInstance();
      await sp.setStringList(_key, fresh);
    } catch (_) {
      // 拉不到就用缓存/兜底,首页照常画
    }
  }

  /// 测试用:直接置位,免得每条用例都要起一个假 ApiClient 再等它刷新完。
  /// 传 null 等于「没拉到过」,回落到内置兜底。
  @visibleForTesting
  static void setForTest(List<String>? channels) => _memo = channels;

  /// 测试用:恢复到「没拉到过」的初始状态。静态量在同一个进程里的用例之间
  /// 会串,不重置的话上一条用例配的频道会漏给下一条
  @visibleForTesting
  static void resetForTest() => _memo = null;

  /// 过滤频道注册表。**不改 tone** —— tone 是色槽下标,
  /// 隐藏两个频道不能让剩下的换颜色。
  static List<SzChannel> visible(List<SzChannel> all) =>
      all.where((c) => current.contains(c.key)).toList();
}
