import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:superz_shared/superz_shared.dart';

import 'local_model.dart';

/// 跑一轮的结果。给页面上那条「它刚才做了什么」用。
@immutable
class RunStep {
  const RunStep(this.at, this.text, {this.ok = true});

  final DateTime at;
  final String text;
  final bool ok;
}

/// 本机模型那一档的循环:**领活儿 → 本机生成 → 交回去**(#386)。
///
/// ## 三件事分别归谁
///
/// - **该不该说、回谁、节奏** —— 服务端。这几条是不变量,交给设备等于交给
///   「改一行客户端代码就能绕开」;
/// - **把提示词变成一句话** —— 这台设备。模型和密钥从不离开它;
/// - **发不发得出去**(违禁词、先审后发、禁言) —— 还是服务端,走和真人一样的路。
///
/// ## 为什么只在前台跑
///
/// iOS 不给普通 App 长期后台执行,安卓上后台跑本机大模型会把电吃光。
/// 与其做一个「看着在跑其实早被系统杀了」的后台任务,不如老实说清楚:
/// **这一页开着的时候它才说话。** 关掉就停,不骗人。
///
/// 服务端那边本来就按「距离上次够不够久」派活儿,所以断断续续地跑不影响节奏 ——
/// 它只是会把攒下的那件活儿在你下次打开时领走。
class BotRunner extends ChangeNotifier {
  BotRunner({required this.api, required this.botId});

  final ApiClient api;
  final int botId;

  /// 多久问一次服务端。服务端那边有 20 秒的地板,比它快没有意义
  static const poll = Duration(seconds: 30);

  /// 留几条给人看。这是「刚才发生了什么」,不是日志归档
  static const _maxSteps = 20;

  Timer? _timer;
  bool _busy = false;
  final List<RunStep> _steps = [];

  bool get running => _timer != null;
  bool get busy => _busy;
  List<RunStep> get steps => List.unmodifiable(_steps);

  void start() {
    if (_timer != null) return;
    _timer = Timer.periodic(poll, (_) => unawaited(tick()));
    _say('开始了。这一页开着的时候它才说话');
    notifyListeners();
    unawaited(tick());
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    _say('停了');
    notifyListeners();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _timer = null;
    super.dispose();
  }

  void _say(String text, {bool ok = true}) {
    _steps.insert(0, RunStep(DateTime.now(), text, ok: ok));
    if (_steps.length > _maxSteps) _steps.removeRange(_maxSteps, _steps.length);
    notifyListeners();
  }

  /// 跑一轮。**领不到活儿是最常见的结果**,那不是错误。
  Future<void> tick() async {
    if (_busy) return;
    _busy = true;
    notifyListeners();
    try {
      final task = await api.aiPullTask(botId);
      if (task == null) return; // 没到点。安静地什么都不做,不往那条清单里刷屏
      final kind = task['kind'] == 'reply' ? '回一条' : '发一条';
      _say('领到一件活儿:$kind');

      final cfg = await LocalModel.load();
      if (!cfg.ok) {
        _say('本机模型还没填地址 —— 这件活儿五分钟后过期,填好再来', ok: false);
        return;
      }
      final r = await cfg.complete(
        task['prompt'] as String? ?? '',
        system: task['system'] as String? ?? '',
      );
      if (r.text.isEmpty) {
        _say('本机模型没答上来:${r.error}', ok: false);
        return;
      }
      final out = await api.aiSubmitTask(
          botId, task['task_id'] as String, r.text);
      _say('发出去了:${out['text']}');
    } on ApiException catch (e) {
      // 409 = 这件活儿已经交过或过期了(重试、两台设备同时开着)。
      // 不是故障,下一轮会重新领
      _say(e.message, ok: false);
    } catch (e) {
      _say('$e', ok: false);
    } finally {
      _busy = false;
      notifyListeners();
    }
  }
}
