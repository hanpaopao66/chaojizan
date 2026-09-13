import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:user_app/chat/models.dart';
import 'package:user_app/chat/ui/composer.dart';
import 'package:user_app/main.dart' show superZTheme;

/// 输入栏的两个长按(安卓走查 #376 撞到的):发送按钮长按出「静音发送 / 定时发送」,麦克风按住说话。
///
/// 原来两处都是外层 GestureDetector 管长按、里层带文字提示(Tooltip)。提示在触屏上也吃长按,
/// 手势竞技场里里层先到点,外层永远轮不到 —— 手机上菜单出不来、录音开始不了;
/// 网页上用鼠标测不出来(提示对鼠标只管悬停)。这里用的是 tester 默认的触屏手指。
void main() {
  ComposerActions actions() => ComposerActions(
        onSendText: (text, entities, {silent = false}) async {},
        onSendAttachments: (files, caption, entities) async {},
        onSendVoice: (voice) async {},
        onSaveEdit: (m, text, entities) async {},
        onPickLocation: () async {},
        onPickContact: () async {},
        onCreatePoll: () async {},
        onDice: (emoji) async {},
        onSchedule: (text, entities) async {},
        onSendSticker: (sticker) async {},
      );

  Future<void> pumpComposer(WidgetTester tester, {required bool media}) async {
    final chat = ChatInfo.fromJson({
      'id': 1,
      'type': 'group',
      'title': '测试群',
      'perms': {'send_messages': true, 'send_media': media, 'send_stickers': true, 'send_polls': true},
    });
    await tester.pumpWidget(MaterialApp(
      theme: superZTheme(Brightness.light),
      home: Scaffold(
        body: Column(children: [
          const Spacer(),
          Composer(
            chat: chat,
            actions: actions(),
            replyTo: null,
            editing: null,
            onCancelReply: () {},
            onCancelEdit: () {},
          ),
        ]),
      ),
    ));
  }

  testWidgets('手指长按发送按钮:出「静音发送 / 定时发送」', (tester) async {
    await pumpComposer(tester, media: true);
    await tester.enterText(find.byType(TextField), '周六见');
    await tester.pump();
    await tester.longPress(find.byKey(const ValueKey('send')));
    await tester.pumpAndSettle();
    expect(find.text('定时发送'), findsOneWidget, reason: '长按被文字提示吃掉了');
    expect(find.text('静音发送'), findsOneWidget);
  });

  testWidgets('手指按住麦克风:长按到了录音的入口(没权限时说「这里不能发语音」)', (tester) async {
    // 用一个关了发媒体的群:录音入口第一步就判权限并提示,不会去碰录音插件
    await pumpComposer(tester, media: false);
    await tester.longPress(find.byKey(const ValueKey('mic')));
    await tester.pump();
    expect(find.text('这里不能发语音'), findsOneWidget, reason: '按住被文字提示吃掉了,录音入口没被调用');
  });

  testWidgets('表情面板开着时按系统返回键:先收面板,页面还在;再按一次才退出', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final chat = ChatInfo.fromJson({
      'id': 1,
      'type': 'group',
      'title': '测试群',
      'perms': {'send_messages': true, 'send_media': true, 'send_stickers': true, 'send_polls': true},
    });
    await tester.pumpWidget(MaterialApp(
      theme: superZTheme(Brightness.light),
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: TextButton(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
                builder: (_) => Scaffold(
                  body: Column(children: [
                    const Spacer(),
                    Composer(
                      chat: chat,
                      actions: actions(),
                      replyTo: null,
                      editing: null,
                      onCancelReply: () {},
                      onCancelEdit: () {},
                    ),
                  ]),
                ),
              )),
              child: const Text('进聊天'),
            ),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('进聊天'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('表情'));
    await tester.pump();
    expect(find.byTooltip('键盘'), findsOneWidget, reason: '表情面板没打开');

    await tester.binding.handlePopRoute(); // 安卓的系统返回键
    await tester.pumpAndSettle();
    expect(find.byType(Composer), findsOneWidget, reason: '返回键直接退出了聊天,面板没先收起来');
    expect(find.byTooltip('表情'), findsOneWidget, reason: '面板还开着');

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.byType(Composer), findsNothing, reason: '面板收起之后,返回键应当退出聊天');
  });

  testWidgets('点一下麦克风:说怎么用', (tester) async {
    await pumpComposer(tester, media: true);
    await tester.tap(find.byKey(const ValueKey('mic')));
    await tester.pump();
    expect(find.textContaining('按住说话,松开发送'), findsOneWidget);
  });
}
