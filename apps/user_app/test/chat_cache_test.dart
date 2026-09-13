import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/chat/models.dart';
import 'package:user_app/chat/store.dart' show messageToCache;
import 'package:user_app/chat/ui/format.dart' show previewOf;

/// 会话列表的离线缓存(安卓走查 #376 撞到):离线打开「消息」时,每个会话那一行预览
/// 要和在线时一模一样。原来缓存少存了字段 —— 剧透的字离线时直接露出来,
/// 通话显示成「[通话]」,语音显示成「[语音] 0:00」。
void main() {
  ChatMessage msg(Map<String, dynamic> over) => ChatMessage.fromJson({
        'chat_id': 1,
        'seq': 9,
        'kind': 'text',
        'text': '',
        'created_at': '2026-09-13T01:00:00Z',
        'sender': {'id': 2, 'name': '小王'},
        ...over,
      });

  ChatMessage roundTrip(ChatMessage m) => ChatMessage.fromJson(jsonDecode(jsonEncode(messageToCache(m))));

  final spoiler = msg({
    'text': '明天 8 点见,谜底是西瓜',
    'entities': [
      {'type': 'bold', 'offset': 0, 'length': 2},
      {'type': 'spoiler', 'offset': 11, 'length': 2}, // 「西瓜」
    ],
  });

  test('缓存往返之后,一行预览和在线时一模一样', () {
    final samples = <ChatMessage>[
      spoiler,
      msg({'text': '第一行\n第二行'}),
      msg({'kind': 'call', 'call': {'video': false, 'state': 'ended', 'duration': 31}}),
      msg({'kind': 'call', 'call': {'video': true, 'state': 'missed'}}),
      msg({
        'kind': 'voice',
        'media': [
          {'id': 5, 'kind': 'voice', 'name': 'v.m4a', 'duration_ms': 3200},
        ],
      }),
      msg({
        'kind': 'file',
        'media': [
          {'id': 6, 'kind': 'file', 'name': '菜单.pdf'},
        ],
      }),
      msg({
        'kind': 'photo',
        'text': '看这个',
        'media': [
          {'id': 7, 'kind': 'photo', 'name': 'a.jpg'},
        ],
      }),
      msg({
        'kind': 'poll',
        'poll': {
          'id': 3,
          'question': '周六几点集合?',
          'options': [
            {'text': '12点', 'voters': 0},
            {'text': '18点', 'voters': 2},
          ],
        },
      }),
      msg({'kind': 'dice', 'dice': {'emoji': '🎯', 'value': 6}}),
      msg({'kind': 'sticker', 'sticker': {'emoji': '😂', 'id': 9, 'url': '/stickers/9.webp'}}),
      msg({'kind': 'location', 'location': {'title': '梓潼正成·财富ID', 'lat': 30.66, 'lng': 104.05}}),
      msg({'kind': 'contact', 'contact': {'name': '用户5526', 'user_id': 17569}}),
    ];
    for (final m in samples) {
      expect(previewOf(roundTrip(m)), previewOf(m), reason: '${m.kind}:${m.text}');
    }
  });

  test('剧透的字离线时也打码', () {
    final offline = previewOf(roundTrip(spoiler));
    expect(offline, isNot(contains('西瓜')));
    expect(offline, '明天 8 点见,谜底是▒▒');
  });

  test('通话和语音离线时说得出时长', () {
    expect(previewOf(roundTrip(msg({'kind': 'call', 'call': {'video': false, 'state': 'ended', 'duration': 31}}))),
        isNot('[通话]'));
    final voice = roundTrip(msg({
      'kind': 'voice',
      'media': [
        {'id': 5, 'kind': 'voice', 'name': 'v.m4a', 'duration_ms': 3200},
      ],
    }));
    expect(previewOf(voice), '[语音] 0:03');
  });
}
