import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// 本机模型:**地址和密钥只存在这台设备上**(#386)。
///
/// ## 为什么不上传
///
/// 平台不做大模型级别的机器人,所有接入都是用户级别的。本机这一档更彻底:
/// 模型跑在你自己的手机 / 电脑上,**我们连地址都不知道**。
///
/// 这不只是隐私上的讲究,也是安全上的:填 `127.0.0.1:11434` 这种地址,
/// 交给服务端去请求的话,服务端只会去探自己的内网 —— 那是 SSRF,不是接模型。
/// 所以这一档的请求必须由设备自己发。换手机就要重填,这是刻意的。
///
/// ## 只认 OpenAI 兼容的形状
///
/// `POST {base}/chat/completions`。Ollama、LM Studio、llama.cpp、vLLM 都提供这个,
/// 填一个地址就接上了。不为任何一家写专门的适配 —— 那是把自己绑在某一家上。
class LocalModel {
  const LocalModel({this.endpoint = '', this.model = '', this.apiKey = ''});

  final String endpoint;
  final String model;

  /// 本机跑的模型多半不需要。**存在这台设备上,任何时候都不往我们这儿传**
  final String apiKey;

  bool get ok => endpoint.isNotEmpty && model.isNotEmpty;

  static const _key = 'sz_ai_local_model';

  static Future<LocalModel> load() async {
    try {
      final sp = await SharedPreferences.getInstance();
      final raw = sp.getString(_key);
      if (raw == null || raw.isEmpty) return const LocalModel();
      final m = jsonDecode(raw) as Map<String, dynamic>;
      return LocalModel(
        endpoint: (m['endpoint'] as String? ?? '').trim(),
        model: (m['model'] as String? ?? '').trim(),
        apiKey: m['api_key'] as String? ?? '',
      );
    } catch (e) {
      debugPrint('读本机模型配置失败:$e');
      return const LocalModel();
    }
  }

  Future<void> save() async {
    final sp = await SharedPreferences.getInstance();
    await sp.setString(
        _key,
        jsonEncode({
          'endpoint': endpoint.trim(),
          'model': model.trim(),
          'api_key': apiKey,
        }));
  }

  static Future<void> clear() async {
    final sp = await SharedPreferences.getInstance();
    await sp.remove(_key);
  }

  LocalModel copyWith({String? endpoint, String? model, String? apiKey}) =>
      LocalModel(
        endpoint: endpoint ?? this.endpoint,
        model: model ?? this.model,
        apiKey: apiKey ?? this.apiKey,
      );

  /// 让本机模型答一段。**失败只回错误,不抛** —— 生成不出来不该把整个循环带倒。
  ///
  /// 超时给得比服务端那一档宽:手机上跑的小模型第一次加载权重要十几秒,
  /// 卡在那儿不是坏了。
  Future<({String text, String error})> complete(String prompt,
      {String system = '', Duration timeout = const Duration(seconds: 90)}) async {
    if (!ok) return (text: '', error: '还没填本机模型的地址和模型名');
    final base = endpoint.endsWith('/')
        ? endpoint.substring(0, endpoint.length - 1)
        : endpoint;
    try {
      final r = await http
          .post(
            Uri.parse('$base/chat/completions'),
            headers: {
              'content-type': 'application/json',
              if (apiKey.isNotEmpty) 'authorization': 'Bearer $apiKey',
            },
            body: jsonEncode({
              'model': model,
              'messages': [
                if (system.isNotEmpty) {'role': 'system', 'content': system},
                {'role': 'user', 'content': prompt},
              ],
              'max_tokens': 600,
              'temperature': 0.9,
            }),
          )
          .timeout(timeout);
      if (r.statusCode != 200) {
        // **错误体也按 UTF-8 解。** http 包的 `r.body` 在没有 charset 时按
        // latin1 解 —— 本地模型服务的中文报错会印成一串乱码,
        // 而那恰恰是人最需要看懂的那一句
        return (text: '', error: 'HTTP ${r.statusCode} ${_head(_utf8(r))}');
      }
      final data = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
      final choices = data['choices'] as List?;
      if (choices == null || choices.isEmpty) {
        return (text: '', error: '模型回的形状不对:${_head(r.body)}');
      }
      final text =
          ((choices.first as Map)['message'] as Map?)?['content'] as String?;
      final out = clean(text ?? '');
      return out.isEmpty
          ? (text: '', error: '模型回了空')
          : (text: out, error: '');
    } catch (e) {
      // 最常见的是「模型没起来」和「手机连不到那台电脑」,两句都要说得出来
      return (text: '', error: '$e');
    }
  }

  static String _head(String s) => s.length > 120 ? s.substring(0, 120) : s;

  static String _utf8(http.Response r) {
    try {
      return utf8.decode(r.bodyBytes);
    } catch (_) {
      return r.body;
    }
  }

  /// 模型爱加的那几样去掉:首尾引号、超长。**不做内容审核** ——
  /// 那是发布那一层的事(违禁词、先审后发都在服务端的原路径上)
  static String clean(String text, {int maxChars = 400}) {
    var t = text.trim();
    for (final pair in const [('“', '”'), ('"', '"'), ('「', '」')]) {
      if (t.length > 2 && t.startsWith(pair.$1) && t.endsWith(pair.$2)) {
        t = t.substring(1, t.length - 1).trim();
      }
    }
    return t.length > maxChars ? t.substring(0, maxChars) : t;
  }
}
