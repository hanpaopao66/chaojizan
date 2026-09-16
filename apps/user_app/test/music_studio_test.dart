// 音乐人中心(DEV-PROMPTS-41 §4 M2、§5.3):开通表单的校验、提交审核前的本机校验、
// 以及开通表单上那两件必须说到的事 —— **不要求实名**、**必须是原创或已获授权**。
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/music/api.dart';
import 'package:user_app/music/models.dart';
import 'package:user_app/music/nav.dart';
import 'package:user_app/music/studio/studio_page.dart';
import 'package:user_app/music/studio/studio_rules.dart';

MTrack track(String tid, {String title = '一首歌', String status = 'ready', String declaration = 'original'}) =>
    MTrack.fromJson({
      'tid': tid,
      'title': title,
      'transcode_status': status,
      'declaration': declaration,
      'duration_ms': 200000,
    });

MRelease release({
  String status = 'draft',
  String cover = '/img/music_cover/a.jpg',
  List<MTrack> tracks = const [],
}) =>
    MRelease(rid: 'mrHbFUgZ3A32', title: '夏天', status: status, cover: cover, tracks: tracks);

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

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('艺名(§4 M2)', () {
    test('2–30 个字,按字符数不按字节', () {
      expect(validateArtistName(''), '起个艺名吧');
      expect(validateArtistName('   '), '起个艺名吧');
      expect(validateArtistName('林'), '艺名至少 2 个字');
      // 两个汉字就是 2 个字,不是 6 个字节
      expect(validateArtistName('小林'), isNull);
      expect(validateArtistName('a' * 30), isNull);
      expect(validateArtistName('a' * 31), '艺名最多 30 个字');
      expect(validateArtistName('字' * 31), '艺名最多 30 个字');
    });

    test('首尾空白不算长度', () {
      expect(validateArtistName('  小林  '), isNull);
      expect(validateArtistName('  林  '), '艺名至少 2 个字');
    });

    test('指平台自己的那几个词不许用(冒充走举报,但这几个词本身是平台的)', () {
      expect(validateArtistName('超级赞官方'), contains('超级赞'));
      expect(validateArtistName('SuperZ Music'), contains('superz'));
      expect(validateArtistName('客服小妹'), contains('客服'));
      expect(validateArtistName('Admin'), contains('admin'));
      // 正常艺名不受影响
      expect(validateArtistName('赞赞乐队'), isNull);
    });

    test('简介最多 300 个字', () {
      expect(validateArtistBio(''), isNull);
      expect(validateArtistBio('字' * 300), isNull);
      expect(validateArtistBio('字' * 301), '简介最多 300 个字');
    });
  });

  group('作品和歌的信息', () {
    test('建草稿要有名字、曲风、语种', () {
      expect(validateReleaseInfo(title: '', genre: 'pop', language: '国语'), '给作品起个名字');
      expect(validateReleaseInfo(title: '夏天', genre: '', language: '国语'), '选一个曲风');
      expect(validateReleaseInfo(title: '夏天', genre: 'pop', language: ''), '选一个语种');
      expect(validateReleaseInfo(title: '夏天', genre: 'pop', language: '国语'), isNull);
      expect(validateReleaseInfo(title: '字' * 61, genre: 'pop', language: '国语'), '作品名最多 60 个字');
    });

    test('歌名 1–60 个字', () {
      expect(validateTrackTitle(' '), '给这首歌起个名字');
      expect(validateTrackTitle('晚风'), isNull);
      expect(validateTrackTitle('字' * 61), '歌名最多 60 个字');
    });
  });

  group('提交审核前的本机校验(§5.3 四个前提)', () {
    test('全齐了就没有问题', () {
      final r = release(tracks: [track('mt1'), track('mt2')]);
      expect(releaseSubmitProblems(r), isEmpty);
    });

    test('一首歌都没有', () {
      expect(releaseSubmitProblems(release()), contains('至少要有 1 首歌'));
    });

    test('没有封面', () {
      final r = release(cover: '', tracks: [track('mt1')]);
      expect(releaseSubmitProblems(r), contains('还没有封面'));
    });

    test('还有歌在转码:说清楚是哪几首,别只说「还没准备好」', () {
      final r = release(tracks: [
        track('mt1', title: '甲'),
        track('mt2', title: '乙', status: 'processing'),
        track('mt3', title: '丙', status: 'pending'),
      ]);
      final problems = releaseSubmitProblems(r);
      expect(problems.length, 1);
      expect(problems.single, contains('乙'));
      expect(problems.single, contains('丙'));
      expect(problems.single, isNot(contains('甲')));
    });

    test('转码失败的和还在转的分开说 —— 一个要等,一个要重传', () {
      final r = release(tracks: [
        track('mt1', title: '甲', status: 'failed'),
        track('mt2', title: '乙', status: 'processing'),
      ]);
      final problems = releaseSubmitProblems(r);
      expect(problems.any((p) => p.contains('转码失败') && p.contains('甲')), isTrue);
      expect(problems.any((p) => p.contains('还在转码') && p.contains('乙')), isTrue);
    });

    test('有歌没勾原创 / 已获授权', () {
      final r = release(tracks: [track('mt1', title: '甲', declaration: ''), track('mt2', declaration: 'authorized')]);
      final problems = releaseSubmitProblems(r);
      expect(problems.any((p) => p.contains('原创 / 已获授权') && p.contains('甲')), isTrue);
    });

    test('缺好几样时一次全说完,而不是修一条报一条', () {
      final r = release(cover: '', tracks: [track('mt1', status: 'processing', declaration: '')]);
      final problems = releaseSubmitProblems(r);
      expect(problems.length, greaterThanOrEqualTo(3));
      expect(problems.any((p) => p.contains('封面')), isTrue);
      expect(problems.any((p) => p.contains('转码')), isTrue);
      expect(problems.any((p) => p.contains('原创')), isTrue);
    });
  });

  group('状态机给的动作(§5.3)', () {
    test('能改的三个状态给「提交审核」', () {
      for (final s in ['draft', 'rejected', 'withdrawn']) {
        expect(releaseActionLabel(s), '提交审核', reason: s);
        expect(releaseEditable(release(status: s)), isTrue, reason: s);
      }
    });

    test('审核中能撤回、已发布能下架、被下架只能申诉', () {
      expect(releaseActionLabel('reviewing'), '撤回提交');
      expect(releaseActionLabel('published'), '下架');
      expect(releaseActionLabel('removed'), '');
      for (final s in ['reviewing', 'published', 'removed']) {
        expect(releaseEditable(release(status: s)), isFalse, reason: s);
      }
    });
  });

  group('开通表单', () {
    /// 没开通时 `/studio/me` 的 artist 是 null;开通请求记下来给断言看。
    List<Map<String, dynamic>> mockNotOpened() {
      final posts = <Map<String, dynamic>>[];
      musicApi = MusicApi(ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          if (req.method == 'POST' && req.url.path.endsWith('/studio/artist')) {
            posts.add(jsonDecode(req.body) as Map<String, dynamic>);
            return http.Response(jsonEncode({'aid': 'maHbFUgZ3A32', 'name': '小林'}), 200,
                headers: {'content-type': 'application/json; charset=utf-8'});
          }
          if (req.url.path.endsWith('/genres')) {
            return http.Response(
                jsonEncode([
                  {'key': 'pop', 'name': '流行'},
                  {'key': 'rock', 'name': '摇滚'},
                ]),
                200,
                headers: {'content-type': 'application/json; charset=utf-8'});
          }
          // /studio/me:还没开通
          return http.Response(jsonEncode({'artist': null}), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      ));
      return posts;
    }

    Future<void> pumpForm(WidgetTester tester) async {
      tester.view.physicalSize = const Size(420, 3000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() {
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });
      await tester.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(body: MusicArtistOpenForm(key: UniqueKey(), onOpened: () async {})),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('表单上写明不要求实名,以及上传必须是原创或已获授权', (tester) async {
      mockNotOpened();
      await pumpForm(tester);
      expect(find.textContaining('不要求实名'), findsOneWidget);
      expect(find.text('上传的必须是原创或已获授权的作品'), findsOneWidget);
      expect(find.textContaining('我确认,我上传的作品是我原创的或者我已获得授权'), findsOneWidget);
      // 不该出现任何要身份证 / 实名认证的字眼
      expect(find.textContaining('身份证'), findsNothing);
      expect(find.textContaining('实名认证'), findsNothing);
    });

    testWidgets('艺名不合规时当场在输入框下面报错,而且不发请求', (tester) async {
      final posts = mockNotOpened();
      await pumpForm(tester);
      await tester.enterText(find.byType(TextField).first, '林');
      await tester.pumpAndSettle();
      expect(find.text('艺名至少 2 个字'), findsOneWidget);

      await tester.tap(find.widgetWithText(FilledButton, '开通'));
      await tester.pumpAndSettle();
      expect(posts, isEmpty);
    });

    testWidgets('用了平台自己的名字时报错,不发请求', (tester) async {
      final posts = mockNotOpened();
      await pumpForm(tester);
      await tester.enterText(find.byType(TextField).first, '超级赞官方');
      await tester.pumpAndSettle();
      expect(find.textContaining('不能有「超级赞」'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilledButton, '开通'));
      await tester.pumpAndSettle();
      expect(posts, isEmpty);
    });

    testWidgets('没勾原创 / 已获授权时不让开通', (tester) async {
      final posts = mockNotOpened();
      await pumpForm(tester);
      await tester.enterText(find.byType(TextField).first, '小林');
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, '开通'));
      await tester.pumpAndSettle();
      expect(posts, isEmpty);
      expect(find.text('请先确认作品是原创或已获授权'), findsOneWidget);
    });

    testWidgets('都填对了才发请求,艺名去掉首尾空白、曲风一起带上', (tester) async {
      final posts = mockNotOpened();
      await pumpForm(tester);
      await tester.enterText(find.byType(TextField).first, '  小林  ');
      await tester.enterText(find.byType(TextField).at(1), '写歌的');
      await tester.pumpAndSettle();
      await tester.tap(find.text('流行'));
      await tester.tap(find.byType(Checkbox));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, '开通'));
      await tester.pumpAndSettle();

      expect(posts.length, 1);
      expect(posts.single['name'], '小林');
      expect(posts.single['bio'], '写歌的');
      expect(posts.single['genres'], ['pop']);
    });

    testWidgets('艺名撞车这类服务端才知道的,把原话摆在输入框下面', (tester) async {
      musicApi = MusicApi(ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          if (req.method == 'POST') {
            return http.Response(jsonEncode({'detail': '这个艺名已经有人用了'}), 409,
                headers: {'content-type': 'application/json; charset=utf-8'});
          }
          return http.Response(jsonEncode(const <Object>[]), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      ));
      await pumpForm(tester);
      await tester.enterText(find.byType(TextField).first, '小林');
      await tester.pumpAndSettle();
      await tester.tap(find.byType(Checkbox));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, '开通'));
      await tester.pumpAndSettle();
      expect(find.text('这个艺名已经有人用了'), findsOneWidget);
    });
  });

  group('开通表单的措辞', () {
    // 这两句是 09-15 运营方拍板的立场,不是随手写的文案:
    // 开通音乐人**不要求实名**,但曲库**只收原创或已获授权**的作品。
    // 措辞改了要一起改规格,所以这里钉住。
    test('保留词清单里有平台自己的名字', () {
      expect(kReservedArtistNames, contains('超级赞'));
      expect(kReservedArtistNames, contains('官方'));
      expect(kReservedArtistNames, contains('admin'));
    });

    test('声明只有原创和已获授权两种,没有第三种', () {
      expect(mDeclarationName('original'), '原创');
      expect(mDeclarationName('authorized'), '已获授权');
      // 传了别的值一律当原创显示是不行的 —— 服务端只认这两种,
      // 提交前校验会把没勾的挑出来(上面那一组)
      expect(releaseSubmitProblems(release(tracks: [track('mt1', declaration: 'whatever')])).any((p) => p.contains('原创')),
          isTrue);
    });
  });
}
