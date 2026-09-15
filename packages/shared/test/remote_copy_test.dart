/// 可下发文案(RemoteCopy):显示 / 隐藏(0142)跟着服务端走,放出来的时候也要跟着放出来。
///
/// 防的是一个不报错的坑:文案那边有「空响应不覆盖缓存」的规矩,隐藏要是也照这条走,
/// 后台把藏着的位置全部放出来时 hidden 是空的 —— 会被当成空响应跳过,客户端就一直藏着。
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

ApiClient api(Map<String, dynamic> config) => ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async => http.Response(jsonEncode(config), 200,
          headers: {'content-type': 'application/json; charset=utf-8'})),
    );

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    RemoteCopy.debugSet(copy: {}, hidden: {});
  });

  test('藏了就不显示;后台全部放出来(hidden 为空)也要跟着放出来', () async {
    await RemoteCopy.refresh(api({'copy': {'nav.chat': '对话'}, 'hidden': ['nav.chat'], 'faq': []}));
    expect(RemoteCopy.shown('nav.chat'), isFalse);
    expect(RemoteCopy.text('nav.chat', '聊天'), '对话');
    await RemoteCopy.refresh(api({'copy': {}, 'hidden': [], 'faq': []}));
    expect(RemoteCopy.shown('nav.chat'), isTrue, reason: '空的 hidden 不是「空响应」,是「什么都没藏」');
  });

  test('老服务端没有 hidden 字段 = 什么都没藏;字段对不上的一律当显示', () async {
    RemoteCopy.debugSet(hidden: {'nav.video'});
    await RemoteCopy.refresh(api({'copy': {'x': 'y'}, 'faq': []}));
    expect(RemoteCopy.shown('nav.video'), isTrue);
    expect(RemoteCopy.shown('没登记的位置'), isTrue);
  });

  test('拉到变化才通知,没变化不通知(底部菜单听它重建)', () async {
    final before = RemoteCopy.changed.value;
    await RemoteCopy.refresh(api({'copy': {'a': '1'}, 'hidden': ['nav.video'], 'faq': []}));
    final after = RemoteCopy.changed.value;
    expect(after, greaterThan(before));
    await RemoteCopy.refresh(api({'copy': {'a': '1'}, 'hidden': ['nav.video'], 'faq': []}));
    expect(RemoteCopy.changed.value, after, reason: '内容一样就别让界面白白重建');
  });

  test('隐藏的位置会缓存:下次冷启动第一帧就是藏着的', () async {
    await RemoteCopy.refresh(api({'copy': {'a': '1'}, 'hidden': ['nav.chat'], 'faq': []}));
    RemoteCopy.debugSet(hidden: {});
    await RemoteCopy.loadCached();
    expect(RemoteCopy.shown('nav.chat'), isFalse);
  });
}
