// 音乐模块的数据对象(DEV-PROMPTS-41 §8.1):容错解析、音质回落、地址过期判定、站内链接。
//
// 解析这一层的价值全在「服务端少给一个字段时不崩」—— 所以每组都有一条只喂半截 JSON 的。
import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/music/models.dart';
import 'package:user_app/music/nav.dart';

void main() {
  group('歌曲解析', () {
    final full = {
      'tid': 'mtHbFUgZ3A32',
      'title': '晚风',
      'duration_ms': 215000,
      'cover': '/img/music_cover/a.jpg',
      'explicit': false,
      'genre': 'pop',
      'genre_name': '流行',
      'plays': 1234,
      'likes': 56,
      'comments': 7,
      'liked': true,
      'artist': {'aid': 'maHbFUgZ3A32', 'name': '小林', 'user_id': 42},
      'release': {'rid': 'mrHbFUgZ3A32', 'title': '夏天', 'kind': 'single'},
      'published_at': '2026-09-15T12:00:00+08:00',
    };

    test('整条都在时逐项对上', () {
      final t = MTrack.fromJson(full);
      expect(t.tid, 'mtHbFUgZ3A32');
      expect(t.title, '晚风');
      expect(t.durationMs, 215000);
      expect(t.genreName, '流行');
      expect(t.plays, 1234);
      expect(t.liked, isTrue);
      expect(t.artist!.name, '小林');
      expect(t.artist!.userId, 42);
      expect(t.release!.kind, 'single');
      expect(t.publishedAt, isNotNull);
    });

    test('只有 tid 和标题也不崩,其余给缺省值', () {
      final t = MTrack.fromJson({'tid': 'mtA', 'title': '无名'});
      expect(t.durationMs, 0);
      expect(t.cover, '');
      expect(t.liked, isFalse);
      expect(t.artist, isNull);
      expect(t.release, isNull);
      expect(t.rank, isNull);
      expect(t.artistName, '');
      // 没给转码状态的(浏览接口)当已就绪,不能把线上的歌显示成「排队中」
      expect(t.transcodeReady, isTrue);
    });

    test('完全不是对象时给空壳', () {
      final t = MTrack.fromJson('不是 JSON 对象');
      expect(t.tid, '');
      expect(t.title, '');
    });

    test('音乐人中心的歌带转码状态', () {
      final t = MTrack.fromJson({
        'tid': 'mtA',
        'title': '半成品',
        'transcode_status': 'processing',
        'track_no': 2,
        'declaration': 'original',
      });
      expect(t.transcodeReady, isFalse);
      expect(t.trackNo, 2);
      expect(mTranscodeName(t.transcodeStatus), '转码中');
      expect(mDeclarationName(t.declaration), '原创');
    });

    test('「歌名 - 歌手」没有歌手时只剩歌名', () {
      expect(mTrackLine(MTrack.fromJson(full)), '晚风 - 小林');
      expect(mTrackLine(MTrack.fromJson({'tid': 'x', 'title': '晚风'})), '晚风');
    });
  });

  group('播放地址', () {
    test('要高品质而 hq 为空时回落标准(§8.2 hq 可为 null)', () {
      final s = MStream.fromJson({'std': '/music/v1/stream/mtA/std.m4a', 'hq': null});
      expect(s.hq, isNull);
      expect(s.urlFor(kQualityHq), '/music/v1/stream/mtA/std.m4a');
      expect(s.urlFor(kQualityStd), '/music/v1/stream/mtA/std.m4a');
    });

    test('有 hq 时按音质各取各的', () {
      final s = MStream.fromJson({'std': 'a.m4a', 'hq': 'b.m4a'});
      expect(s.urlFor(kQualityHq), 'b.m4a');
      expect(s.urlFor(kQualityStd), 'a.m4a');
    });

    test('到期判定留两分钟余量:卡在到期那一秒去播必然 403', () {
      final now = DateTime(2026, 9, 15, 12, 0);
      final soon = MStream(std: 'a', expiresAt: now.add(const Duration(minutes: 1)));
      final later = MStream(std: 'a', expiresAt: now.add(const Duration(hours: 5)));
      expect(soon.expiredBy(now), isTrue);
      expect(later.expiredBy(now), isFalse);
      // 服务端没给到期时间时不主动重签(不知道就别瞎猜)
      expect(const MStream(std: 'a').expiredBy(now), isFalse);
    });
  });

  group('作品与歌单', () {
    test('作品:能改的只有草稿 / 未通过 / 已下架(§5.3)', () {
      for (final s in ['draft', 'rejected', 'withdrawn']) {
        expect(MRelease.fromJson({'rid': 'mrA', 'title': 'x', 'status': s}).editable, isTrue, reason: s);
      }
      for (final s in ['reviewing', 'published', 'removed']) {
        expect(MRelease.fromJson({'rid': 'mrA', 'title': 'x', 'status': s}).editable, isFalse, reason: s);
      }
    });

    test('作品:没给 track_count 时按 tracks 的条数算', () {
      final r = MRelease.fromJson({
        'rid': 'mrA',
        'title': '夏天',
        'tracks': [
          {'tid': 'mt1', 'title': 'a'},
          {'tid': 'mt2', 'title': 'b'},
        ],
      });
      expect(r.trackCount, 2);
      expect(r.tracks.length, 2);
    });

    test('歌单:owner 走人物简卡,is_public 缺省公开', () {
      final p = MPlaylist.fromJson({
        'pid': 'mpHbFUgZ3A32',
        'title': '通勤',
        'owner': {'id': 7, 'name': '小明', 'username': 'xiaoming'},
        'tags': ['华语', '流行'],
      });
      expect(p.owner!.id, 7);
      expect(p.owner!.username, 'xiaoming');
      expect(p.tags, ['华语', '流行']);
      expect(p.isPublic, isTrue);
      expect(MPlaylist.fromJson({'pid': 'x', 'title': 'y', 'is_public': false}).isPublic, isFalse);
    });

    test('作品类型和状态的中文', () {
      expect(mReleaseKindName('album'), '专辑');
      expect(mReleaseKindName('ep'), 'EP');
      expect(mReleaseKindName('single'), '单曲');
      expect(mReleaseKindName('乱写的'), '单曲');
      expect(mReleaseStatusName('reviewing'), '审核中');
      expect(mReleaseStatusName('removed'), '被下架');
    });
  });

  group('算分中间量与榜单', () {
    test('rank 带 score / parts / why(§5.4 每一项都要带)', () {
      final r = MRank.fromJson({
        'score': 152.5,
        'parts': {'listeners_7d': 35, 'likes_7d': 4},
        'why': '近7天 35 人收听、4 人加入歌单',
      });
      expect(r.score, 152.5);
      expect(r.parts['listeners_7d'], 35);
      expect(r.why, '近7天 35 人收听、4 人加入歌单');
      expect(r.isEmpty, isFalse);
      expect(MRank.fromJson(null).isEmpty, isTrue);
    });

    test('榜单条目:rank 放在条目上或歌上都认', () {
      final onEntry = MChartEntry.fromJson({
        'rank_no': 1,
        'track': {'tid': 'mtA', 'title': 'a'},
        'rank': {'score': 9, 'why': '甲'},
      });
      expect(onEntry.rankNo, 1);
      expect(onEntry.rank!.why, '甲');

      final onTrack = MChartEntry.fromJson({
        'rank_no': 2,
        'track': {
          'tid': 'mtB',
          'title': 'b',
          'rank': {'score': 8, 'why': '乙'}
        },
      });
      expect(onTrack.rank!.why, '乙');
    });
  });

  group('发现页一屏', () {
    test('缺整块时是空列表,不是 null', () {
      final h = MHome.fromJson({
        'daily': [
          {'tid': 'mt1', 'title': 'a'}
        ],
        'charts': [
          {
            'key': 'hot',
            'name': '热歌榜',
            'top': [
              {'tid': 'mt2', 'title': 'b'}
            ]
          }
        ],
      });
      expect(h.daily.length, 1);
      expect(h.playlists, isEmpty);
      expect(h.newTracks, isEmpty);
      expect(h.genres, isEmpty);
      expect(h.charts.single.top.single.title, 'b');
      // 服务端没说就当个性化开着(关了才会明说)
      expect(h.dailyPersonalized, isTrue);
      expect(MHome.fromJson({'daily_personalized': false}).dailyPersonalized, isFalse);
    });
  });

  group('署名', () {
    test('只摊出填了的那几项,空白名字丢掉', () {
      final lines = mCreditLines({
        'lyricist': ['小林', ' '],
        'composer': [],
        'arranger': ['阿元', '小周'],
      });
      expect(lines.map((e) => e.label).toList(), ['作词', '编曲']);
      expect(lines[0].names, '小林');
      expect(lines[1].names, '阿元、小周');
    });

    test('完全没有署名时是空', () => expect(mCreditLines(const {}), isEmpty));
  });

  group('站内链接(§5.1)', () {
    ({String type, String id})? parse(String s) => musicLinkOf(Uri.parse(s));

    test('四种对象各认一条', () {
      expect(parse('https://chaojizan.cc/music/t/mtHbFUgZ3A32'), (type: 'track', id: 'mtHbFUgZ3A32'));
      expect(parse('https://chaojizan.cc/music/r/mrHbFUgZ3A32'), (type: 'release', id: 'mrHbFUgZ3A32'));
      expect(parse('https://www.chaojizan.cc/music/p/mpHbFUgZ3A32'), (type: 'playlist', id: 'mpHbFUgZ3A32'));
      expect(parse('https://chaojizan.cc/music/a/maHbFUgZ3A32'), (type: 'artist', id: 'maHbFUgZ3A32'));
    });

    test('长得像本站的域名不认', () {
      expect(parse('https://chaojizan.cc.evil.example/music/t/mtHbFUgZ3A32'), isNull);
      expect(parse('https://evil.example/music/t/mtHbFUgZ3A32'), isNull);
    });

    test('路径那一段和编号前缀对不上的不认', () {
      expect(parse('https://chaojizan.cc/music/t/mpHbFUgZ3A32'), isNull);
      expect(parse('https://chaojizan.cc/music/x/mtHbFUgZ3A32'), isNull);
    });

    test('编号形状不对的不认(长度、base58 里没有的字符)', () {
      expect(parse('https://chaojizan.cc/music/t/mtHbFUgZ3A3'), isNull);
      expect(parse('https://chaojizan.cc/music/t/mt0OIl123456'), isNull);
      expect(parse('https://chaojizan.cc/music/t/123'), isNull);
    });

    test('别的板块的链接不认', () {
      expect(parse('https://chaojizan.cc/v/svHbFUgZ3A32'), isNull);
      expect(parse('https://chaojizan.cc/music'), isNull);
      expect(parse('https://chaojizan.cc/music/t'), isNull);
    });

    test('分享链接和解析是一对', () {
      for (final t in ['track', 'release', 'playlist', 'artist']) {
        final id = '${{'track': 'mt', 'release': 'mr', 'playlist': 'mp', 'artist': 'ma'}[t]}HbFUgZ3A32';
        expect(parse(musicLinkFor(t, id)), (type: t, id: id));
      }
    });
  });
}
