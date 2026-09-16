// 论坛正文的实体切片(DEV-PROMPTS-41 #381、§5.6)。
//
// ## 守的是什么
//
// - 话题两种写法都认:`#话题#`(闭合)和 `#话题`(到空白、井号或中英文标点为止);
// - **只照服务端给的实体画**:服务端没给的,长得再像也不画成可点的 ——
//   点了也跳不到地方,而且客户端自己认会和服务端的正则慢慢长歪;
// - 中文标点边界:`#周末,吃什么` 里话题到逗号为止,`#周末快乐` 整个是一个话题,
//   不能从它里面切出一个 `#周末`;
// - @超级赞号后面还跟着号里合法的字符时不算(服务端认的是更长的那个号);
// - 正文字数按 Unicode 字符数(emoji 算 1 个),不是 UTF-16 码元数。
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:user_app/forum/entities.dart';
import 'package:user_app/forum/models.dart';

FEntities ents({List<String> tags = const [], List<String> ats = const [], List<String> links = const []}) =>
    FEntities(
      tags: [for (final t in tags) FTag(t.toLowerCase(), t)],
      mentions: [for (var i = 0; i < ats.length; i++) FMention(100 + i, ats[i])],
      links: links,
    );

/// 把切片摊成 `kind:文字` 的列表,断言好读
List<String> shape(String text, FEntities e) =>
    [for (final s in forumSegments(text, e)) '${s.kind.name}:${s.text}'];

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

  group('话题', () {
    test('闭合写法 #话题# 整段可点,井号也在片段里', () {
      expect(shape('今天 #周末# 去哪', ents(tags: ['周末'])),
          ['plain:今天 ', 'tag:#周末#', 'plain: 去哪']);
    });

    test('开放写法 #话题 到空格为止', () {
      expect(shape('今天 #周末 去哪', ents(tags: ['周末'])),
          ['plain:今天 ', 'tag:#周末', 'plain: 去哪']);
    });

    test('开放写法到中文逗号为止', () {
      expect(shape('#周末,吃什么', ents(tags: ['周末'])), ['tag:#周末', 'plain:,吃什么']);
    });

    test('开放写法到中文句号、感叹号、顿号为止', () {
      expect(shape('#周末。', ents(tags: ['周末'])), ['tag:#周末', 'plain:。']);
      expect(shape('#周末!', ents(tags: ['周末'])), ['tag:#周末', 'plain:!']);
      expect(shape('#周末、#工作日', ents(tags: ['周末', '工作日'])),
          ['tag:#周末', 'plain:、', 'tag:#工作日']);
    });

    test('英文标点也截止', () {
      expect(shape('#weekend, ok', ents(tags: ['weekend'])), ['tag:#weekend', 'plain:, ok']);
    });

    test('到结尾为止', () {
      expect(shape('走起 #周末', ents(tags: ['周末'])), ['plain:走起 ', 'tag:#周末']);
    });

    test('#周末快乐 不能切出一个 #周末 —— 服务端认的是整个词', () {
      // 服务端给的实体是「周末快乐」,正文里的 #周末 后面还跟着字,不是那个话题
      expect(shape('#周末快乐', ents(tags: ['周末快乐'])), ['tag:#周末快乐']);
      // 反过来:服务端只给了「周末」,而正文是 #周末快乐 —— 一个字都不画
      expect(shape('#周末快乐', ents(tags: ['周末'])), ['plain:#周末快乐']);
    });

    test('服务端没给的话题不画(超过 10 个之后的那些)', () {
      expect(shape('#甲 #乙', ents(tags: ['甲'])), ['tag:#甲', 'plain: #乙']);
    });

    test('同一个话题出现两次,两处都可点', () {
      expect(shape('#周末 和 #周末', ents(tags: ['周末'])),
          ['tag:#周末', 'plain: 和 ', 'tag:#周末']);
    });

    test('大小写:tag 是小写规范形,显示还是作者写的样子', () {
      final segs = forumSegments('聊聊 #Flutter', ents(tags: ['Flutter']));
      final tag = segs.firstWhere((s) => s.kind == FSegmentKind.tag);
      expect(tag.text, '#Flutter');
      expect(tag.value, 'flutter');
    });
  });

  group('提及', () {
    test('@超级赞号 可点,后面跟标点没关系', () {
      expect(shape('喊一下 @xiaoming,你看', ents(ats: ['xiaoming'])),
          ['plain:喊一下 ', 'mention:@xiaoming', 'plain:,你看']);
    });

    test('后面还跟着号里合法的字符时不算', () {
      // 服务端解析出来的是 xiaoming,而正文里是 @xiaoming2 —— 那是另一个号
      expect(shape('@xiaoming2', ents(ats: ['xiaoming'])), ['plain:@xiaoming2']);
      expect(shape('@xiaoming_x', ents(ats: ['xiaoming'])), ['plain:@xiaoming_x']);
    });

    test('查不到人的 @ 不画(服务端不给实体)', () {
      expect(shape('@nobodyhere 在吗', ents()), ['plain:@nobodyhere 在吗']);
    });

    test('点中的提及能对回它的用户号', () {
      final segs = forumSegments('@xiaoming', ents(ats: ['xiaoming']));
      expect(segs.single.value, 'xiaoming');
      expect(segs.single.kind, FSegmentKind.mention);
    });
  });

  group('链接', () {
    test('链接整段可点', () {
      expect(shape('看这个 https://example.com/a 挺好', ents(links: ['https://example.com/a'])),
          ['plain:看这个 ', 'link:https://example.com/a', 'plain: 挺好']);
    });

    test('链接里的 #锚点 不会被切成话题 —— 起点靠前的赢', () {
      expect(
        shape('https://example.com/a#周末', ents(tags: ['周末'], links: ['https://example.com/a#周末'])),
        ['link:https://example.com/a#周末'],
      );
    });

    test('链接、话题、提及混在一条里', () {
      expect(
        shape('@xiaoming 看 #周末# https://a.cc 走',
            ents(tags: ['周末'], ats: ['xiaoming'], links: ['https://a.cc'])),
        ['mention:@xiaoming', 'plain: 看 ', 'tag:#周末#', 'plain: ', 'link:https://a.cc', 'plain: 走'],
      );
    });
  });

  group('没有实体', () {
    test('一段普通字', () {
      expect(shape('就是一句话', const FEntities()), ['plain:就是一句话']);
    });

    test('空正文给空列表(纯图 / 卡片 / 投票的帖子)', () {
      expect(forumSegments('', ents(tags: ['周末'])), isEmpty);
    });
  });

  group('字数与校验', () {
    test('按 Unicode 字符数:emoji 算 1 个,不是 2 个', () {
      expect(forumTextLength('😀'), 1);
      expect('😀'.length, 2); // UTF-16 码元数是 2 —— 这就是不能用 length 的原因
      expect(forumTextLength('中文 abc'), 6);
    });

    test('首尾空白不算', () {
      expect(forumTextLength('  哈  '), 1);
      expect(forumTextLength('   '), 0);
    });

    test('500 字正好能发,501 字不行', () {
      expect(forumTextError('字' * kPostMaxChars), isNull);
      final e = forumTextError('字' * (kPostMaxChars + 1));
      expect(e, contains('500'));
      expect(e, contains('501'));
    });

    test('空正文要有图 / 卡片 / 投票才行', () {
      expect(forumTextError(''), '写点什么吧');
      expect(forumTextError('', hasMedia: true), isNull);
      expect(forumTextError('', hasCard: true), isNull);
      expect(forumTextError('', hasPoll: true), isNull);
    });
  });
}
