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

/// 判骑手责任的骑手行(规格 §6.2b):**不在 rider_rows 里**,单独放在 rider_fault_rows。
/// 冲回这单收入、池子不够骑手另出的是负数,申诉改判退回的是正数
const _riderFaultSigns = {'fault_reversal': -1, 'fault_charge': -1, 'fault_refund': 1};

/// 判商家责任的商家行(规格 §6.2c):**不在 merchant_rows 里**,单独放在 merchant_fault_rows。
/// 骑手那份配送费和小费商家另出的是负数,申诉改判退回的是正数
const _merchantFaultSigns = {'fault_charge': -1, 'fault_refund': 1};

List<Map> _rows(dynamic v) => (v as List? ?? const []).whereType<Map>().toList();

/// 逐行加总某个字段;[kind] 给了就只加这一种
num _sum(dynamic rows, String field, [String? kind]) => _rows(rows)
    .where((r) => kind == null || r['kind'] == kind)
    .fold<num>(0, (s, r) => s + (r[field] as num));

/// 平台这一天为纠错(申诉改判成立)出的钱,规格 §6.5:商家改判补回的净额(merchant_rows 里的
/// adjustment)+ 退回商家另出的那行 + 退回骑手的 + 顾客改判平台退的
num platformCorrection(Map p) =>
    _sum(p['merchant_rows'], 'net', 'adjustment') +
    _sum(p['merchant_fault_rows'], 'amount', 'fault_refund') +
    _sum(p['rider_fault_rows'], 'amount', 'fault_refund') +
    _sum(p['appeal_refund_rows'], 'amount');

/// 三原则恒等式逐行核账(与 witness.py verify_rows 一致;四个见证实现跑同一份用例
/// witness/testdata/verify_rows_cases.json,见 test/witness_verify_test.dart)
List<String> verifyRows(Map payload) {
  final problems = <String>[];
  final rate = (payload['commission_rate_max'] as num?) ?? 0.06;
  final vrate = (payload['voucher_rate'] as num?) ?? 0.03;
  final srate = (payload['stay_rate'] as num?) ?? 0.05;
  for (final r in _rows(payload['merchant_rows'])) {
    final food = r['food'] as num, fee = r['commission'] as num;
    if (r['net'] != food - fee) problems.add('商家行 ${r['o']}: 净额恒等式不成立');
    if (fee.abs() > food.abs() * rate + 1) {
      problems.add('商家行 ${r['o']}: 佣金超过 ${(rate * 100).round()}%');
    }
  }
  // 「只进不冲」的实质是骑手的钱只增不减:负数即违规,不管挂什么 kind;
  // kind 走白名单(earning / adjustment),将来多出一种会扣钱的立刻拦住
  for (final r in _rows(payload['rider_rows'])) {
    if ((r['amount'] as num) < 0) {
      problems.add('骑手行 ${r['o']}: 配送费被冲回(${r['kind']})');
    } else if (r['kind'] != 'earning' && r['kind'] != 'adjustment') {
      problems.add('骑手行 ${r['o']}: 未知入账类型 ${r['kind']}');
    }
  }
  for (final r in _rows(payload['voucher_rows'])) {
    final gross = r['gross'] as num;
    final expect = (gross * vrate).truncate();
    if (r['fee'] != expect || r['net'] != gross - (r['fee'] as num)) {
      problems.add('团购行 ${r['p']}: 服务费不是 ${(vrate * 100).round()}%');
    }
  }
  for (final r in _rows(payload['stay_rows'])) {
    final gross = r['gross'] as num, fee = r['fee'] as num, net = r['net'] as num;
    if (r['kind'] == 'settle') {
      // 离店结算:净额恒等 + 佣金不超上限(±1 分取整)
      if (net != gross - fee) problems.add('住宿行 ${r['s']}: 净额恒等式不成立');
      if (fee > gross * srate + 1) {
        problems.add('住宿行 ${r['s']}: 佣金超过 ${(srate * 100).round()}%');
      }
    } else if (r['kind'] == 'penalty') {
      // 到店无房违约金:商家负行赔给用户,平台分文不取;赔付不超房费
      if (fee != 0 || !(-gross <= net && net < 0)) {
        problems.add('住宿行 ${r['s']}: 违约金行越界');
      }
    } else {
      // 取消扣款/未入住:平台分文不取,商家所得不超过房费
      if (fee != 0) problems.add('住宿行 ${r['s']}: 取消/未入住不应产生佣金');
      if (!(0 <= net && net <= gross)) problems.add('住宿行 ${r['s']}: 扣款超出房费');
    }
  }
  // 判骑手责任(§6.2b)、判商家责任(§6.2c):种类在白名单里、符号对。缺这些字段的老锚点跳过
  for (final (key, signs, label) in [
    ('rider_fault_rows', _riderFaultSigns, '骑手判责行'),
    ('merchant_fault_rows', _merchantFaultSigns, '商家判责行'),
  ]) {
    for (final r in _rows(payload[key])) {
      final sign = signs[r['kind']];
      if (sign == null) {
        problems.add('$label ${r['o']}: 未知类型 ${r['kind']}');
      } else if ((r['amount'] as num) * sign < 0) {
        problems.add('$label ${r['o']}: ${r['kind']} 的金额 ${r['amount']} 符号不对');
      }
    }
  }
  for (final r in _rows((payload['rider_fund'] as Map?)?['rows'])) {
    if ((r['kind'] != 'payout' && r['kind'] != 'return') || (r['amount'] as num) <= 0) {
      problems.add('保障金池行 ${r['o']}: ${r['kind']} ${r['amount']} —— '
          '只应有正数的支出(payout)和回池(return)');
    }
  }
  // 顾客申诉改判、平台原路退回的钱(§6.2d):只应是正数
  for (final r in _rows(payload['appeal_refund_rows'])) {
    if ((r['amount'] as num) <= 0) {
      problems.add('申诉改判退款行 ${r['o']}: 金额 ${r['amount']} 不是正数');
    }
  }
  // 合计交叉校验(§6.5)。骑手合计是必核的(缺了也算对不上),其余字段存在才核
  final t = payload['totals'] as Map? ?? const {};
  if (t.isNotEmpty) {
    if (t['rider_amount'] != _sum(payload['rider_rows'], 'amount')) {
      problems.add('骑手合计与逐行加总不一致');
    }
    for (final (key, want, msg) in [
      ('stay_fee', _sum(payload['stay_rows'], 'fee'), '住宿服务费合计与逐行加总不一致'),
      ('rider_fault', _sum(payload['rider_fault_rows'], 'amount'), '骑手判责合计与逐行加总不一致'),
      ('merchant_fault', _sum(payload['merchant_fault_rows'], 'amount'), '商家判责合计与逐行加总不一致'),
      ('appeal_refund', _sum(payload['appeal_refund_rows'], 'amount'), '申诉改判退款合计与逐行加总不一致'),
      ('platform_correction', platformCorrection(payload), '平台纠错(申诉改判)合计与逐行加总不一致'),
    ]) {
      if (t.containsKey(key) && t[key] != want) problems.add(msg);
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
        'version': 'app-0.5',
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
