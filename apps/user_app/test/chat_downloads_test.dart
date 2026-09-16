/// 「下载内容」的本机清单(chat/downloads.dart)。
///
/// 守的是:记一条就有一条、同一个文件再下一次不多占一行、超过上限新的挤掉旧的、
/// 重启之后还在(存进 SharedPreferences)、**删清单不等于删文件**。
///
/// 最后一条是这一份里最要紧的:清单删了还能再下一次,文件删了就没了 ——
/// 所以 Downloads.remove 只动清单,删文件是调用方另外一步(media_save.deleteDownloaded)。
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:user_app/chat/downloads.dart';
import 'package:user_app/chat/models.dart';

MediaInfo file(int id, {String name = '', String mime = 'application/pdf', int size = 1024}) =>
    MediaInfo(id: id, kind: 'file', name: name, mime: mime, size: size);

void main() {
  final d = Downloads.instance;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    d.resetForTest();
  });

  test('记一条就有一条,带上从哪个会话来', () async {
    await d.record(file(1, name: '合同.pdf', size: 2048), path: '/tmp/a.pdf', chatId: 9, chatTitle: '项目群');
    expect(d.items.length, 1);
    final it = d.items.first;
    expect(it.name, '合同.pdf');
    expect(it.size, 2048);
    expect(it.chatTitle, '项目群');
    expect(it.onThisDevice, isTrue);
  });

  test('网页版没有本机文件:path 空,onThisDevice 是 false', () async {
    await d.record(file(2, name: 'x.pdf'));
    expect(d.items.first.onThisDevice, isFalse);
  });

  test('没名字的按类型给一个说得出口的名字', () async {
    await d.record(const MediaInfo(id: 3, kind: 'photo'));
    expect(d.items.first.name, '图片');
  });

  test('同一个文件再下一次:不多占一行,而且排到最前面', () async {
    await d.record(file(1, name: 'a.pdf'));
    await d.record(file(2, name: 'b.pdf'));
    await d.record(file(1, name: 'a.pdf'), path: '/tmp/a.pdf');
    expect(d.items.length, 2);
    expect(d.items.first.mediaId, 1);
    expect(d.items.first.onThisDevice, isTrue, reason: '重下之后路径要更新');
  });

  test('删清单**不删文件**:remove 把那一行还给调用方,由它决定要不要删文件', () async {
    await d.record(file(7, name: 'c.pdf'), path: '/tmp/c.pdf');
    final gone = await d.remove(7);
    expect(d.items, isEmpty);
    expect(gone?.path, '/tmp/c.pdf', reason: '要删文件的话调用方得拿得到路径');
    expect(await d.remove(7), isNull, reason: '删第二次什么也不发生');
  });

  test('清空也是只清清单,把清掉的还回去', () async {
    await d.record(file(1), path: '/tmp/1');
    await d.record(file(2), path: '/tmp/2');
    final gone = await d.clear();
    expect(d.items, isEmpty);
    expect(gone.map((e) => e.path), containsAll(['/tmp/1', '/tmp/2']));
  });

  test('重启之后还在:写进了 SharedPreferences,读回来是同一条', () async {
    await d.record(file(5, name: '年报.pdf', size: 99), path: '/tmp/5', chatId: 3, chatTitle: '财务');
    final raw = SharedPreferences.getInstance();
    expect((await raw).getString('sz_chat_downloads'), isNotNull);

    d.resetForTest(); // 装作重启
    await d.load();
    expect(d.items.length, 1);
    expect(d.items.first.name, '年报.pdf');
    expect(d.items.first.chatTitle, '财务');
    expect(d.items.first.size, 99);
  });

  test('存坏了当没有,不炸', () async {
    SharedPreferences.setMockInitialValues({'sz_chat_downloads': '{不是个数组'});
    d.resetForTest();
    await d.load();
    expect(d.items, isEmpty);
  });

  test('超过上限:新的挤掉最旧的', () async {
    for (var i = 1; i <= 305; i++) {
      await d.record(file(i, name: 'f$i'));
    }
    expect(d.items.length, 300);
    expect(d.items.first.name, 'f305');
    expect(d.items.map((e) => e.name), isNot(contains('f1')));
  });

  test('存进去的是 JSON,字段名固定 —— 换版本读得回来', () async {
    await d.record(file(1, name: 'a.pdf'), path: '/tmp/a', chatId: 2, chatTitle: 'g');
    final sp = await SharedPreferences.getInstance();
    final list = jsonDecode(sp.getString('sz_chat_downloads')!) as List;
    expect((list.first as Map).keys,
        containsAll(['media_id', 'name', 'mime', 'size', 'kind', 'path', 'chat_id', 'chat_title', 'at']));
  });
}
