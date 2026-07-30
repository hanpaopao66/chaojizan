import 'dart:convert';

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

  static Map<String, String> _copy = const {};
  static List<FaqItem> _faq = const [];

  /// 内容版本号(服务端算的内容哈希),便于排查"我改了怎么没生效"
  static String rev = '';

  /// 取一条文案。[fallback] 是客户端自带的完整默认值,不能省。
  static String text(String key, String fallback) => _copy[key] ?? fallback;

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
      if (copy.isEmpty && faq.isEmpty) return; // 空响应不覆盖已有缓存
      _copy = copy;
      _faq = faq;
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_copyKey, jsonEncode(copy));
      await prefs.setString(
          _faqKey, jsonEncode([for (final f in faq) f.toJson()]));
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
