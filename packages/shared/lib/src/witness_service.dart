/// 手机见证节点:与 witness.py / 网页版完全相同的校验算法,跑在用户手机上。
///
/// "连电脑都不会"的群体也能参与监督——装了 App、打开账目透明页,
/// 手机就自动复算平台账本;愿意的话一键匿名上报,成为公开节点。
///
/// 诚实边界(页面上也要写):App 由平台分发,完全独立的核验请用
/// /nodes 的网页或脚本方式;开源后可自行编译对照。手机校验的价值在于:
/// 校验发生在用户自己的设备上、对着公开数据算,平台无法对单个用户造假。
library;

import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';

const _genesis =
    '0000000000000000000000000000000000000000000000000000000000000000';

/// 与服务端 canonical() 字节级一致:键排序、无空格、非 ASCII 原样
String canonicalJson(dynamic o) {
  if (o is Map) {
    final keys = o.keys.cast<String>().toList()..sort();
    return '{${keys.map((k) => '${jsonEncode(k)}:${canonicalJson(o[k])}').join(',')}}';
  }
  if (o is List) return '[${o.map(canonicalJson).join(',')}]';
  return jsonEncode(o);
}

String sha256Hex(String s) => sha256.convert(utf8.encode(s)).toString();

class WitnessResult {
  WitnessResult({
    required this.ok,
    required this.daysVerified,
    required this.verifiedDay,
    required this.verifiedHash,
    required this.problems,
  });

  final bool ok;
  final int daysVerified;
  final String verifiedDay;
  final String verifiedHash;
  final List<String> problems;
}

/// 三原则恒等式逐行核账(与 witness.py verify_rows 一致)
List<String> verifyRows(Map payload) {
  final problems = <String>[];
  final rate = (payload['commission_rate_max'] as num?) ?? 0.06;
  final vrate = (payload['voucher_rate'] as num?) ?? 0.03;
  for (final r in (payload['merchant_rows'] as List? ?? const [])) {
    final food = r['food'] as int, fee = r['commission'] as int;
    if (r['net'] != food - fee) problems.add('商家行 ${r['o']}: 净额恒等式不成立');
    if (fee.abs() > food.abs() * rate + 1) {
      problems.add('商家行 ${r['o']}: 佣金超过 ${(rate * 100).round()}%');
    }
  }
  for (final r in (payload['rider_rows'] as List? ?? const [])) {
    if (r['kind'] != 'earning' || (r['amount'] as int) < 0) {
      problems.add('骑手行 ${r['o']}: 配送费被冲减');
    }
  }
  for (final r in (payload['voucher_rows'] as List? ?? const [])) {
    final gross = r['gross'] as int;
    final expect = (gross * vrate).truncate();
    if (r['fee'] != expect || r['net'] != gross - (r['fee'] as int)) {
      problems.add('团购行 ${r['p']}: 服务费不是 ${(vrate * 100).round()}%');
    }
  }
  return problems;
}

class PhoneWitness {
  PhoneWitness(this.api);

  final ApiClient api;

  /// 跑一轮完整见证:比对本机留存的历史锚点 → 复算新增 → (若已开启)匿名上报。
  Future<WitnessResult> runCycle({bool heartbeat = false}) async {
    final prefs = await SharedPreferences.getInstance();
    final seen = (jsonDecode(prefs.getString('witness_seen') ?? '{}') as Map)
        .cast<String, String>();

    final anchors = <Map>[];
    var after = '';
    while (true) {
      final page = await api.ledgerAnchors(after: after);
      anchors.addAll(page);
      if (page.length < 400) break;
      after = page.last['day'] as String;
    }

    final current = {
      for (final a in anchors) a['day'] as String: a['chain_hash'] as String
    };
    final problems = <String>[
      for (final d in seen.keys)
        if (current.containsKey(d) && current[d] != seen[d]) '锚点被改: $d',
      for (final d in seen.keys)
        if (!current.containsKey(d)) '锚点消失: $d',
    ];

    var prev = _genesis;
    var verifiedDay = '', verifiedHash = '';
    for (final a in anchors) {
      final day = a['day'] as String;
      if (seen.containsKey(day) && problems.isEmpty) {
        prev = seen[day]!;
        verifiedDay = day;
        verifiedHash = prev;
        continue;
      }
      final detail = await api.ledgerDay(day);
      final ph = sha256Hex(canonicalJson(detail['payload']));
      final ch = sha256Hex(prev + ph);
      if (ph != detail['payload_hash'] || ch != a['chain_hash']) {
        problems.add('$day: 哈希链复算不一致');
        break;
      }
      problems.addAll(
          verifyRows(detail['payload'] as Map).map((p) => '$day: $p'));
      seen[day] = ch;
      prev = ch;
      verifiedDay = day;
      verifiedHash = ch;
      if (problems.length > 20) break;
    }
    await prefs.setString('witness_seen', jsonEncode(seen));

    final result = WitnessResult(
      ok: problems.isEmpty,
      daysVerified: seen.length,
      verifiedDay: verifiedDay,
      verifiedHash: verifiedHash,
      problems: problems,
    );
    if (heartbeat) await _heartbeat(prefs, result);
    return result;
  }

  /// 匿名心跳:只有随机节点 ID 与校验结论,不含任何账号/设备信息
  Future<void> _heartbeat(SharedPreferences prefs, WitnessResult r) async {
    var nodeId = prefs.getString('witness_node_id');
    if (nodeId == null) {
      nodeId = sha256Hex(
              '${DateTime.now().microsecondsSinceEpoch}-${identityHashCode(this)}')
          .substring(0, 32);
      await prefs.setString('witness_node_id', nodeId);
    }
    try {
      await api.nodeHeartbeat({
        'node_id': nodeId,
        'name': prefs.getString('witness_name') ?? '',
        'region': '手机节点',
        'version': 'app-0.4',
        'verified_day': r.verifiedDay,
        'chain_hash': r.verifiedHash,
        'ok': r.ok,
        'message': (() { final m = r.problems.join('; ');
          return m.length > 200 ? m.substring(0, 200) : m; })(),
      });
    } catch (_) {
      // 上报失败静默:本机核验结论不受影响
    }
  }

  static Future<bool> enabled() async =>
      (await SharedPreferences.getInstance()).getBool('witness_on') ?? false;

  static Future<void> setEnabled(bool on, {String name = ''}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('witness_on', on);
    if (name.isNotEmpty) await prefs.setString('witness_name', name);
  }
}
