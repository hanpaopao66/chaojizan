// 论坛的数据对象(DEV-PROMPTS-41 §8.1)。
//
// ## 守的是什么
//
// - **投票前看不到票数**:`votes` 和 `total` 是 null,不能拿 0 顶上 ——
//   0 票和「还看不到」是两回事,顶成 0 会画出一条「0%」的结果条;
// - 卡片查不到时只有 `{type, id, unavailable}`,要能认出来画灰条;
// - 串里的占位 `{pid, unavailable, reason}` 也是一条帖子,不能解析成空帖被跳过;
// - 引用不再嵌套引用,被引的没了时是一条占位;
// - 服务端多给字段、少给字段、给错类型都不能崩(旧客户端要活着)。
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:user_app/forum/models.dart';

/// §8.1 里那条帖子的真实形状,[over] 覆盖其中几项
Map<String, dynamic> postJson([Map<String, dynamic> over = const {}]) => {
      'pid': 'fpHbFUgZ3A32',
      'author': {'id': 42, 'name': '小王', 'username': 'xiaowang', 'avatar': '/img/a.jpg'},
      'text': '今天 #周末# 去哪 @xiaoming',
      'entities': {
        'tags': [
          {'tag': '周末', 'display': '周末'}
        ],
        'mentions': [
          {'id': 7, 'username': 'xiaoming'}
        ],
        'links': <String>[],
      },
      'media': [
        {'url': '/img/forum/u42-a.jpg', 'w': 1080, 'h': 1440}
      ],
      'card': null,
      'quote': null,
      'reply_to': null,
      'root_pid': 'fpHbFUgZ3A32',
      'poll': null,
      'reply_policy': 'all',
      'can_reply': true,
      'counts': {'replies': 1, 'reposts': 2, 'quotes': 0, 'likes': 9, 'bookmarks': 1, 'views': 120},
      'viewer': {'liked': false, 'reposted': false, 'bookmarked': false},
      'edited': false,
      'edited_at': null,
      'created_at': '2026-09-15T12:00:00+08:00',
      'pinned': false,
      ...over,
    };

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

  group('帖子', () {
    test('照 §8.1 的形状解出来', () {
      final p = FPost.fromJson(postJson());
      expect(p.pid, 'fpHbFUgZ3A32');
      expect(p.author?.name, '小王');
      expect(p.author?.username, 'xiaowang');
      expect(p.entities.tags.single.display, '周末');
      expect(p.entities.mentions.single.id, 7);
      expect(p.media.single.w, 1080);
      expect(p.media.single.aspect, closeTo(0.75, 0.001));
      expect(p.counts.likes, 9);
      expect(p.counts.views, 120);
      expect(p.viewer.liked, isFalse);
      expect(p.replyPolicyName, '所有人');
      expect(p.unavailable, isFalse);
    });

    test('少给字段不崩,给缺省值', () {
      final p = FPost.fromJson({'pid': 'fpX'});
      expect(p.text, '');
      expect(p.author, isNull);
      expect(p.media, isEmpty);
      expect(p.counts.likes, 0);
      expect(p.canReply, isTrue); // 没说不能回就是能回
      expect(p.replyPolicy, 'all');
    });

    test('整个不是 Map 也不崩', () {
      expect(FPost.fromJson(null).pid, '');
      expect(FPost.fromJson('坏数据').pid, '');
      expect(FPost.fromJson(const []).media, isEmpty);
    });

    test('多给字段照样解(服务端加字段不让旧客户端崩)', () {
      final p = FPost.fromJson(postJson({'brand_new_field': 1, 'counts': {'likes': 3, 'zzz': 9}}));
      expect(p.counts.likes, 3);
      expect(p.raw['brand_new_field'], 1);
    });

    test('媒体没给宽高时按 4:3 摆,不至于把高度算成 0', () {
      final p = FPost.fromJson(postJson({
        'media': [
          {'url': '/img/forum/x.jpg'}
        ]
      }));
      expect(p.media.single.aspect, closeTo(4 / 3, 0.001));
    });

    test('没给 media 的 url 也不崩', () {
      final p = FPost.fromJson(postJson({'media': ['不是对象']}));
      expect(p.media.single.url, '');
    });
  });

  group('占位条目', () {
    test('删了 / 下架了 / 拉黑的,三种原因各有一句中文', () {
      for (final e in const {
        'deleted': '这条帖子已删除',
        'removed': '这条帖子已下架',
        'blocked': '这条帖子看不到',
      }.entries) {
        final p = FPost.fromJson({'pid': 'fpX', 'unavailable': true, 'reason': e.key});
        expect(p.unavailable, isTrue);
        expect(p.unavailableText, e.value);
      }
    });

    test('没给 reason 时有兜底的一句', () {
      final p = FPost.fromJson({'pid': 'fpX', 'unavailable': true});
      expect(p.unavailableText, '这条帖子已不可见');
    });

    test('占位也是一条帖子:pid 在,不能被当成空的跳过', () {
      final p = FPost.fromJson({'pid': 'fpAAA', 'unavailable': true, 'reason': 'deleted'});
      expect(p.pid, 'fpAAA');
    });
  });

  group('卡片', () {
    test('有快照时标题封面都在', () {
      final p = FPost.fromJson(postJson({
        'card': {
          'type': 'track',
          'id': 'mtAbc',
          'title': '一首歌',
          'subtitle': '某位音乐人',
          'cover': '/img/c.jpg',
          'url': 'https://chaojizan.cc/music/t/mtAbc',
        }
      }));
      expect(p.card?.unavailable, isFalse);
      expect(p.card?.title, '一首歌');
      expect(p.card?.typeName, '歌曲');
    });

    test('查不到时 unavailable,还能说清是什么不见了', () {
      final p = FPost.fromJson(postJson({
        'card': {'type': 'playlist', 'id': 'mpAbc', 'unavailable': true}
      }));
      expect(p.card?.unavailable, isTrue);
      expect(p.card?.typeName, '歌单');
      expect(p.card?.title, '');
    });

    test('不认得的类型不崩,给一个中性的名字', () {
      final p = FPost.fromJson(postJson({
        'card': {'type': '还没做出来的东西', 'id': 'x'}
      }));
      expect(p.card?.typeName, '内容');
    });
  });

  group('引用', () {
    test('引用一条正常帖子', () {
      final p = FPost.fromJson(postJson({'quote': postJson({'pid': 'fpQuoted', 'text': '被引的'})}));
      expect(p.quote?.pid, 'fpQuoted');
      expect(p.quote?.text, '被引的');
      expect(p.quote?.unavailable, isFalse);
    });

    test('被引的没了:引用照样在,里面是一条占位', () {
      final p = FPost.fromJson(postJson({
        'quote': {'pid': 'fpGone', 'unavailable': true}
      }));
      expect(p.quote?.unavailable, isTrue);
      expect(p.quote?.pid, 'fpGone');
    });
  });

  group('投票三态', () {
    test('投票前:votes 和 total 是 null,看不到结果', () {
      final p = FPost.fromJson(postJson({
        'poll': {
          'options': [
            {'text': '甲', 'votes': null},
            {'text': '乙', 'votes': null},
          ],
          'total': null,
          'ends_at': '2026-09-16T12:00:00+08:00',
          'closed': false,
          'voted': null,
        }
      }));
      final poll = p.poll!;
      expect(poll.options.first.votes, isNull, reason: '不能把 null 顶成 0');
      expect(poll.total, isNull);
      expect(poll.showResults, isFalse);
      expect(poll.didVote, isFalse);
      expect(poll.canVote, isTrue);
      expect(poll.share(0), 0);
    });

    test('投过了:票数出来,我投的那项标出来,不能再投', () {
      final poll = FPoll.fromJson({
        'options': [
          {'text': '甲', 'votes': 3},
          {'text': '乙', 'votes': 1},
        ],
        'total': 4,
        'ends_at': '2026-09-16T12:00:00+08:00',
        'closed': false,
        'voted': 0,
      });
      expect(poll.showResults, isTrue);
      expect(poll.didVote, isTrue);
      expect(poll.voted, 0);
      expect(poll.canVote, isFalse);
      expect(poll.share(0), closeTo(0.75, 0.001));
      expect(poll.share(1), closeTo(0.25, 0.001));
    });

    test('结束了:没投过也看得到结果,但投不了', () {
      final poll = FPoll.fromJson({
        'options': [
          {'text': '甲', 'votes': 2},
          {'text': '乙', 'votes': 0},
        ],
        'total': 2,
        'closed': true,
        'voted': null,
      });
      expect(poll.showResults, isTrue);
      expect(poll.canVote, isFalse);
      expect(poll.share(1), 0);
      expect(fPollLeft(poll), '已结束');
    });

    test('一票没有时占比是 0,不除以 0', () {
      final poll = FPoll.fromJson({
        'options': [
          {'text': '甲', 'votes': 0}
        ],
        'total': 0,
        'closed': true,
      });
      expect(poll.share(0), 0);
      expect(poll.share(9), 0, reason: '越界也给 0');
    });

    test('还剩多久:天 / 小时 / 分钟 / 已结束', () {
      final now = DateTime(2026, 9, 15, 12);
      FPoll at(Duration d) => FPoll(endsAt: now.add(d));
      expect(fPollLeft(at(const Duration(days: 2)), now: now), '还有 2 天');
      expect(fPollLeft(at(const Duration(hours: 3)), now: now), '还有 3 小时');
      expect(fPollLeft(at(const Duration(minutes: 12)), now: now), '还有 12 分钟');
      expect(fPollLeft(at(const Duration(seconds: -1)), now: now), '已结束');
    });
  });

  group('时间线条目', () {
    test('普通帖子条目', () {
      final item = FTimelineItem.fromJson({'type': 'post', 'post': postJson()});
      expect(item.isRepost, isFalse);
      expect(item.post.pid, 'fpHbFUgZ3A32');
      expect(item.by, isNull);
    });

    test('转发条目:谁转的、什么时候转的,帖子还是原作者的', () {
      final item = FTimelineItem.fromJson({
        'type': 'repost',
        'by': {'id': 9, 'name': '小李', 'username': 'xiaoli', 'avatar': ''},
        'at': '2026-09-15T13:00:00+08:00',
        'post': postJson(),
      });
      expect(item.isRepost, isTrue);
      expect(item.by?.name, '小李');
      expect(item.at, isNotNull);
      expect(item.post.author?.name, '小王', reason: '转发条目里的帖子还是原作者的');
    });

    test('裸帖子(书签、话题、回复这些接口)也能当条目', () {
      final item = FTimelineItem.fromJson(postJson());
      expect(item.isRepost, isFalse);
      expect(item.post.pid, 'fpHbFUgZ3A32');
    });

    test('不认得的 type 当普通帖子处理,不崩', () {
      final item = FTimelineItem.fromJson({'type': '将来才有的类型', 'post': postJson()});
      expect(item.type, 'post');
      expect(item.post.pid, 'fpHbFUgZ3A32');
    });
  });

  group('推荐的中间量', () {
    test('服务端给了 why 就用它的原话', () {
      expect(fRankWhy({'score': 1.2, 'why': '你关注的人发的'}), '你关注的人发的');
    });

    test('只给 parts 时自己拼一句', () {
      expect(
        fRankWhy({
          'parts': {'likes': 5, 'reposts': 2, 'quotes': 0, 'repliers': 1}
        }),
        '5 人赞、2 人转发、1 人回复',
      );
    });

    test('什么都没有时给空串,不画那一行', () {
      expect(fRankWhy(const {}), '');
      expect(fRankWhy({'parts': <String, dynamic>{}}), '');
    });

    test('parts 里的数是字符串也不崩', () {
      expect(fRankWhy({'parts': {'likes': '3'}}), '3 人赞');
    });
  });

  group('编辑窗口', () {
    test('30 分钟内、不到 5 次能改', () {
      final now = DateTime(2026, 9, 15, 12);
      final p = FPost.fromJson(postJson(
          {'created_at': now.subtract(const Duration(minutes: 10)).toIso8601String(), 'edit_count': 2}));
      expect(fCanEdit(p, now: now), isTrue);
    });

    test('超过 30 分钟不能改', () {
      final now = DateTime(2026, 9, 15, 12);
      final p = FPost.fromJson(
          postJson({'created_at': now.subtract(const Duration(minutes: 31)).toIso8601String()}));
      expect(fCanEdit(p, now: now), isFalse);
    });

    test('改满 5 次不能再改', () {
      final now = DateTime(2026, 9, 15, 12);
      final p = FPost.fromJson(postJson(
          {'created_at': now.subtract(const Duration(minutes: 1)).toIso8601String(), 'edit_count': 5}));
      expect(fCanEdit(p, now: now), isFalse);
    });

    test('占位条目不能改', () {
      expect(fCanEdit(FPost.fromJson({'pid': 'fpX', 'unavailable': true})), isFalse);
    });
  });

  group('主页', () {
    test('置顶那条在,关注状态和数字都在', () {
      final p = FProfile.fromJson({
        'user': {'id': 42, 'name': '小王', 'username': 'xiaowang', 'avatar': ''},
        'bio': '随便写写',
        'joined_at': '2026-01-01T00:00:00+08:00',
        'posts': 12,
        'following': 3,
        'fans': 20,
        'followed': true,
        'follows_you': true,
        'pinned': postJson({'pid': 'fpPinned', 'pinned': true}),
      });
      expect(p.user.name, '小王');
      expect(p.fans, 20);
      expect(p.followed, isTrue);
      expect(p.followsYou, isTrue);
      expect(p.pinned?.pid, 'fpPinned');
      expect(p.pinned?.pinned, isTrue);
    });

    test('没有置顶时是 null', () {
      final p = FProfile.fromJson({
        'user': {'id': 1, 'name': 'a'},
        'pinned': null,
      });
      expect(p.pinned, isNull);
      expect(p.bio, '');
    });
  });

  group('热门话题', () {
    test('照 §8.3 的形状解', () {
      final t = FTrendingTag.fromJson(
          {'tag': '周末', 'display': '周末', 'authors_24h': 12, 'authors_3h': 4, 'score': 20.0});
      expect(t.tag, '周末');
      expect(t.authors24h, 12);
      expect(t.score, 20.0);
    });

    test('score 是字符串或缺失也不崩', () {
      expect(FTrendingTag.fromJson({'tag': 'a', 'score': '3.5'}).score, 3.5);
      expect(FTrendingTag.fromJson({'tag': 'a'}).score, 0);
      expect(FTrendingTag.fromJson({'tag': 'a'}).display, 'a', reason: '没给 display 就用 tag');
    });
  });
}
