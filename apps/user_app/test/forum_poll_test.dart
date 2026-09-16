// 帖子里的投票画出来是什么样(DEV-PROMPTS-41 F1、§8.1)。
//
// ## 守的是什么
//
// 投票**三态**必须泾渭分明,因为错的那一种会泄露结果:
//
// | 态 | 服务端给的 | 画成什么 |
// |---|---|---|
// | 还能投 | `votes` / `total` 都是 null | 每项一个按钮,**一个数字都不许出现** |
// | 投过了 | 票数在,`voted` 是我投的那项 | 横条 + 百分比,我那项打勾,按钮点不动 |
// | 已结束 | 票数在,`closed` 为真 | 横条 + 百分比 + 「已结束」 |
//
// 第一态里只要画出「0%」「0 人投票」,就等于告诉还没投的人结果 —— 和 X 不一样了。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/forum/models.dart';
import 'package:user_app/forum/widgets/poll_view.dart';

Widget host(Widget child) => MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(body: Padding(padding: const EdgeInsets.all(8), child: child)),
    );

FPoll poll(Map<String, dynamic> j) => FPoll.fromJson(j);

void main() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  group('第一态:还能投', () {
    final beforeVote = {
      'options': [
        {'text': '吃面', 'votes': null},
        {'text': '吃饭', 'votes': null},
      ],
      'total': null,
      'ends_at': '2999-01-01T12:00:00+08:00',
      'closed': false,
      'voted': null,
    };

    testWidgets('每项是一个能点的按钮', (t) async {
      var picked = -1;
      await t.pumpWidget(host(PollView(poll(beforeVote), onVote: (i) => picked = i)));
      expect(find.text('吃面'), findsOneWidget);
      expect(find.text('吃饭'), findsOneWidget);
      await t.tap(find.text('吃饭'));
      expect(picked, 1, reason: '点第二项投的就是第二项');
    });

    testWidgets('一个百分比、一个票数都不许出现', (t) async {
      await t.pumpWidget(host(PollView(poll(beforeVote), onVote: (_) {})));
      expect(find.textContaining('%'), findsNothing);
      expect(find.textContaining('人投票'), findsNothing);
    });

    testWidgets('写清楚「投票后才能看到结果」', (t) async {
      final noEnd = {...beforeVote, 'ends_at': null};
      await t.pumpWidget(host(PollView(poll(noEnd), onVote: (_) {})));
      expect(find.text('投票后才能看到结果'), findsOneWidget);
    });

    testWidgets('正在投的时候按钮点不动(别投两次)', (t) async {
      var taps = 0;
      await t.pumpWidget(host(PollView(poll(beforeVote), busy: true, onVote: (_) => taps++)));
      await t.tap(find.text('吃面'));
      expect(taps, 0);
    });

    testWidgets('还剩多久也显示出来', (t) async {
      await t.pumpWidget(host(PollView(poll(beforeVote), onVote: (_) {})));
      expect(find.textContaining('还有'), findsOneWidget);
    });
  });

  group('第二态:投过了', () {
    final afterVote = {
      'options': [
        {'text': '吃面', 'votes': 3},
        {'text': '吃饭', 'votes': 1},
      ],
      'total': 4,
      'ends_at': '2999-01-01T12:00:00+08:00',
      'closed': false,
      'voted': 0,
    };

    testWidgets('票数和百分比都出来', (t) async {
      await t.pumpWidget(host(PollView(poll(afterVote), onVote: (_) {})));
      expect(find.text('75%'), findsOneWidget);
      expect(find.text('25%'), findsOneWidget);
      expect(find.text('4 人投票'), findsOneWidget);
    });

    testWidgets('我投的那项打勾', (t) async {
      await t.pumpWidget(host(PollView(poll(afterVote), onVote: (_) {})));
      expect(find.byIcon(Icons.check), findsOneWidget);
      // 无障碍读出来也要说清楚是我投的那项
      expect(find.bySemanticsLabel(RegExp('我投的')), findsOneWidget);
    });

    testWidgets('点不动了(每人一票、不能改)', (t) async {
      var taps = 0;
      await t.pumpWidget(host(PollView(poll(afterVote), onVote: (_) => taps++)));
      await t.tap(find.text('吃饭'), warnIfMissed: false);
      await t.pump();
      expect(taps, 0);
    });
  });

  group('第三态:已结束', () {
    final closed = {
      'options': [
        {'text': '吃面', 'votes': 2},
        {'text': '吃饭', 'votes': 0},
      ],
      'total': 2,
      'closed': true,
      'voted': null,
    };

    testWidgets('没投过也看得到结果,写着「已结束」', (t) async {
      await t.pumpWidget(host(PollView(poll(closed), onVote: (_) {})));
      expect(find.text('100%'), findsOneWidget);
      expect(find.text('0%'), findsOneWidget);
      expect(find.text('已结束'), findsOneWidget);
    });

    testWidgets('没人打勾(我没投过)', (t) async {
      await t.pumpWidget(host(PollView(poll(closed), onVote: (_) {})));
      expect(find.byIcon(Icons.check), findsNothing);
    });

    testWidgets('一票都没有时不崩(不除以 0)', (t) async {
      await t.pumpWidget(host(PollView(
          poll({
            'options': [
              {'text': '甲', 'votes': 0},
              {'text': '乙', 'votes': 0},
            ],
            'total': 0,
            'closed': true,
          }),
          onVote: (_) {})));
      expect(find.text('0%'), findsNWidgets(2));
    });
  });

  group('只读', () {
    testWidgets('onVote 不给时按钮也点不动(别人的帖子、没登录的只读态)', (t) async {
      await t.pumpWidget(host(PollView(poll({
        'options': [
          {'text': '甲', 'votes': null},
          {'text': '乙', 'votes': null},
        ],
        'total': null,
        'closed': false,
      }))));
      // 画得出来,只是点不动
      expect(find.text('甲'), findsOneWidget);
      final button = t.widget<OutlinedButton>(
          find.ancestor(of: find.text('甲'), matching: find.byType(OutlinedButton)));
      expect(button.onPressed, isNull);
    });

    testWidgets('四项也排得下', (t) async {
      await t.pumpWidget(host(PollView(poll({
        'options': [
          for (final o in ['甲', '乙', '丙', '丁']) {'text': o, 'votes': null},
        ],
        'total': null,
        'closed': false,
      }), onVote: (_) {})));
      for (final o in ['甲', '乙', '丙', '丁']) {
        expect(find.text(o), findsOneWidget);
      }
    });
  });
}
