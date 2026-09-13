import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/main.dart' show superZTheme;
import 'package:user_app/video/comments/comments_view.dart' show showCommentInput;
import 'package:user_app/video/me/common.dart' show vPrompt;

/// 弹层里的输入框控制器不能在 pop 回来之后马上销毁(安卓走查 #376:发评论整屏红)。
///
/// pop 那一刻 future 就回来了,弹层还在退场动画里、输入框还挂着;手机上键盘同时在收,
/// viewInsets 一变弹层就重建,输入框重建时去用已经销毁的控制器 ——
/// 「A TextEditingController was used after being disposed」,接着一串 `_dependents.isEmpty`。
/// 网页上没有软键盘收起这一步,测不出来。这里用 tester.view.viewInsets 模拟键盘收起。
void main() {
  Future<void> openThenSubmitWhileKeyboardCloses(
    WidgetTester tester, {
    required Future<String?> Function(BuildContext context) open,
    required String submitLabel,
  }) async {
    tester.view.physicalSize = const Size(400, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    String? got;
    await tester.pumpWidget(MaterialApp(
      theme: superZTheme(Brightness.light),
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: TextButton(onPressed: () async => got = await open(context), child: const Text('打开')),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    // 键盘弹起来了
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    await tester.pump();
    await tester.enterText(find.byType(TextField), '周六见');
    await tester.tap(find.text(submitLabel));
    // pop 之后:代码里的 await 回来了,弹层还在退场;这时键盘收起
    await tester.pump();
    tester.view.viewInsets = FakeViewPadding.zero;
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 16));
    }
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(got, '周六见');
  }

  testWidgets('评论输入弹层:点「发布」时键盘在收,不能用到已经销毁的控制器', (tester) async {
    await openThenSubmitWhileKeyboardCloses(tester,
        open: (context) => showCommentInput(context), submitLabel: '发布');
  });

  testWidgets('一行文字的对话框(改名、申诉理由)同理', (tester) async {
    await openThenSubmitWhileKeyboardCloses(tester,
        open: (context) => vPrompt(context, title: '改名'), submitLabel: '确定');
  });
}
