// 手机见证(witness_service.dart)按四个见证实现共用的用例核账:
// witness/testdata/verify_rows_cases.json(Python / Go / 网页跑的是同一份),口径分叉这里先红。
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 问题的种类:问题文本第一个空格前的那个词(合计类的问题整句没有空格,就是整句)
String _tagOf(String p) {
  final i = p.indexOf(' ');
  return i < 0 ? p : p.substring(0, i);
}

void main() {
  // flutter test 在包目录(packages/shared)里跑
  final doc = jsonDecode(
          File('../../witness/testdata/verify_rows_cases.json').readAsStringSync())
      as Map;
  final cases = (doc['cases'] as List).cast<Map>();
  final vectors = (doc['hash_vectors'] as List).cast<Map>();

  test('共用用例不是空的', () {
    expect(cases, isNotEmpty);
    expect(vectors, isNotEmpty);
  });

  for (final c in cases) {
    test('共用用例:${c['name']}', () {
      final problems = verifyRows(c['payload'] as Map);
      final got = problems.map(_tagOf).toList()..sort();
      final want = (c['expect'] as List).cast<String>().toList()..sort();
      expect(got, want, reason: problems.join('\n'));
    });
  }

  for (final v in vectors) {
    test('哈希向量:${v['name']}', () {
      final canon = canonicalJson(v['payload']);
      expect(canon, v['canonical']);
      final ph = sha256Hex(canon);
      expect(ph, v['payload_hash']);
      expect(sha256Hex('${v['prev']}$ph'), v['chain_hash']);
    });
  }

  test('平台纠错的式子和服务端同一个(干净的一天)', () {
    final clean = cases.firstWhere((c) => (c['name'] as String).startsWith('干净的一天'));
    final p = clean['payload'] as Map;
    expect(platformCorrection(p), (p['totals'] as Map)['platform_correction']);
  });
}
