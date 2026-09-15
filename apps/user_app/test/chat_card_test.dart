/// 分享卡片消息(DEV-PROMPTS-41 §5.9):歌、歌单、专辑、音乐人、动态、视频分享进聊天。
///
/// 守的是:卡片里的字来自**服务端存下的快照**(客户端只发 `{type, id}`);
/// 会话列表那一行写得出是什么([歌曲] 晚风);服务端说这东西没了(unavailable)时不显示假标题、点不动。
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/chat/models.dart';
import 'package:user_app/chat/ui/format.dart';
import 'package:user_app/chat/ui/media_views.dart';
import 'package:user_app/main.dart' show superZTheme;

void main() {
  ChatMessage card(Map<String, dynamic> c) => ChatMessage.fromJson({
        'chat_id': 1,
        'seq': 9,
        'kind': 'card',
        'text': '',
        'created_at': '2026-09-15T01:00:00Z',
        'sender': {'id': 2, 'name': '小王'},
        'card': c,
      });

  const track = {
    'type': 'track',
    'id': 'mt1234567890',
    'title': '晚风',
    'subtitle': '某某 · 夏天的第一张',
    'cover': '',
    'url': 'https://chaojizan.cc/music/t/mt1234567890',
  };

  group('会话列表那一行', () {
    test('按分享的是什么写', () {
      expect(previewOf(card(track)), '[歌曲] 晚风');
      expect(previewOf(card({...track, 'type': 'playlist', 'title': '通勤路上'})), '[歌单] 通勤路上');
      expect(previewOf(card({...track, 'type': 'post', 'title': '今天的面很好吃'})), '[动态] 今天的面很好吃');
      expect(previewOf(card({...track, 'type': 'video', 'title': '做面'})), '[视频] 做面');
      expect(previewOf(card({...track, 'type': 'artist', 'title': '某某'})), '[音乐人] 某某');
      expect(previewOf(card({...track, 'type': 'release', 'title': '夏天的第一张'})), '[专辑] 夏天的第一张');
    });

    test('认不出的类型也不露馅:说「分享」,不写死成歌', () {
      expect(previewOf(card({'type': 'whatever', 'id': 'x', 'title': '某个东西'})), '[分享] 某个东西');
      expect(previewOf(card({'type': 'track', 'id': 'x'})), '[歌曲]');
    });

    test('kindLabels 里有 card,别的地方(引用、置顶条)也写得出', () {
      expect(kindLabels['card'], '分享');
    });
  });

  group('卡片本身', () {
    Future<void> pump(WidgetTester tester, Map<String, dynamic> c, {void Function(String)? onOpen}) async {
      await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: Scaffold(
          body: ShareCardView(
            card: c,
            fg: const Color(0xFF141413),
            accent: const Color(0xFFC15F3C),
            onOpen: onOpen ?? (_) {},
          ),
        ),
      ));
      await tester.pump();
    }

    testWidgets('画的是服务端给的快照:类型、标题、副标题', (tester) async {
      await pump(tester, track);
      expect(find.text('歌曲'), findsOneWidget);
      expect(find.text('晚风'), findsOneWidget);
      expect(find.text('某某 · 夏天的第一张'), findsOneWidget);
    });

    testWidgets('点一下按 url 走站内链接', (tester) async {
      final opened = <String>[];
      await pump(tester, track, onOpen: opened.add);
      await tester.tap(find.byType(InkWell));
      await tester.pump();
      expect(opened, ['https://chaojizan.cc/music/t/mt1234567890']);
    });

    testWidgets('东西没了(unavailable):说一声,点不动', (tester) async {
      final opened = <String>[];
      await pump(tester, {'type': 'post', 'id': 'fp1', 'unavailable': true, 'title': '不该显示'},
          onOpen: opened.add);
      expect(find.text('内容已不可见'), findsOneWidget);
      expect(find.text('不该显示'), findsNothing);
      await tester.tap(find.byType(InkWell));
      await tester.pump();
      expect(opened, isEmpty);
    });
  });
}
