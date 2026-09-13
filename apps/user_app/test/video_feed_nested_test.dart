import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/main.dart' show superZTheme;
import 'package:user_app/video/models.dart';
import 'package:user_app/video/widgets/feed.dart';

/// 空间页的「投稿」是嵌在 NestedScrollView 里的卡片流(安卓走查 #376)。
/// 原来卡片流挂着自己的滚动控制器,外层协调不了:往上滑列表,头部(头像、关注 / 粉丝)一直占着上半屏,
/// 列表只能在下面那一截里滚。现在 nested: true 时把滚动交给外层,头部跟着收起;翻页改成听滚动通知。
void main() {
  final loaded = <int>[];
  Future<void> pumpNested(WidgetTester tester, {required bool nested}) async {
    loaded.clear();
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      theme: superZTheme(Brightness.light),
      home: Scaffold(
        body: NestedScrollView(
          headerSliverBuilder: (_, __) => [
            const SliverToBoxAdapter(child: SizedBox(height: 300, child: Center(child: Text('空间头部')))),
          ],
          body: VideoFeed(
            nested: nested,
            load: (page, cursor) async {
              loaded.add(page);
              return VPage([
                for (var i = 0; i < 10; i++) VideoCard(vid: 'p${page}v$i', title: '第 $page 页第 $i 个'),
              ], hasMore: page < 3);
            },
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('嵌在 NestedScrollView 里:往上滑列表,头部跟着收起', (tester) async {
    await pumpNested(tester, nested: true);
    final before = tester.getTopLeft(find.text('空间头部')).dy;
    await tester.drag(find.text('第 0 页第 2 个'), const Offset(0, -250));
    await tester.pumpAndSettle();
    final after = tester.getTopLeft(find.text('空间头部')).dy;
    expect(before - after, greaterThan(200), reason: '头部没跟着上去:$before → $after');
  });

  testWidgets('滑到快见底时自动拿下一页', (tester) async {
    await pumpNested(tester, nested: true);
    final first = loaded.length; // 首屏离底不到 600 时会顺手补一页
    for (var i = 0; i < 12; i++) {
      await tester.drag(find.byType(CustomScrollView), const Offset(0, -500));
      await tester.pumpAndSettle();
    }
    expect(loaded.length, greaterThan(first), reason: '往下滑没有翻页:$loaded');
    expect(loaded, [0, 1, 2, 3], reason: '四页都该拿到(第 3 页之后没有了),不重复不跳页');
  });
}
