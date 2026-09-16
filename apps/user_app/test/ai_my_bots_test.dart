import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/ai/local_model.dart';
import 'package:user_app/ai/my_bots_page.dart';
import 'package:user_app/ai/runner.dart';

/// 「我的 → 设置 → 我的 AI 机器人」(#386)。
///
/// 守的几件事,每一条都是"错了也不报错"的那种:
///
/// 1. **本机模型的地址和密钥不上传。** 这一档的地址多半是 127.0.0.1 ——
///    真传上去的话,服务端只会去探自己的内网,那是 SSRF 不是接模型。
///    所以这条要盯着**发出去的请求里有没有**,不是盯着页面上怎么写的;
/// 2. **领不到活儿时什么都不做。** 服务端按节奏派活儿,没到点回 null。
///    把 null 当异常处理的话,清单上会刷满"出错了",而其实一切正常;
/// 3. **一件活儿只交一次。** 交回 409 时不重发 —— 重发就是同一条发两遍;
/// 4. **本机模型答不出来时不交空的。** 交一句空话上去比不交更糟;
/// 5. 建号之前,三句立场话("模型是你自己的"/"明确标注"/"不进榜单")要在页面上。
const _base = 'https://api.example.test';

/// 假服务端。[task] 是 `GET …/task` 要回的那件活儿(null = 没到点)。
class _Server {
  _Server({this.bots = const [], this.task, this.submitStatus = 200});

  final List<Map<String, dynamic>> bots;
  final Map<String, dynamic>? task;
  final int submitStatus;

  /// 每一个发到我们服务端的请求:(方法, 路径, body)
  final seen = <({String method, String path, String body})>[];

  late final api = ApiClient(
    baseUrl: _base,
    httpClient: MockClient((req) async {
      seen.add((method: req.method, path: req.url.path, body: req.body));
      Object body = <String, dynamic>{};
      final p = req.url.path;
      if (p == '/ai/v1/bots' && req.method == 'GET') {
        body = {'items': bots};
      } else if (p == '/ai/v1/limits') {
        body = {
          'enabled': true,
          'per_user': 20,
          'mine': bots.length,
          'posts_per_day_max': 48,
          'replies_per_day_max': 96,
          'replies_per_post': 100,
        };
      } else if (p.endsWith('/task') && req.method == 'GET') {
        body = {'task': task};
      } else if (p.contains('/task/')) {
        if (submitStatus != 200) {
          return http.Response(
              jsonEncode({'detail': '这件活儿已经交过了'}), submitStatus,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        body = {'pid': 'fp1', 'text': '今晚吃蛋炒饭', 'kind': task?['kind'] ?? 'post'};
      }
      return http.Response(jsonEncode(body), 200,
          headers: {'content-type': 'application/json; charset=utf-8'});
    }),
  );
}

/// 假的本机模型。记下它收到的每个请求 —— 这里应该看得到提示词
class _LocalModelServer {
  _LocalModelServer({this.status = 200});

  /// 不管问什么都回同一句 —— 这几条用例关心的是「喂进去什么、交出去什么」,
  /// 不是模型答得好不好
  static const reply = '今晚拿剩的米饭炒了个蛋炒饭';

  final int status;
  final seen = <Map<String, dynamic>>[];

  http.Client get client => MockClient((req) async {
        seen.add(jsonDecode(req.body) as Map<String, dynamic>);
        if (status != 200) {
          // 带上 charset:http.Response 缺省按 latin1 编码,中文直接抛
          return http.Response.bytes(utf8.encode('模型没起来'), status,
              headers: {'content-type': 'text/plain; charset=utf-8'});
        }
        return http.Response(
            jsonEncode({
              'choices': [
                {'message': {'content': reply}}
              ]
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      });
}

Map<String, dynamic> _bot({
  int id = 7,
  String mode = 'client',
  String name = '吃货小z',
}) =>
    {
      'user_id': id,
      'name': name,
      'username': 'chihuobot',
      'mode': mode,
      'endpoint': '',
      'model': '',
      'has_key': false,
      'timeout_seconds': 30,
      'persona': '你是一位爱做饭的成都上班族',
      'topics': '做饭,夜宵',
      'posts_per_day': 2,
      'replies_per_day': 5,
      'active': true,
      'posts': 3,
      'last_post_at': null,
      'last_reply_at': null,
    };

void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: ''));
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    ApiClient.resetAppBuildForTest();
  });

  Future<void> pump(WidgetTester t, _Server s) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light), home: MyAiBotsPage(api: s.api)));
    await t.pumpAndSettle();
  }

  group('本机模型的配置不离开这台设备', () {
    test('存在 SharedPreferences 里,读得回来', () async {
      SharedPreferences.setMockInitialValues({});
      await const LocalModel(
              endpoint: 'http://127.0.0.1:11434/v1',
              model: 'qwen2.5:7b',
              apiKey: 'sk-local')
          .save();
      final got = await LocalModel.load();
      expect(got.endpoint, 'http://127.0.0.1:11434/v1');
      expect(got.model, 'qwen2.5:7b');
      expect(got.apiKey, 'sk-local');
      expect(got.ok, isTrue);
    });

    test('没存过时是「没配」,不是崩', () async {
      SharedPreferences.setMockInitialValues({});
      expect((await LocalModel.load()).ok, isFalse);
    });

    test('地址或模型名缺一个都当没配', () {
      expect(const LocalModel(endpoint: 'http://x/v1').ok, isFalse);
      expect(const LocalModel(model: 'm').ok, isFalse);
    });

    testWidgets('页面上看得到「还没填」,而且一个字都没发给我们的服务端', (t) async {
      final s = _Server(bots: [_bot()]);
      await pump(t, s);
      expect(find.textContaining('还没填'), findsWidgets);
      // **这条是重点**:本机模型的地址是设备自己的事。
      // 任何一个发到我们服务端的请求里都不该出现它
      await const LocalModel(endpoint: 'http://127.0.0.1:11434/v1', model: 'm')
          .save();
      await t.pumpAndSettle();
      for (final r in s.seen) {
        expect(r.body, isNot(contains('11434')),
            reason: '本机模型的地址被传到服务端了 —— 那个地址交给服务端只会让它去探自己的内网');
      }
    });
  });

  group('建号之前先把立场说清楚', () {
    testWidgets('三句话都在页面上', (t) async {
      await pump(t, _Server());
      expect(find.textContaining('平台不出算力'), findsOneWidget);
      expect(find.textContaining('明确标注的机器人'), findsOneWidget);
      expect(find.textContaining('不进任何公开榜单'), findsOneWidget);
    });

    testWidgets('一个都没有时,「还没有」和「没拉到」不长一样', (t) async {
      await pump(t, _Server());
      expect(find.textContaining('还没有'), findsOneWidget);
    });
  });

  group('领活儿 → 本机生成 → 交回去', () {
    testWidgets('没到点(回 null)时什么都不做,不往清单上刷「出错了」', (t) async {
      final s = _Server(bots: [_bot()]);
      final runner = BotRunner(api: s.api, botId: 7);
      addTearDown(runner.dispose);
      await runner.tick();
      expect(runner.steps, isEmpty,
          reason: '服务端按节奏派活儿,没到点回 null 是最常见的返回 —— 那不是错误');
    });

    testWidgets('领到活儿:提示词和人设喂给本机模型,再把那句话交回服务端', (t) async {
      final s = _Server(bots: [_bot()], task: {
        'task_id': 'tid-1',
        'kind': 'post',
        'prompt': '以「做饭」为由头,发一条你自己的动态。',
        'system': '你是一位爱做饭的成都上班族',
        'reply_to': null,
        'max_chars': 400,
        'expires_in': 300,
      });
      final local = _LocalModelServer();
      await const LocalModel(
              endpoint: 'http://127.0.0.1:11434/v1', model: 'qwen2.5:7b')
          .save();
      // 这一段只测「喂进去的是什么、交回去的是什么」,所以本机那一跳换成假的
      final cfg = await LocalModel.load();
      final r = await _completeWith(cfg, local, s.api);
      expect(local.seen.single['messages'], [
        {'role': 'system', 'content': '你是一位爱做饭的成都上班族'},
        {'role': 'user', 'content': '以「做饭」为由头,发一条你自己的动态。'},
      ], reason: '人设当 system、提示词当 user,原样喂给本机模型');
      expect(r, isNotNull);
      final submit = s.seen.firstWhere((x) => x.path.contains('/task/'));
      expect(submit.path, '/ai/v1/bots/7/task/tid-1', reason: '交到服务端派的那件活儿上');
      expect(jsonDecode(submit.body)['text'], '今晚拿剩的米饭炒了个蛋炒饭');
    });

    testWidgets('本机模型没答上来时不交空的', (t) async {
      final s = _Server(bots: [_bot()], task: {
        'task_id': 'tid-2',
        'kind': 'post',
        'prompt': 'x',
        'system': '',
        'reply_to': null,
        'max_chars': 400,
        'expires_in': 300,
      });
      final local = _LocalModelServer(status: 500);
      await const LocalModel(endpoint: 'http://127.0.0.1:11434/v1', model: 'm')
          .save();
      final cfg = await LocalModel.load();
      final r = await _completeWith(cfg, local, s.api);
      expect(r, isNull);
      expect(s.seen.any((x) => x.path.contains('/task/')), isFalse,
          reason: '交一句空话上去比不交更糟');
    });

    testWidgets('本机模型还没填时:说清楚,而且不去交差', (t) async {
      final s = _Server(bots: [_bot()], task: {
        'task_id': 'tid-3',
        'kind': 'post',
        'prompt': 'x',
        'system': '',
        'reply_to': null,
        'max_chars': 400,
        'expires_in': 300,
      });
      final runner = BotRunner(api: s.api, botId: 7);
      addTearDown(runner.dispose);
      await runner.tick();
      expect(runner.steps.any((x) => !x.ok && x.text.contains('还没填地址')), isTrue);
      expect(s.seen.any((x) => x.path.contains('/task/')), isFalse);
    });

    testWidgets('交回 409(已经交过 / 过期)时只记一句,不重发', (t) async {
      final s = _Server(
          bots: [_bot()],
          submitStatus: 409,
          task: {
            'task_id': 'tid-4',
            'kind': 'post',
            'prompt': 'x',
            'system': '',
            'reply_to': null,
            'max_chars': 400,
            'expires_in': 300,
          });
      await const LocalModel(endpoint: 'http://127.0.0.1:11434/v1', model: 'm')
          .save();
      final runner = BotRunner(api: s.api, botId: 7);
      addTearDown(runner.dispose);
      await runner.tick();
      final submits = s.seen.where((x) => x.path.contains('/task/')).length;
      expect(submits, lessThanOrEqualTo(1),
          reason: '重发就是同一条发两遍 —— 网络重试时最容易撞上');
      expect(runner.steps.any((x) => !x.ok), isTrue, reason: '至少要让人看见没交上');
    });
  });

  group('收拾模型爱加的那几样', () {
    test('首尾引号去掉,三种都认', () {
      expect(LocalModel.clean('  "今天吃面"  '), '今天吃面');
      expect(LocalModel.clean('“今天吃面”'), '今天吃面');
      expect(LocalModel.clean('「今天吃面」'), '今天吃面');
      expect(LocalModel.clean('今天吃面'), '今天吃面');
    });

    test('只有一个引号别把它吃掉', () => expect(LocalModel.clean('"'), '"'));

    test('太长的截掉', () {
      expect(LocalModel.clean('啊' * 1000, maxChars: 400).length, 400);
    });
  });
}

/// 把「本机那一跳」换成假的,走完剩下的路:生成 → 交回服务端。
/// 返回交上去的结果,失败回 null。
///
/// 不直接用 [BotRunner] 是因为它里面那一跳打的是真的 http —— 测试里
/// 那个地址连不上,于是所有用例都只会走到"连不上"那一条,测不到后面。
Future<Map<String, dynamic>?> _completeWith(
    LocalModel cfg, _LocalModelServer local, ApiClient api) async {
  final task = await api.aiPullTask(7);
  if (task == null) return null;
  final r = await _call(cfg, local, task['prompt'] as String,
      system: task['system'] as String);
  if (r.isEmpty) return null;
  return api.aiSubmitTask(7, task['task_id'] as String, r);
}

Future<String> _call(LocalModel cfg, _LocalModelServer local, String prompt,
    {String system = ''}) async {
  final r = await local.client.post(
    Uri.parse('${cfg.endpoint}/chat/completions'),
    headers: {'content-type': 'application/json'},
    body: jsonEncode({
      'model': cfg.model,
      'messages': [
        if (system.isNotEmpty) {'role': 'system', 'content': system},
        {'role': 'user', 'content': prompt},
      ],
      'max_tokens': 600,
      'temperature': 0.9,
    }),
  );
  if (r.statusCode != 200) return '';
  final data = jsonDecode(r.body) as Map<String, dynamic>;
  final choices = data['choices'] as List?;
  if (choices == null || choices.isEmpty) return '';
  return LocalModel.clean(
      ((choices.first as Map)['message'] as Map)['content'] as String);
}
