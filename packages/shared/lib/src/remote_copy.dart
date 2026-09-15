import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';

/// 可下发文案(#122):改一句话不用发一次三端版。
///
/// 三条规矩,想改这个文件前先读:
///
/// 1. **下发只是"覆盖",不是"来源"**。每个调用点都必须传本地默认值,
///    首次启动、断网、接口挂了,用户看到的仍是完整内容而不是空白。
///    所以 [text] 的签名强制要求 fallback,没有只传 key 的重载。
/// 2. **取值必须同步**。文案散在几十个 build() 里,做成 Future 就等于
///    把整个 UI 拖进 FutureBuilder。启动时拉一次进内存,之后同步读。
/// 3. **承诺类文案(pledge.*)由服务端按真实费率算出来**,后台改不了。
///    客户端这边一视同仁地当普通 key 用即可 —— 拿不到就用本地默认值,
///    本地默认值也是按当前费率写死的那句,不会说出比服务端更高的承诺。
///
/// 拉取失败一律静默,与 [checkForUpdate] 同口径:检查失败不打扰使用。
class RemoteCopy {
  RemoteCopy._();

  static const _copyKey = 'remote_copy_v1';
  static const _faqKey = 'remote_faq_v1';
  static const _hiddenKey = 'remote_hidden_v1';

  static Map<String, String> _copy = const {};
  static List<FaqItem> _faq = const [];

  /// 后台藏起来的位置(`/config` 的 hidden,0142):底部菜单的一格、一段说明。
  /// 哪些位置能藏由服务端的登记表定(server/app/services/copy_registry.py),客户端只管照做
  static Set<String> _hidden = const {};

  /// 拉到新的文案 / 显示隐藏之后加一:底部菜单这类常驻的界面听它,拉到就当场换,不用等下次启动
  static final ValueNotifier<int> changed = ValueNotifier(0);

  /// 内容版本号(服务端算的内容哈希),便于排查"我改了怎么没生效"
  static String rev = '';

  /// 服务端功能开关(`/config` 的 features:video、video_upload、calls……)。
  /// 只用来收起入口 —— 关着的功能服务端照样回 503;拉不到就当开着,别因为断网把入口全藏了
  static Map<String, bool> features = const {};

  static bool feature(String key) => features[key] ?? true;

  /// 要公示的《信息网络传播视听节目许可证》编号(`/config` 的 licenses.av)。
  /// 后台「平台开关」里填,空 = 不显示;「关于我们」读它
  static String avLicense = '';

  /// 取一条文案。[fallback] 是客户端自带的完整默认值,不能省。
  static String text(String key, String fallback) => _copy[key] ?? fallback;

  /// 这个位置显示不显示(后台没藏就显示;拉不到配置也显示)
  static bool shown(String key) => !_hidden.contains(key);

  /// 测试用:直接摆好文案和隐藏的位置
  @visibleForTesting
  static void debugSet({Map<String, String>? copy, Set<String>? hidden}) {
    if (copy != null) _copy = copy;
    if (hidden != null) _hidden = hidden;
    changed.value++;
  }

  /// 取帮助中心问答。服务端没配就整体用本地默认值 ——
  /// 不做逐条合并:FAQ 是一篇要通读的东西,半本地半远端会读出前后矛盾。
  static List<FaqItem> faq(List<FaqItem> fallback) =>
      _faq.isEmpty ? fallback : _faq;

  /// 各端 main() 里 runApp 之前 await 一次:只读本地缓存,毫秒级。
  ///
  /// 拆成两步是有意的 —— 冷启动**绝不能**卡在一个网络请求上。
  /// 第一帧用上次拉到的内容(没有就用本地默认值),网络刷新交给
  /// [refresh] 在后台跑,下次启动生效。
  static Future<void> loadCached() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final rawCopy = prefs.getString(_copyKey);
      if (rawCopy != null) {
        _copy = (jsonDecode(rawCopy) as Map).map(
            (k, v) => MapEntry(k as String, '$v'));
      }
      final rawFaq = prefs.getString(_faqKey);
      if (rawFaq != null) {
        _faq = (jsonDecode(rawFaq) as List)
            .map((e) => FaqItem.fromJson(e as Map<String, dynamic>))
            .toList();
      }
      _hidden = {...?prefs.getStringList(_hiddenKey)};
    } catch (_) {
      // 缓存坏了就当没有,下面的网络请求会重新灌
    }
  }

  /// 主动刷新(启动时调一次;设置页「检查更新」之类的地方也可以再调)。
  static Future<void> refresh(ApiClient api) async {
    try {
      final data = await api.platformConfig();
      final copy = (data['copy'] as Map?)
              ?.map((k, v) => MapEntry('$k', '$v')) ??
          const <String, String>{};
      final faq = ((data['faq'] as List?) ?? const [])
          .map((e) => FaqItem.fromJson(e as Map<String, dynamic>))
          .toList();
      rev = data['rev'] as String? ?? '';
      final licenses = data['licenses'];
      if (licenses is Map) avLicense = '${licenses['av'] ?? ''}'.trim();
      if (data['features'] is Map) {
        features = {
          for (final e in (data['features'] as Map).entries) '${e.key}': e.value == true,
        };
      }
      final prefs = await SharedPreferences.getInstance();
      // 显示 / 隐藏单独处理,不跟下面「空响应不覆盖」那条走:后台把藏起来的位置全部放出来时,hidden 就是空的,
      // 要是当成「空响应」跳过,客户端就一直藏着。老服务端没有这个字段 = 什么都没藏
      final hidden = {for (final k in (data['hidden'] as List? ?? const [])) '$k'};
      if (!setEquals(hidden, _hidden)) {
        _hidden = hidden;
        await prefs.setStringList(_hiddenKey, hidden.toList());
        changed.value++;
      }
      if (copy.isEmpty && faq.isEmpty) return; // 空响应不覆盖已有缓存
      final copyChanged = !mapEquals(copy, _copy);
      _copy = copy;
      _faq = faq;
      await prefs.setString(_copyKey, jsonEncode(copy));
      await prefs.setString(
          _faqKey, jsonEncode([for (final f in faq) f.toJson()]));
      if (copyChanged) changed.value++;
    } catch (_) {
      // 拉不到就用缓存/本地默认值,不打扰使用
    }
  }
}

/// 帮助中心一条问答
class FaqItem {
  const FaqItem(this.question, this.answer, {this.audience = 'user'});

  FaqItem.fromJson(Map<String, dynamic> json)
      : question = json['q'] as String? ?? '',
        answer = json['a'] as String? ?? '',
        audience = json['audience'] as String? ?? 'user';

  final String question;
  final String answer;
  final String audience;

  Map<String, dynamic> toJson() =>
      {'q': question, 'a': answer, 'audience': audience};
}
