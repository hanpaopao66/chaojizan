/// 分享面板上的「发到消息 / 发到动态」(DEV-PROMPTS-41 §5.9、#382 打通)。
///
/// 守的是两件事:
/// 1. 歌、专辑、歌单、音乐人、视频都能发成**卡片**(客户端只报 {type, id}),
///    不是以前那条「标题 + 链接」的纯文本 —— 这一步是 shareCardToChat;
/// 2. 「发到动态」只在论坛那一格开着的时候露。论坛关掉时给了入口,用户写完一条
///    帖子才被 503 顶回来,比没有这个入口更糟。
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/channel_config.dart';
import 'package:user_app/main.dart' show superZTheme;
import 'package:user_app/music/nav.dart' show shareMusic;
import 'package:user_app/video/models.dart' show VideoCard;
import 'package:user_app/video/widgets/share.dart' show shareVideo;

void main() {
  tearDown(ChannelConfig.resetForTest);

  /// 摆一个按钮,点一下就开分享面板 —— 面板要有 Navigator 和 ScaffoldMessenger
  Future<void> pumpShare(WidgetTester tester, Future<void> Function(BuildContext) share) async {
    await tester.pumpWidget(MaterialApp(
      theme: superZTheme(Brightness.light),
      home: Scaffold(
        body: Builder(builder: (ctx) => TextButton(onPressed: () => share(ctx), child: const Text('分享'))),
      ),
    ));
    await tester.tap(find.text('分享'));
    await tester.pumpAndSettle();
  }

  group('音乐', () {
    testWidgets('论坛开着:四条路都在', (tester) async {
      ChannelConfig.setForTest(['food', 'music', 'forum']);
      await pumpShare(tester, (ctx) => shareMusic(ctx, 'track', 'mt3kQ9', '晚风'));

      expect(find.text('晚风'), findsOneWidget);
      expect(find.text('发到消息'), findsOneWidget);
      expect(find.text('发到动态'), findsOneWidget);
      expect(find.text('复制链接'), findsOneWidget);
      expect(find.text('更多'), findsOneWidget);
    });

    testWidgets('论坛没开:没有「发到动态」这一条', (tester) async {
      ChannelConfig.setForTest(['food', 'music']);
      await pumpShare(tester, (ctx) => shareMusic(ctx, 'track', 'mt3kQ9', '晚风'));

      expect(find.text('发到消息'), findsOneWidget);
      expect(find.text('发到动态'), findsNothing);
    });

    testWidgets('点「发到消息」:走的是卡片那条路(没登录就先说要登录)', (tester) async {
      ChannelConfig.setForTest(['music']);
      await pumpShare(tester, (ctx) => shareMusic(ctx, 'track', 'mt3kQ9', '晚风'));

      await tester.tap(find.text('发到消息'));
      await tester.pumpAndSettle();

      expect(find.text('先登录才能分享到聊天'), findsOneWidget);
    });
  });

  group('视频', () {
    testWidgets('论坛开着:多一条「发到动态」', (tester) async {
      ChannelConfig.setForTest(['forum']);
      await pumpShare(tester, (ctx) => shareVideo(ctx, VideoCard(vid: 'v9', title: '一条视频')));

      expect(find.text('一条视频'), findsOneWidget);
      expect(find.text('发到消息'), findsOneWidget);
      expect(find.text('发到动态'), findsOneWidget);
    });

    testWidgets('论坛没开:只剩发到消息、复制链接、更多', (tester) async {
      ChannelConfig.setForTest(['food']);
      await pumpShare(tester, (ctx) => shareVideo(ctx, VideoCard(vid: 'v9', title: '一条视频')));

      expect(find.text('发到消息'), findsOneWidget);
      expect(find.text('发到动态'), findsNothing);
      expect(find.text('复制链接'), findsOneWidget);
    });
  });
}
