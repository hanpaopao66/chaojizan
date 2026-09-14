import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/chat/models.dart';
import 'package:user_app/chat/pages/tags_badges_page.dart';
import 'package:user_app/chat/pages/user_profile_page.dart';
import 'package:user_app/chat/store.dart';
import 'package:user_app/chat/ui/tags_badges.dart';
import 'package:user_app/main.dart' show superZTheme;

/// 资料页上的标签和勋章、「标签和勋章」设置页(服务端 services/badges.py)。
///
/// 守的几件事:
/// - 资料页照服务端给的显示:别人的只有没隐藏的(服务端已经滤掉),自己的隐藏项标「已隐藏」;
/// - 点一枚勋章看得到它的发放条件(服务端给的那一句,不是客户端写的);
/// - 设置页:加标签发出去的是整组新标签,重复的本地就挡、不发请求;服务端不收时原样提示它的话;
///   删标签、隐藏整组标签、隐藏单枚勋章各发一个 PATCH,方向对(开关打开 = 别人看得到);
/// - 「实名认证」默认不显示(服务端给 default_hidden):开关一进来是关的、页上写着默认不显示;
///   本人打开之后,别人的资料页上才有这一枚。
const _condRealName = '完成了实名认证(姓名和身份证号经过核验)';
const _condEarly = '在 2026 年 12 月 31 日(北京时间)及以前注册';
const _condUploader = '有至少 1 个审核通过、正在公开发布的视频';
const _condRegular = '完成过至少 10 单外卖或跑腿';

Map<String, dynamic> _badge(String key, String name, String icon, String cond,
        {bool? hidden, bool? earned, bool? defaultHidden}) =>
    {
      'key': key,
      'name': name,
      'icon': icon,
      'condition': cond,
      if (hidden != null) 'hidden': hidden,
      if (earned != null) 'earned': earned,
      if (defaultHidden != null) 'default_hidden': defaultHidden,
    };

/// 别人看:服务端已经把隐藏了的滤掉,hidden 一律 false
Map<String, dynamic> _othersCard() => {
      'id': 42,
      'name': '周小满',
      'username': 'xiaoman',
      'avatar': '',
      'bio': '爱吃辣',
      'public_id': 'kTx7YPsmgyJ2',
      'last_seen': {'online': false, 'at': null, 'approx': 'recently'},
      'is_contact': false,
      'contact_alias': '',
      'blocked': false,
      'is_bot': false,
      'is_self': false,
      'tags': ['川菜', '夜猫子'],
      'tags_hidden': false,
      'badges': [
        _badge('real_name', '实名认证', '实', _condRealName, hidden: false),
        _badge('uploader', 'UP 主', '投', _condUploader, hidden: false),
      ],
    };

/// 自己看自己:隐藏了的也在,标着
Map<String, dynamic> _selfCard() => {
      ..._othersCard(),
      'is_self': true,
      'tags_hidden': true,
      'badges': [
        _badge('real_name', '实名认证', '实', _condRealName, hidden: true),
        _badge('uploader', 'UP 主', '投', _condUploader, hidden: false),
      ],
    };

/// 假服务端:资料卡回 [card];「标签和勋章」按真服务端的样子改状态、回整页数据。
class _Server {
  _Server({Map<String, dynamic>? card}) : card = card ?? _othersCard();

  final Map<String, dynamic> card;
  final patches = <Map<String, dynamic>>[];
  var gets = 0;

  /// 一个还没动过显示设置的人:实名认证按缺省是隐藏的(真服务端就这么回)
  final me = <String, dynamic>{
    'tags': ['川菜', '夜猫子'],
    'tags_hidden': false,
    'tags_max': 5,
    'tag_max_len': 8,
    'badges': [
      _badge('real_name', '实名认证', '实', _condRealName, earned: true, hidden: true, defaultHidden: true),
      _badge('early', '早期用户', '早', _condEarly, earned: true, hidden: false, defaultHidden: false),
      _badge('uploader', 'UP 主', '投', _condUploader, earned: false, hidden: false, defaultHidden: false),
      _badge('regular', '老顾客', '老', _condRegular, earned: false, hidden: false, defaultHidden: false),
    ],
  };

  /// 照真服务端的口径,别人看我的资料时有哪几枚:拿到了、没隐藏的(hidden 一律 false,不带设置页的字段)
  List<Map<String, dynamic>> othersSee() => [
        for (final b in (me['badges'] as List).cast<Map<String, dynamic>>())
          if (b['earned'] == true && b['hidden'] != true)
            ({...b, 'hidden': false}
              ..remove('earned')
              ..remove('default_hidden')),
      ];

  http.Response _json(Object body, [int code = 200]) => http.Response(jsonEncode(body), code,
      headers: {'content-type': 'application/json; charset=utf-8'});

  late final api = ApiClient(
    baseUrl: 'https://api.example.test',
    httpClient: MockClient((req) async {
      final path = req.url.path;
      if (path == '/social/v1/me/tags-badges' && req.method == 'GET') {
        gets++;
        return _json(me);
      }
      if (path == '/social/v1/me/tags-badges' && req.method == 'PATCH') {
        final body = (jsonDecode(req.body) as Map).cast<String, dynamic>();
        patches.add(body);
        final tags = body['tags'];
        if (tags is List && tags.contains('官方推荐')) {
          return _json({'detail': '「官方推荐」容易被当成平台发的标志,换一个吧'}, 422);
        }
        if (tags is List) me['tags'] = [...tags];
        if (body['tags_hidden'] is bool) me['tags_hidden'] = body['tags_hidden'];
        final hide = (body['hidden_badges'] as Map?)?.cast<String, dynamic>() ?? const {};
        for (final b in (me['badges'] as List).cast<Map<String, dynamic>>()) {
          if (hide[b['key']] is bool) b['hidden'] = hide[b['key']];
        }
        return _json(me);
      }
      if (path.startsWith('/social/v1/users/')) return _json(card);
      return _json(<String, dynamic>{});
    }),
  );
}

void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'user_app', packageName: 'com.superz.user', version: '0.1.0', buildNumber: '1', buildSignature: ''));
  setUp(() => SharedPreferences.setMockInitialValues({}));
  tearDown(() => ChatStore.instance.stop());

  Future<void> pump(WidgetTester tester, Widget home) async {
    tester.view
      ..devicePixelRatio = 1
      ..physicalSize = const Size(390, 900);
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(theme: superZTheme(Brightness.light), home: home));
    await tester.pumpAndSettle();
  }

  group('从接口读', () {
    test('资料卡上的三个字段;列表里的名片没有这几项就是空的', () {
      final u = ChatUser.fromJson(_selfCard());
      expect(u.tagsBadges.tags, ['川菜', '夜猫子']);
      expect(u.tagsBadges.tagsHidden, isTrue);
      expect([for (final b in u.tagsBadges.badges) (b.key, b.hidden, b.earned)],
          [('real_name', true, true), ('uploader', false, true)]);
      expect(u.tagsBadges.badges.first.condition, _condRealName);
      final listCard = ChatUser.fromJson({'id': 7, 'name': '列表里的人'});
      expect(listCard.tagsBadges.isEmpty, isTrue);
      expect(TagsBadges.fromJson({'tags': ['a', 3, ''], 'badges': [{'name': '没有 key'}]}).tags, ['a'],
          reason: '宽松读:不认识的丢掉,不崩');
      expect(ProfileBadge.fromJson(_badge('real_name', '实名认证', '实', _condRealName, defaultHidden: true)).defaultHidden,
          isTrue);
      expect(u.tagsBadges.badges.first.defaultHidden, isFalse, reason: '资料卡上不带这个字段,读成 false');
    });
  });

  group('资料页', () {
    testWidgets('别人的:勋章、标签照服务端给的显示,没有「已隐藏」;点勋章看得到条件', (tester) async {
      final s = _Server();
      ChatStore.instance.debugUseClient(s.api);
      await pump(tester, const UserProfilePage(userId: 42));

      expect(find.text('实名认证'), findsOneWidget);
      expect(find.text('UP 主'), findsOneWidget);
      expect(find.text('川菜'), findsOneWidget);
      expect(find.text('夜猫子'), findsOneWidget);
      expect(find.textContaining('已隐藏'), findsNothing);
      // 勋章和标签在名字下面、按钮上面
      expect(tester.getTopLeft(find.text('实名认证')).dy, greaterThan(tester.getTopLeft(find.text('周小满')).dy));
      expect(tester.getTopLeft(find.text('川菜')).dy, lessThan(tester.getTopLeft(find.text('发消息')).dy));
      // 别人的标签不能点进去改
      expect(tester.widget<SzChip>(find.widgetWithText(SzChip, '川菜')).onTap, isNull);

      await tester.tap(find.text('实名认证'));
      await tester.pumpAndSettle();
      expect(find.text(_condRealName), findsOneWidget, reason: '条件是服务端给的那一句');
      expect(find.textContaining('不能买、不能申请'), findsOneWidget);
    });

    testWidgets('自己的:隐藏了的也在,标着「已隐藏」', (tester) async {
      final s = _Server(card: _selfCard());
      ChatStore.instance.debugUseClient(s.api);
      await pump(tester, const UserProfilePage(userId: 42));

      expect(find.text('实名认证 · 已隐藏'), findsOneWidget);
      expect(find.text('UP 主'), findsOneWidget);
      expect(find.text('标签已隐藏,只有你自己看得到'), findsOneWidget);
      expect(tester.widget<SzChip>(find.widgetWithText(SzChip, '川菜')).onTap, isNotNull,
          reason: '自己的标签点进去改');

      // 实名认证默认就是隐藏的:点开不能说成「你把它设成了隐藏」,告诉他在哪儿打开
      await tester.tap(find.text('实名认证 · 已隐藏'));
      await tester.pumpAndSettle();
      expect(find.text('现在对别人隐藏,只有你自己看得到;在「标签和勋章」里可以打开。'), findsOneWidget);
      expect(find.textContaining('你把它设成了'), findsNothing);
    });

    testWidgets('没有标签也没有勋章:什么都不画', (tester) async {
      final s = _Server(card: {..._othersCard(), 'tags': <String>[], 'badges': <Object>[]});
      ChatStore.instance.debugUseClient(s.api);
      await pump(tester, const UserProfilePage(userId: 42));
      expect(find.byType(TagsBadgesView), findsNothing);
      expect(find.byType(BadgeChip), findsNothing);
    });
  });

  group('「标签和勋章」设置页', () {
    testWidgets('全部勋章都列着:拿到的有开关,没拿到的写「还没有」,条件都在', (tester) async {
      final s = _Server();
      await pump(tester, TagsBadgesPage(client: s.api));
      for (final c in [_condRealName, _condUploader, _condRegular]) {
        expect(find.text(c), findsOneWidget);
      }
      expect(find.text('还没有'), findsNWidgets(2));
      // 两枚拿到了的勋章各一个开关 + 标签那一个
      expect(find.byType(Switch), findsNWidgets(3));
    });

    testWidgets('加标签:发出去的是整组新标签;重复的本地就挡;服务端不收的原样提示', (tester) async {
      final s = _Server();
      await pump(tester, TagsBadgesPage(client: s.api));

      await tester.enterText(find.byType(TextField), ' 周末 徒步 ');
      await tester.tap(find.text('添加'));
      await tester.pumpAndSettle();
      expect(s.patches.last, {'tags': ['川菜', '夜猫子', '周末 徒步']}, reason: '规整后整组发');
      expect(find.text('周末 徒步'), findsOneWidget);
      expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, isEmpty, reason: '加上了就清空输入框');

      final n = s.patches.length;
      await tester.enterText(find.byType(TextField), '夜猫子');
      await tester.tap(find.text('添加'));
      await tester.pumpAndSettle();
      expect(s.patches.length, n, reason: '重复的不发请求');
      expect(find.text('已经有「夜猫子」了'), findsOneWidget);

      await tester.enterText(find.byType(TextField), '官方推荐');
      await tester.tap(find.text('添加'));
      await tester.pumpAndSettle();
      expect(find.text('「官方推荐」容易被当成平台发的标志,换一个吧'), findsOneWidget);
      expect(find.widgetWithText(InputChip, '官方推荐'), findsNothing, reason: '服务端没收就不出现');

      // 输入框最多 8 个字(服务端的 tag_max_len),多的打不进去
      expect(tester.widget<TextField>(find.byType(TextField)).maxLength, 8);
    });

    testWidgets('删标签;满 5 个就不给输入框', (tester) async {
      final s = _Server();
      s.me['tags'] = ['一', '二', '三', '四', '五'];
      await pump(tester, TagsBadgesPage(client: s.api));
      expect(find.byType(TextField), findsNothing);
      expect(find.text('已经 5 个了,删掉一个才能再加'), findsOneWidget);

      await tester.tap(find.byTooltip('删掉「三」'));
      await tester.pumpAndSettle();
      expect(s.patches.last, {'tags': ['一', '二', '四', '五']});
      expect(find.byType(TextField), findsOneWidget, reason: '少了一个就又能加了');
    });

    testWidgets('隐藏:开关打开 = 别人看得到;关掉整组标签、关掉一枚勋章', (tester) async {
      final s = _Server();
      await pump(tester, TagsBadgesPage(client: s.api));

      Finder switchIn(Finder row) => find.descendant(of: row, matching: find.byType(Switch));
      final tagRow = find.ancestor(of: find.text('别人看得到我的标签'), matching: find.byType(SzEntryTile));
      expect(tester.widget<Switch>(switchIn(tagRow)).value, isTrue);
      await tester.tap(switchIn(tagRow));
      await tester.pumpAndSettle();
      expect(s.patches.last, {'tags_hidden': true});
      expect(find.text('已隐藏,只有你自己看得到'), findsOneWidget);

      final early = find.ancestor(of: find.text(_condEarly), matching: find.byType(InkWell)).first;
      expect(tester.widget<Switch>(switchIn(early)).value, isTrue);
      await tester.tap(switchIn(early));
      await tester.pumpAndSettle();
      expect(s.patches.last, {'hidden_badges': {'early': true}});
      expect(find.text('早期用户 · 已隐藏'), findsOneWidget);
      expect(tester.widget<Switch>(switchIn(early)).value, isFalse);

      await tester.tap(switchIn(early));
      await tester.pumpAndSettle();
      expect(s.patches.last, {'hidden_badges': {'early': false}}, reason: '再打开就是取消隐藏');
      expect(find.text('早期用户'), findsOneWidget);
    });

    testWidgets('实名认证默认不显示:开关一进来是关的、写着默认不显示;本人打开之后别人的资料页上才有', (tester) async {
      final s = _Server();
      await pump(tester, TagsBadgesPage(client: s.api));

      Finder switchIn(Finder row) => find.descendant(of: row, matching: find.byType(Switch));
      expect(find.textContaining('「实名认证」这一枚默认不显示,你可以自己打开'), findsOneWidget,
          reason: '哪一枚默认不显示照服务端的 default_hidden 写');
      final realName = find.ancestor(of: find.text(_condRealName), matching: find.byType(InkWell)).first;
      expect(tester.widget<Switch>(switchIn(realName)).value, isFalse, reason: '没选过:按缺省关着');
      expect(find.text('实名认证 · 已隐藏'), findsOneWidget);
      expect([for (final b in s.othersSee()) b['key']], ['early'], reason: '这时别人看不到实名认证');

      await tester.tap(switchIn(realName));
      await tester.pumpAndSettle();
      expect(s.patches.last, {'hidden_badges': {'real_name': false}}, reason: '打开 = 选了让别人看得到');
      expect(tester.widget<Switch>(switchIn(realName)).value, isTrue);
      expect(find.text('实名认证'), findsOneWidget);
      expect(find.text('实名认证 · 已隐藏'), findsNothing);

      // 别人再打开我的资料页:实名认证出来了,和别的勋章一样,没有「已隐藏」
      final other = _Server(card: {..._othersCard(), 'badges': s.othersSee()});
      ChatStore.instance.debugUseClient(other.api);
      await pump(tester, const UserProfilePage(userId: 42));
      expect(find.widgetWithText(BadgeChip, '实名认证'), findsOneWidget);
      expect(find.widgetWithText(BadgeChip, '早期用户'), findsOneWidget);
      expect(find.textContaining('已隐藏'), findsNothing);
    });

    testWidgets('服务端没有默认不显示的勋章时,不多那一句', (tester) async {
      final s = _Server();
      for (final b in (s.me['badges'] as List).cast<Map<String, dynamic>>()) {
        b['default_hidden'] = false;
      }
      await pump(tester, TagsBadgesPage(client: s.api));
      expect(find.textContaining('默认不显示'), findsNothing);
    });
  });
}
