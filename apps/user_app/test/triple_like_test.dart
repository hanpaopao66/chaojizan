import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/main.dart' show superZTheme;
import 'package:user_app/video/widgets/triple_like_button.dart';

/// 视频详情的点赞(设计稿 E 重画了那一排):点一下是赞;按住 1.5 秒是三连;没按够就松手什么也不发。
/// 用 tester 的手指按(触屏),不是鼠标 —— 长按在触屏和鼠标上走的是两条路。
void main() {
  Future<({List<String> calls})> pump(WidgetTester tester) async {
    final calls = <String>[];
    await tester.pumpWidget(MaterialApp(
      theme: superZTheme(Brightness.light),
      home: Scaffold(
        body: Center(
          child: TripleLikeButton(
            liked: false,
            count: 1832,
            onTap: () => calls.add('tap'),
            onTriple: () => calls.add('triple'),
          ),
        ),
      ),
    ));
    return (calls: calls);
  }

  testWidgets('点一下是赞', (tester) async {
    final r = await pump(tester);
    await tester.tap(find.byType(TripleLikeButton));
    await tester.pump(const Duration(milliseconds: 400));
    expect(r.calls, ['tap']);
    expect(find.text('1832'), findsOneWidget);
  });

  testWidgets('按住 1.5 秒转一圈 = 三连,只发一次', (tester) async {
    final r = await pump(tester);
    final g = await tester.startGesture(tester.getCenter(find.byType(TripleLikeButton)));
    await tester.pump(const Duration(milliseconds: 600)); // 过了长按判定(500ms),圈开始转
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(r.calls, isEmpty, reason: '还没按够 1.5 秒');
    await tester.pump(const Duration(milliseconds: 1500));
    await g.up();
    await tester.pump();
    expect(r.calls, ['triple']);
    expect(find.byType(CircularProgressIndicator), findsNothing, reason: '三连发出去之后圈收回去');
  });

  testWidgets('没按够就松手:圈退回去,什么也不发', (tester) async {
    final r = await pump(tester);
    final g = await tester.startGesture(tester.getCenter(find.byType(TripleLikeButton)));
    await tester.pump(const Duration(milliseconds: 700));
    await g.up();
    await tester.pump(const Duration(milliseconds: 1500));
    expect(r.calls, isEmpty);
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });
}
