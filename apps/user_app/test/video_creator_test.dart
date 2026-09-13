// 投稿与创作中心(DEV-PROMPTS-40 #358)的纯函数:表单校验、差量、三方合并、状态标签、折线图坐标。
//
// 校验规则抄的是服务端 server/app/services/video.py(clean_fields / _check_submittable),
// 两边口径不一致时这里先红。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/video/creator/creator_models.dart';
import 'package:user_app/video/creator/line_chart.dart';
import 'package:user_app/video/creator/upload_form.dart';

/// 创作中心接口返回的稿件(字段取自 VIDEO-API 8.3 的真实响应),[over] 覆盖其中几项。
Map<String, dynamic> creatorJson([Map<String, dynamic> over = const {}]) => {
      'vid': 'svHbFUgZ3A32',
      'title': '示例视频',
      'cover': '',
      'duration_ms': 6000,
      'zone': 'tech',
      'zone_name': '科技',
      'tags': ['示例', '测试'],
      'status': 'draft',
      'status_label': '草稿',
      'visibility': 'public',
      'reject_code': '',
      'reject_label': '',
      'reject_note': '',
      'fail_reason': '',
      'scheduled_at': null,
      'pending': null,
      'description': '接口文档用的示例稿件',
      'copyright': 'original',
      'source_url': '',
      'allow_danmaku': true,
      'allow_comments': true,
      'shop': null,
      'shop_id': null,
      'shop_collab': null,
      'cover_media_id': null,
      'cover_preview': null,
      'parts': [
        {'id': 221, 'idx': 0, 'title': '第一 P', 'status': 'ready', 'duration_ms': 6000, 'w': 1280, 'h': 720, 'live': true},
        {'id': 222, 'idx': 1, 'title': '第二 P', 'status': 'processing', 'duration_ms': 3000, 'w': 1280, 'h': 720, 'live': true},
      ],
      'version_part_ids': [221, 222],
      'decisions': [],
      ...over,
    };

CreatorVideo cv([Map<String, dynamic> over = const {}]) => CreatorVideo.fromJson(creatorJson(over));

UploadForm okForm() => UploadForm(
      title: '探店:楼下面馆',
      zone: 'shop_visit',
      tags: ['探店'],
      parts: [const PartDraft(1, 'P1')],
    );

void main() {
  final now = DateTime(2026, 9, 12, 10, 0);

  group('标题 / 简介', () {
    test('提交时标题必填,存草稿不必填', () {
      expect(checkTitle('', submitting: true), '标题不能为空');
      expect(checkTitle('   \n ', submitting: true), '标题不能为空');
      expect(checkTitle('', submitting: false), isNull);
    });

    test('80 字正好能过,81 字不行', () {
      expect(checkTitle('字' * 80, submitting: true), isNull);
      expect(checkTitle('字' * 81, submitting: true), '标题最多 80 字');
    });

    test('字数按码点数:80 个 emoji 在 Dart 里 length 是 160,也算 80 字', () {
      final t = '😀' * 80;
      expect(t.length, 160);
      expect(checkTitle(t, submitting: true), isNull);
      expect(checkTitle('$t😀', submitting: true), '标题最多 80 字');
    });

    test('连续空白压成一个再数(和服务端 " ".join(split()) 一样)', () {
      expect(normalizeTitle('  楼下  面馆\n\t好吃 '), '楼下 面馆 好吃');
      // 79 个字 + 中间一大段空白:压完是 80,能过
      expect(checkTitle('${'字' * 40}          ${'字' * 39}', submitting: true), isNull);
    });

    test('简介最多 2000 字', () {
      expect(checkDescription('字' * 2000), isNull);
      expect(checkDescription('字' * 2001), '简介最多 2000 字');
    });
  });

  group('标签', () {
    test('逗号、顿号、空格都能分隔,# 去掉,重复的跳过', () {
      expect(splitTagInput('#探店, 美食，火锅、 成都  #探店'), ['探店', '美食', '火锅', '成都', '探店']);
      final r = addTags(['探店'], '#探店,美食');
      expect(r.tags, ['探店', '美食']);
      expect(r.error, isNull);
    });

    test('第 11 个加不进去,并说明原因', () {
      final ten = [for (var i = 0; i < 10; i++) '标签$i'];
      final r = addTags(ten, '再来一个');
      expect(r.tags, ten);
      expect(r.error, '标签最多 10 个');
      expect(checkTags([...ten, 'x']), '标签最多 10 个');
    });

    test('超过 20 字的不加,同一次敲的其他标签照加', () {
      final r = addTags([], '${'长' * 21},短的');
      expect(r.tags, ['短的']);
      expect(r.error, '每个标签最多 20 字');
      expect(checkTags(['长' * 20]), isNull);
      expect(checkTags(['长' * 21]), '每个标签最多 20 字');
    });
  });

  group('转载来源', () {
    test('自制不看来源', () {
      expect(checkSource('original', '', submitting: true), isNull);
      expect(checkSource('original', '乱写的', submitting: true), isNull);
    });

    test('转载必填,而且得是 http(s) 链接', () {
      expect(checkSource('repost', '', submitting: true), '转载要填写来源链接');
      expect(checkSource('repost', '', submitting: false), isNull);
      expect(checkSource('repost', 'www.bilibili.com/video/1', submitting: true), '转载来源要填 http(s) 开头的链接');
      expect(checkSource('repost', 'ftp://a.com/x', submitting: true), '转载来源要填 http(s) 开头的链接');
      expect(checkSource('repost', 'https://a b.com', submitting: true), '转载来源要填 http(s) 开头的链接');
      expect(checkSource('repost', 'http://a', submitting: true), '转载来源要填 http(s) 开头的链接');
      expect(checkSource('repost', ' https://b23.tv/abc ', submitting: true), isNull);
      expect(checkSource('repost', 'http://example.com', submitting: true), isNull);
    });
  });

  group('定时发布', () {
    test('5 分钟之后、30 天之内,两头正好都算合规', () {
      expect(checkSchedule(null, now), isNull);
      expect(checkSchedule(now.add(const Duration(minutes: 5)), now), isNull);
      expect(checkSchedule(now.add(const Duration(days: 30)), now), isNull);
      expect(checkSchedule(now.add(const Duration(minutes: 4, seconds: 59)), now), '定时发布要设在 5 分钟之后、30 天之内');
      expect(checkSchedule(now.add(const Duration(days: 30, minutes: 1)), now), '定时发布要设在 5 分钟之后、30 天之内');
      expect(checkSchedule(now.subtract(const Duration(hours: 1)), now), '定时发布要设在 5 分钟之后、30 天之内');
    });

    test('已经在等定时发布、离发布不到 5 分钟:没改时间就不查(那个时间不会再送)', () {
      final base = okForm()..scheduledAt = now.add(const Duration(minutes: 3));
      final cur = base.copy()..title = '改个标题';
      expect(validateForm(cur, now: now, submitting: true, base: base).containsKey('schedule'), isFalse);
      // 改了时间就要查
      final moved = base.copy()..scheduledAt = now.add(const Duration(minutes: 4));
      expect(validateForm(moved, now: now, submitting: true, base: base)['schedule'], '定时发布要设在 5 分钟之后、30 天之内');
    });

    test('同一时刻换个时区写法不算改', () {
      final a = okForm()..scheduledAt = DateTime.utc(2026, 9, 13, 12);
      final b = a.copy()..scheduledAt = DateTime.utc(2026, 9, 13, 12).toLocal();
      expect(scheduleChanged(a, b), isFalse);
      expect(formDiff(a, b), isEmpty);
    });
  });

  group('合作声明(D16)', () {
    test('挂了店就必须选有没有合作;不挂店不管', () {
      expect(checkCollab(12, null, submitting: true), '挂了店铺就要选「与商家有无合作」');
      expect(checkCollab(12, false, submitting: true), isNull);
      expect(checkCollab(12, true, submitting: true), isNull);
      expect(checkCollab(null, null, submitting: true), isNull);
      expect(checkCollab(12, null, submitting: false), isNull);
    });
  });

  group('整张表单', () {
    test('空表单提交:标题、分区、分 P 都要;存草稿一个都不拦', () {
      final e = validateForm(UploadForm(), now: now, submitting: true);
      expect(e.keys, containsAll(['title', 'zone', 'parts']));
      expect(validateForm(UploadForm(), now: now, submitting: false), isEmpty);
    });

    test('填好了就没有问题', () {
      expect(validateForm(okForm(), now: now, submitting: true), isEmpty);
    });

    test('超过 10 P', () {
      final f = okForm()..parts = [for (var i = 0; i < 11; i++) PartDraft(i, 'P$i')];
      expect(validateForm(f, now: now, submitting: false)['parts'], '一个视频最多 10 P');
    });
  });

  group('差量(只送改了的)', () {
    test('没改就是空的', () {
      final base = UploadForm.fromCreator(cv());
      expect(formDiff(base, base.copy()), isEmpty);
    });

    test('改了标题只送标题;标题里多打的空格不算改', () {
      final base = UploadForm.fromCreator(cv());
      expect(formDiff(base, base.copy()..title = '  示例视频 '), isEmpty);
      expect(formDiff(base, base.copy()..title = '新标题'), {'title': '新标题'});
    });

    test('已发布的稿件不带 scheduled_at(带了服务端回 409)', () {
      final base = UploadForm.fromCreator(cv({'status': 'published'}));
      final cur = base.copy()
        ..scheduledAt = now.add(const Duration(days: 1))
        ..visibility = 'private';
      final d = formDiff(base, cur, withSchedule: false);
      expect(d.containsKey('scheduled_at'), isFalse);
      expect(d, {'visibility': 'private'});
    });

    test('换店铺时合作声明一起送', () {
      final base = UploadForm.fromCreator(cv({'shop_id': 1, 'shop_collab': true, 'shop': {'id': 1, 'name': '张记面馆'}}));
      expect(base.shopName, '张记面馆');
      final cur = base.copy()..shopId = 2;
      expect(formDiff(base, cur), {'shop_id': 2, 'shop_collab': true});
      final removed = base.copy()
        ..shopId = null
        ..shopCollab = null;
      expect(formDiff(base, removed), {'shop_id': null, 'shop_collab': null});
    });

    test('改回自制把转载来源清掉', () {
      final base = UploadForm.fromCreator(cv({'copyright': 'repost', 'source_url': 'https://b23.tv/x'}));
      final cur = base.copy()..copyright = 'original';
      expect(formDiff(base, cur), {'copyright': 'original', 'source_url': ''});
    });

    test('分 P 换了顺序或改了标题才送 parts', () {
      final base = UploadForm.fromCreator(cv());
      expect(base.parts, [const PartDraft(221, '第一 P'), const PartDraft(222, '第二 P')]);
      final swapped = base.copy()..parts = base.parts.reversed.toList();
      expect(formDiff(base, swapped)['parts'], [
        {'id': 222, 'title': '第二 P'},
        {'id': 221, 'title': '第一 P'},
      ]);
      final renamed = base.copy()..parts = [const PartDraft(221, '开头'), base.parts[1]];
      expect(formDiff(base, renamed).keys, ['parts']);
    });
  });

  group('从稿件读表单', () {
    test('已发布稿件有没审的改动:改动里的值优先,分 P 用改动的清单', () {
      final v = cv({
        'status': 'published',
        'pending': {
          'state': 'editing',
          'state_label': '改动未提交',
          'fields': {
            'title': '改过的标题',
            'tags': ['新标签'],
            'cover_media_id': 99,
            'shop_id': 7,
          },
          'parts': [
            {'id': 222, 'title': '第二 P'},
            {'id': 300, 'title': '新加的'},
          ],
        },
      });
      final f = UploadForm.fromCreator(v);
      expect(f.title, '改过的标题');
      expect(f.tags, ['新标签']);
      expect(f.coverMediaId, 99);
      expect(f.shopId, 7);
      expect(f.shopName, '', reason: '改动里换的店,线上那家的名字对不上,页面再按 id 查');
      expect(f.description, '接口文档用的示例稿件', reason: '没改的字段用线上的');
      expect(f.parts, [const PartDraft(222, '第二 P'), const PartDraft(300, '新加的')]);
    });

    test('文件名当默认标题:去扩展名、下划线当空格、超长截到 80', () {
      expect(titleFromFileName('my_trip.final.mp4'), 'my trip.final');
      expect(titleFromFileName('VID20260912'), 'VID20260912');
      expect(titleFromFileName('${'长' * 100}.mov').runes.length, 80);
    });
  });

  group('三方合并', () {
    test('我没动的字段跟服务端,动过的留我的', () {
      final old = UploadForm.fromCreator(cv());
      final mine = old.copy()..description = '我刚写的简介';
      final fresh = UploadForm.fromCreator(cv({'title': '另一台设备改的标题'}));
      final r = rebaseForm(old, mine, fresh);
      expect(r.title, '另一台设备改的标题');
      expect(r.description, '我刚写的简介');
      expect(formDiff(fresh, r), {'description': '我刚写的简介'});
    });

    test('新传的分 P 接在后面,别处删掉的去掉,我排的顺序和改的标题留着', () {
      expect(
        mergeParts(
          [const PartDraft(2, '二'), const PartDraft(1, '一(改)')],
          [const PartDraft(1, '一'), const PartDraft(3, '三')],
        ),
        [const PartDraft(1, '一(改)'), const PartDraft(3, '三')],
      );
      final old = UploadForm.fromCreator(cv());
      final mine = old.copy()..parts = [old.parts[1], old.parts[0]];
      final fresh = UploadForm.fromCreator(cv({
        'parts': [...(creatorJson()['parts'] as List), {'id': 223, 'idx': 2, 'title': '第三 P', 'status': 'processing'}],
        'version_part_ids': [221, 222, 223],
      }));
      final r = rebaseForm(old, mine, fresh);
      expect([for (final p in r.parts) p.id], [222, 221, 223]);
    });

    test('我没挪过顺序:跟服务端的顺序', () {
      final old = UploadForm.fromCreator(cv());
      final fresh = UploadForm.fromCreator(cv({'version_part_ids': [222, 221]}));
      final r = rebaseForm(old, old.copy(), fresh);
      expect([for (final p in r.parts) p.id], [222, 221]);
    });
  });

  group('状态标签', () {
    List<String> labels(Map<String, dynamic> over) => [for (final t in creatorTags(cv(over))) t.toString()];

    test('每种状态一个标签', () {
      expect(labels({'status': 'draft'}), ['草稿']);
      expect(labels({'status': 'processing'}), ['转码中']);
      expect(labels({'status': 'reviewing'}), ['审核中']);
      expect(labels({'status': 'published'}), ['已通过']);
    });

    test('未通过、下架、转码失败带原因', () {
      expect(labels({'status': 'rejected', 'reject_code': 'V202', 'reject_label': '标题 / 封面与内容不符', 'reject_note': '标题和内容对不上'}),
          ['未通过(标题 / 封面与内容不符:标题和内容对不上)']);
      expect(labels({'status': 'removed', 'reject_code': 'V201', 'reject_label': '视频侵权(未经授权搬运)'}),
          ['已下架(视频侵权(未经授权搬运))']);
      expect(labels({'status': 'failed', 'fail_reason': '「第一 P」转码失败:文件损坏'}), ['转码失败(「第一 P」转码失败:文件损坏)']);
      // 没有中文名时退回代码,不留空
      expect(labels({'status': 'rejected', 'reject_code': 'X999', 'reject_note': ''}), ['未通过(X999)']);
      expect(creatorTags(cv({'status': 'rejected'})).single.tone, CreatorTone.bad);
    });

    test('定时发布写上几点公开', () {
      final at = DateTime(2026, 9, 14, 20, 5);
      final t = creatorTags(cv({'status': 'scheduled', 'scheduled_at': at.toUtc().toIso8601String()})).single;
      expect(t.label, '定时发布');
      expect(t.detail, '9月14日 20:05 公开');
      expect(t.tone, CreatorTone.busy);
    });

    test('已发布 + 改动:两个标签', () {
      Map<String, dynamic> pending(String state, [Map<String, dynamic> more = const {}]) =>
          {'status': 'published', 'pending': {'state': state, 'fields': {'title': 'x'}, ...more}};
      expect(labels(pending('reviewing')), ['已通过', '改动审核中']);
      expect(labels(pending('processing')), ['已通过', '改动转码中']);
      expect(labels(pending('editing')), ['已通过', '改动未提交']);
      expect(labels(pending('rejected', {'reject_code': 'V202', 'reject_label': '标题 / 封面与内容不符'})),
          ['已通过', '改动未通过(标题 / 封面与内容不符)']);
    });

    test('转码 / 审核中(稿件或改动)不能改内容;下架的什么都不能改', () {
      expect(cv({'status': 'draft'}).contentLocked, isFalse);
      expect(cv({'status': 'reviewing'}).contentLocked, isTrue);
      expect(cv({'status': 'removed'}).contentLocked, isTrue);
      expect(cv({'status': 'published', 'pending': {'state': 'reviewing'}}).contentLocked, isTrue);
      expect(cv({'status': 'published', 'pending': {'state': 'rejected'}}).contentLocked, isFalse);
    });

    test('页签口径和服务端 CREATOR_FILTERS 一致', () {
      expect(inCreatorTab('processing', 'draft'), isTrue);
      expect(inCreatorTab('processing', 'failed'), isTrue);
      expect(inCreatorTab('processing', 'reviewing'), isFalse);
      expect(inCreatorTab('published', 'scheduled'), isTrue);
      expect(inCreatorTab('all', 'removed'), isTrue);
      expect(inCreatorTab('all', 'deleted'), isFalse);
      final byStatus = {'draft': 1, 'processing': 2, 'failed': 1, 'published': 3, 'scheduled': 1, 'removed': 0};
      expect(creatorTabCount('processing', byStatus), 4);
      expect(creatorTabCount('published', byStatus), 4);
      expect(creatorTabCount('all', byStatus), 8);
    });

    test('能不能申诉:只看最近一次驳回 / 下架,而且稿件还停在那个结论上(和服务端 appeal() 同一个判据)', () {
      Map<String, dynamic> d(int id, String action, {bool can = false}) =>
          {'id': id, 'action': action, 'can_appeal': can};
      // 被驳回、没改过:能申诉
      final rejected = cv({'status': 'rejected', 'decisions': [d(1, 'reject', can: true)]});
      expect(rejected.canAppeal, isTrue);
      expect(rejected.appealTarget!.id, 1);
      // 驳回之后改过、重新提交了:服务端回 409「不用申诉」,这里就不给按钮
      expect(cv({'status': 'reviewing', 'decisions': [d(1, 'reject', can: true)]}).canAppeal, isFalse);
      // 已经申诉过
      expect(cv({'status': 'rejected', 'decisions': [d(1, 'reject'), d(2, 'appeal')]}).canAppeal, isFalse);
      // 改动被驳回:改动还停在「未通过」才能申诉;放弃后重交就不行了
      expect(
          cv({
            'status': 'published',
            'pending': {'state': 'rejected'},
            'decisions': [d(1, 'approve'), d(2, 'reject_changes', can: true)],
          }).canAppeal,
          isTrue);
      expect(
          cv({
            'status': 'published',
            'pending': {'state': 'reviewing'},
            'decisions': [d(1, 'approve'), d(2, 'reject_changes', can: true)],
          }).canAppeal,
          isFalse);
      // 只看最近一次:更早那条驳回的 can_appeal 还是 true,但最近一次是下架
      expect(
          cv({
            'status': 'removed',
            'decisions': [d(1, 'reject', can: true), d(2, 'approve'), d(3, 'remove', can: true)],
          }).appealTarget!.id,
          3);
      expect(cv({'status': 'published', 'decisions': [d(1, 'approve')]}).canAppeal, isFalse);
    });

    test('改动摘要:改了哪些', () {
      final p = cv({
        'status': 'published',
        'pending': {
          'state': 'editing',
          'fields': {'title': 'x', 'tags': ['y']},
          'parts': [{'id': 1, 'title': 'a'}],
        },
      }).pending!;
      expect(pendingSummary(p), '改了:标题、标签、分 P');
    });
  });

  group('折线图坐标', () {
    test('y 轴顶:1 / 2 / 5 × 10ⁿ,全是 0 时取 1', () {
      expect(chartCeil(0), 1);
      expect(chartCeil(1), 1);
      expect(chartCeil(3), 5);
      expect(chartCeil(7), 10);
      expect(chartCeil(10), 10);
      expect(chartCeil(11), 20);
      expect(chartCeil(101), 200);
      expect(chartCeil(250), 500);
      expect(chartCeil(12000), 20000);
    });

    test('x 均分、y 从底往上', () {
      final pts = chartPoints([0, 5, 10], const Size(100, 50), yMax: 10);
      expect(pts, const [Offset(0, 50), Offset(50, 25), Offset(100, 0)]);
    });

    test('留白算进去', () {
      final pts = chartPoints([0, 10], const Size(140, 72), pad: const EdgeInsets.fromLTRB(30, 10, 10, 22), yMax: 10);
      expect(pts, const [Offset(30, 50), Offset(130, 10)]);
    });

    test('只有一个点放中间;超出上限的夹在顶上;全是 0 贴底', () {
      expect(chartPoints([3], const Size(100, 40), yMax: 10), const [Offset(50, 28)]);
      expect(chartPoints([20], const Size(100, 40), yMax: 10).single.dy, 0);
      expect(chartPoints([0, 0, 0], const Size(90, 30)).map((p) => p.dy), [30, 30, 30]);
      expect(chartPoints([], const Size(90, 30)), isEmpty);
    });

    test('手指位置换成第几天(就近,越界夹到两头)', () {
      const size = Size(100, 50);
      expect(chartIndexAt(0, 30, size), 0);
      expect(chartIndexAt(100, 30, size), 29);
      expect(chartIndexAt(51, 30, size), 15);
      expect(chartIndexAt(-20, 30, size), 0);
      expect(chartIndexAt(500, 30, size), 29);
      expect(chartIndexAt(60, 3, const Size(130, 50), pad: const EdgeInsets.only(left: 30)), 1);
      expect(chartIndexAt(10, 1, size), 0);
    });

    test('日期标签', () {
      expect(chartDayLabel('2026-09-07'), '9/7');
      expect(chartDayLabel('2026-10-12'), '10/12');
      expect(chartDayLabel('坏的'), '坏的');
    });

    testWidgets('折线图画得出来,点一下换成那一天的数', (tester) async {
      final days = [for (var i = 1; i <= 30; i++) '2026-09-${i.toString().padLeft(2, '0')}'];
      final values = [for (var i = 0; i < 30; i++) i == 9 ? 42 : i % 3];
      await tester.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
          body: Align(
            alignment: Alignment.topLeft,
            child: SizedBox(
              width: 320,
              child: StatsLineChart(days: days, values: values, label: '播放'),
            ),
          ),
        ),
      ));
      // 默认显示最后一天
      expect(find.text('9/30 播放 2'), findsOneWidget);
      final box = tester.getRect(
          find.descendant(of: find.byType(StatsLineChart), matching: find.byType(CustomPaint)));
      expect(box.width, 320);
      // 第 10 天(下标 9)的 x:左留白 34,可画宽度 320-44
      final x = box.left + 34 + (320 - 44) * 9 / 29;
      await tester.tapAt(Offset(x, box.center.dy));
      await tester.pump();
      expect(find.text('9/10 播放 42'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
