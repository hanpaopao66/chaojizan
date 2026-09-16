// 一条帖子画出来是什么样(DEV-PROMPTS-41 §2.2、§8.1)。
//
// ## 守的是什么
//
// - 头像、名字、@超级赞号、相对时间、「已编辑」该出的都出;
// - 正文里的 #话题、@、链接是**可点的片段**(和普通字不是同一个 TextSpan);
// - 「谁能回复」限制到我头上时,回复按钮不是消失,而是**置灰并说明为什么** ——
//   消失的话用户只会以为这条不能回复,不知道是自己不在名单里;
// - 删了 / 下架了 / 拉黑的那一条在串里**占位**,不是跳过;
// - 引用被引的没了时,引用框里写「已不可见」,引用本身照样在;
// - 卡片查不到时画灰条,不画一张点不开的空卡片。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/forum/models.dart';
import 'package:user_app/forum/widgets/post_tile.dart';
import 'package:user_app/forum/widgets/post_text.dart';

Map<String, dynamic> postJson([Map<String, dynamic> over = const {}]) => {
      'pid': 'fpHbFUgZ3A32',
      'author': {'id': 42, 'name': '小王', 'username': 'xiaowang', 'avatar': ''},
      'text': '就一句话',
      'entities': {'tags': <dynamic>[], 'mentions': <dynamic>[], 'links': <dynamic>[]},
      'media': <dynamic>[],
      'counts': {'replies': 2, 'reposts': 1, 'quotes': 0, 'likes': 9, 'bookmarks': 0, 'views': 120},
      'viewer': {'liked': false, 'reposted': false, 'bookmarked': false},
      'reply_policy': 'all',
      'can_reply': true,
      'created_at': '2026-09-15T12:00:00+08:00',
      ...over,
    };

Widget host(Widget child) => MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(body: ListView(children: [child])),
    );

/// 正文里可点的片段有几个(带手势识别器的 TextSpan)
int tappableSpans(WidgetTester t) {
  final rich = t.widget<Text>(find.descendant(of: find.byType(PostText), matching: find.byType(Text)).first);
  final span = rich.textSpan as TextSpan;
  return (span.children ?? const <InlineSpan>[])
      .whereType<TextSpan>()
      .where((s) => s.recognizer != null)
      .length;
}

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

  group('头部', () {
    testWidgets('名字、@号、相对时间都在', (t) async {
      await t.pumpWidget(host(PostTile(post: FPost.fromJson(postJson()))));
      expect(find.text('小王'), findsOneWidget);
      expect(find.text('@xiaowang'), findsOneWidget);
      expect(find.text('就一句话'), findsOneWidget);
    });

    testWidgets('改过的帖子标「已编辑」', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson(postJson({'edited': true, 'edited_at': '2026-09-15T12:10:00+08:00'})))));
      expect(find.text('已编辑'), findsOneWidget);
    });

    testWidgets('没改过的不标', (t) async {
      await t.pumpWidget(host(PostTile(post: FPost.fromJson(postJson()))));
      expect(find.text('已编辑'), findsNothing);
    });

    testWidgets('置顶那条标「置顶」', (t) async {
      await t.pumpWidget(host(PostTile(post: FPost.fromJson(postJson({'pinned': true})))));
      expect(find.text('置顶'), findsOneWidget);
    });

    testWidgets('回复别人的那条写「回复 @谁」', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson(postJson({
        'reply_to': {
          'pid': 'fpParent',
          'author': {'id': 7, 'name': '小明', 'username': 'xiaoming', 'avatar': ''}
        }
      })))));
      expect(find.text('回复 @xiaoming'), findsOneWidget);
    });
  });

  group('正文实体', () {
    testWidgets('#话题、@、链接各算一个可点片段', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson(postJson({
        'text': '#周末# 找 @xiaoming 看 https://a.cc',
        'entities': {
          'tags': [
            {'tag': '周末', 'display': '周末'}
          ],
          'mentions': [
            {'id': 7, 'username': 'xiaoming'}
          ],
          'links': ['https://a.cc'],
        },
      })))));
      expect(tappableSpans(t), 3);
    });

    testWidgets('没有实体时一个可点片段都没有', (t) async {
      await t.pumpWidget(host(PostTile(post: FPost.fromJson(postJson()))));
      expect(tappableSpans(t), 0);
    });

    testWidgets('点在普通字上只打开一次详情,不是两次', (t) async {
      // 正文外面套过一层 GestureDetector 的话,它和整条那层 InkWell 会抢同一下,
      // 同一个详情页可能被 push 两遍
      var taps = 0;
      await t.pumpWidget(host(PostTile(post: FPost.fromJson(postJson()), onTap: () => taps++)));
      await t.tap(find.text('就一句话'));
      await t.pump();
      expect(taps, 1);
    });
  });

  group('谁能回复', () {
    testWidgets('限制到我头上时回复按钮置灰,说得出只有谁能回', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson(postJson({'can_reply': false, 'reply_policy': 'following'})))));
      // 按钮还在(不是消失),提示写清楚了是谁能回
      final tip = t.widget<Tooltip>(find.ancestor(
          of: find.byIcon(Icons.mode_comment_outlined), matching: find.byType(Tooltip)));
      expect(tip.message, '只有我关注的人能回复');
    });

    testWidgets('不限制时提示就是「回复」', (t) async {
      await t.pumpWidget(host(PostTile(post: FPost.fromJson(postJson()))));
      final tip = t.widget<Tooltip>(find.ancestor(
          of: find.byIcon(Icons.mode_comment_outlined), matching: find.byType(Tooltip)));
      expect(tip.message, '回复');
    });
  });

  group('操作栏', () {
    testWidgets('回复 / 转发 / 赞 / 浏览 / 书签 / 分享六个都在,数字对得上', (t) async {
      await t.pumpWidget(host(PostTile(post: FPost.fromJson(postJson()))));
      expect(find.byIcon(Icons.mode_comment_outlined), findsOneWidget);
      expect(find.byIcon(Icons.repeat), findsOneWidget);
      expect(find.byIcon(Icons.favorite_outline), findsOneWidget);
      expect(find.byIcon(Icons.bar_chart), findsOneWidget);
      expect(find.byIcon(Icons.bookmark_border), findsOneWidget);
      expect(find.byIcon(Icons.ios_share), findsOneWidget);
      expect(find.text('9'), findsOneWidget, reason: '9 个赞');
      expect(find.text('120'), findsOneWidget, reason: '120 次浏览');
    });

    testWidgets('赞过的那条画的是实心心', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson(postJson({
        'viewer': {'liked': true, 'reposted': false, 'bookmarked': false}
      })))));
      expect(find.byIcon(Icons.favorite), findsOneWidget);
      expect(find.byIcon(Icons.favorite_outline), findsNothing);
    });

    testWidgets('showActions 关掉时整条操作栏都不画(发帖页里的原帖)', (t) async {
      await t.pumpWidget(host(PostTile(post: FPost.fromJson(postJson()), showActions: false)));
      expect(find.byIcon(Icons.favorite_outline), findsNothing);
    });
  });

  group('占位', () {
    testWidgets('删了的那条在串里占位,不是消失', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson({'pid': 'fpGone', 'unavailable': true, 'reason': 'deleted'}))));
      expect(find.text('这条帖子已删除'), findsOneWidget);
      // 占位条没有操作栏可点
      expect(find.byIcon(Icons.favorite_outline), findsNothing);
    });

    testWidgets('下架了、拉黑了各是一句', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson({'pid': 'fpX', 'unavailable': true, 'reason': 'removed'}))));
      expect(find.text('这条帖子已下架'), findsOneWidget);
    });
  });

  group('引用', () {
    testWidgets('引用框里是被引那条的作者和正文', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson(postJson({
        'quote': postJson({
          'pid': 'fpQuoted',
          'text': '被引的那句',
          'author': {'id': 7, 'name': '小明', 'username': 'xiaoming', 'avatar': ''},
        })
      })))));
      expect(find.text('被引的那句'), findsOneWidget);
      expect(find.text('小明'), findsOneWidget);
    });

    testWidgets('被引的没了:引用照样在,框里写「已不可见」', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson(postJson({
        'text': '看看这条',
        'quote': {'pid': 'fpGone', 'unavailable': true},
      })))));
      expect(find.text('看看这条'), findsOneWidget);
      expect(find.text('这条帖子已不可见'), findsOneWidget);
    });
  });

  group('卡片', () {
    testWidgets('有快照时标题和类型都画出来', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson(postJson({
        'card': {
          'type': 'track',
          'id': 'mtA',
          'title': '一首歌',
          'subtitle': '某位音乐人',
          'cover': '',
          'url': 'https://chaojizan.cc/music/t/mtA',
        }
      })))));
      expect(find.text('一首歌'), findsOneWidget);
      expect(find.text('某位音乐人'), findsOneWidget);
      expect(find.text('歌曲'), findsOneWidget);
    });

    testWidgets('查不到时画灰条,说清是什么不见了', (t) async {
      await t.pumpWidget(host(PostTile(
          post: FPost.fromJson(postJson({
        'card': {'type': 'playlist', 'id': 'mpA', 'unavailable': true}
      })))));
      expect(find.text('这条歌单已不可见'), findsOneWidget);
    });
  });

  group('转发条目', () {
    testWidgets('顶上一行「谁转发了」', (t) async {
      await t.pumpWidget(host(PostTile(
        post: FPost.fromJson(postJson()),
        repostBy: VPerson.fromJson({'id': 9, 'name': '小李', 'username': 'xiaoli', 'avatar': ''}),
        repostAt: DateTime.now().subtract(const Duration(minutes: 5)),
      )));
      expect(find.text('小李 转发了'), findsOneWidget);
      expect(find.text('小王'), findsOneWidget, reason: '帖子还是原作者的');
    });
  });

  group('推荐的中间量', () {
    testWidgets('推荐线上给一行「为什么推荐」', (t) async {
      await t.pumpWidget(host(PostTile(
        post: FPost.fromJson(postJson({
          'rank': {
            'score': 3.2,
            'parts': {'likes': 5, 'repliers': 1},
            'why': '5 人赞、1 人回复',
          }
        })),
        showRank: true,
      )));
      expect(find.text('为什么推荐:5 人赞、1 人回复'), findsOneWidget);
    });

    testWidgets('没有 rank 时不画那一行', (t) async {
      await t.pumpWidget(host(PostTile(post: FPost.fromJson(postJson()), showRank: true)));
      expect(find.textContaining('为什么推荐'), findsNothing);
    });
  });

  group('详情页那一条', () {
    testWidgets('计数摊成一行、浏览数写成整句', (t) async {
      await t.pumpWidget(host(PostTile(post: FPost.fromJson(postJson()), detail: true)));
      expect(find.text('转发'), findsOneWidget);
      expect(find.text('引用'), findsOneWidget);
      expect(find.text('赞'), findsOneWidget);
      expect(find.text('书签'), findsOneWidget);
      expect(find.text('120 次浏览'), findsOneWidget);
    });
  });
}
