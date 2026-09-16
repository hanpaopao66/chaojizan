// 发帖页的校验和草稿(DEV-PROMPTS-41 F1、F3、§5.6)。
//
// ## 守的是什么
//
// - 500 字上限按 Unicode 字符数;超了要**看得见「−3」**再自己删,不许偷偷截掉;
// - 图片最多 4 张;还在传、传失败的时候不许发(发出去会是一条缺图的帖子);
// - 投票 2–4 项、每项 ≤ 25 字、不能重复、时长 5 分钟–7 天;
// - 空正文只有在有图 / 卡片 / 投票时才行;
// - 编辑时图和投票动不了(F3),只判正文;
// - @ / # 联想的判据:光标前最近的那个 @ 或 #,到光标之间没有空白,
//   而且它前面是开头或空白(不然邮箱地址 `a@b` 也会弹联想)。
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:user_app/forum/compose_form.dart';
import 'package:user_app/forum/models.dart';

ComposeImage done(String url) => ComposeImage(name: 'a.jpg', url: url, progress: 1);
ComposeImage uploading() => ComposeImage(name: 'a.jpg');
ComposeImage failed() => ComposeImage(name: 'a.jpg', error: '上传失败');

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

  group('字数', () {
    test('一句话能发', () {
      expect(ComposeDraft(text: '今天天气不错').canSend, isTrue);
    });

    test('空的发不了', () {
      final d = ComposeDraft();
      expect(d.canSend, isFalse);
      expect(d.error, '写点什么吧');
    });

    test('只有空格也发不了', () {
      expect(ComposeDraft(text: '   \n  ').canSend, isFalse);
    });

    test('500 字能发,501 字不行', () {
      expect(ComposeDraft(text: '字' * 500).canSend, isTrue);
      final d = ComposeDraft(text: '字' * 501);
      expect(d.canSend, isFalse);
      expect(d.remaining, -1);
    });

    test('剩几个字的数是按 Unicode 字符算的', () {
      expect(ComposeDraft(text: '😀😀').remaining, kPostMaxChars - 2);
    });
  });

  group('图片', () {
    test('有图时正文可以是空的', () {
      expect(ComposeDraft(images: [done('/img/forum/a.jpg')]).canSend, isTrue);
    });

    test('4 张能发,5 张不行', () {
      final four = ComposeDraft(text: 'x', images: [for (var i = 0; i < 4; i++) done('/img/$i.jpg')]);
      expect(four.canSend, isTrue);
      expect(four.canAddImage, isFalse, reason: '满 4 张之后不能再加');

      final five = ComposeDraft(text: 'x', images: [for (var i = 0; i < 5; i++) done('/img/$i.jpg')]);
      expect(five.canSend, isFalse);
      expect(five.error, contains('4'));
    });

    test('还在传的时候不能发', () {
      final d = ComposeDraft(text: 'x', images: [uploading()]);
      expect(d.uploading, isTrue);
      expect(d.error, '图片还在上传');
    });

    test('有传失败的图时不能发,要先删掉', () {
      final d = ComposeDraft(text: 'x', images: [failed()]);
      expect(d.uploading, isFalse, reason: '失败了就不算「还在传」,不然永远卡着');
      expect(d.error, contains('没传上去'));
    });

    test('发出去的只有传完的那些地址', () {
      final d = ComposeDraft(text: 'x', images: [done('/img/a.jpg'), uploading()]);
      expect(d.mediaUrls, ['/img/a.jpg']);
    });
  });

  group('卡片', () {
    test('只带一张卡片、不写字也能发', () {
      expect(ComposeDraft(card: {'type': 'track', 'id': 'mtA'}).canSend, isTrue);
    });
  });

  group('投票', () {
    test('两项填好了能发', () {
      final d = ComposeDraft(text: '选哪个', poll: ComposePoll(options: ['甲', '乙']));
      expect(d.canSend, isTrue);
    });

    test('只填了一项不行', () {
      final d = ComposeDraft(text: 'x', poll: ComposePoll(options: ['甲', '']));
      expect(d.error, contains('至少'));
    });

    test('最多 4 项', () {
      final poll = ComposePoll(options: ['甲', '乙', '丙', '丁']);
      expect(poll.canAdd, isFalse);
      expect(poll.error, isNull);
      expect(ComposePoll(options: ['甲', '乙', '丙', '丁', '戊']).error, contains('最多'));
    });

    test('前两项去不掉(至少要 2 项)', () {
      expect(ComposePoll(options: ['甲', '乙']).canRemove, isFalse);
      expect(ComposePoll(options: ['甲', '乙', '丙']).canRemove, isTrue);
    });

    test('每项最多 25 字', () {
      expect(ComposePoll(options: ['字' * 25, '乙']).error, isNull);
      expect(ComposePoll(options: ['字' * 26, '乙']).error, contains('25'));
    });

    test('两项写得一样不行', () {
      expect(ComposePoll(options: ['甲', '甲']).error, contains('一样'));
    });

    test('时长 5 分钟到 7 天', () {
      expect(ComposePoll(options: ['甲', '乙'], minutes: 5).error, isNull);
      expect(ComposePoll(options: ['甲', '乙'], minutes: 4).error, contains('最短'));
      expect(ComposePoll(options: ['甲', '乙'], minutes: kPollMaxMinutes).error, isNull);
      expect(ComposePoll(options: ['甲', '乙'], minutes: kPollMaxMinutes + 1).error, contains('7 天'));
    });

    test('有投票时正文可以是空的', () {
      expect(ComposeDraft(poll: ComposePoll(options: ['甲', '乙'])).canSend, isTrue);
    });

    test('选项两边的空格会去掉', () {
      expect(ComposePoll(options: ['  甲  ', '乙']).filled, ['甲', '乙']);
    });
  });

  group('编辑', () {
    test('改正文时图和投票动不了', () {
      final d = ComposeDraft(text: '改过的', editing: true, images: [done('/img/a.jpg')]);
      expect(d.canAddImage, isFalse);
      expect(d.canSend, isTrue);
    });

    test('原帖有图时,改成空正文也行', () {
      expect(ComposeDraft(text: '', editing: true, images: [done('/img/a.jpg')]).canSend, isTrue);
    });

    test('原帖没图时不能把正文清空', () {
      expect(ComposeDraft(text: '', editing: true).canSend, isFalse);
    });
  });

  group('回复和引用', () {
    test('回复和引用各自认得出来', () {
      expect(ComposeDraft(text: 'x', replyToPid: 'fpA').isReply, isTrue);
      expect(ComposeDraft(text: 'x', quotePid: 'fpA').isQuote, isTrue);
      expect(ComposeDraft(text: 'x').isReply, isFalse);
    });
  });

  group('退出时问不问', () {
    test('什么都没写就不问', () {
      expect(ComposeDraft().dirty, isFalse);
      expect(ComposeDraft(text: '   ').dirty, isFalse);
    });

    test('写了字、加了图、开了投票、带了卡片都要问', () {
      expect(ComposeDraft(text: '半句').dirty, isTrue);
      expect(ComposeDraft(images: [uploading()]).dirty, isTrue);
      expect(ComposeDraft(poll: ComposePoll()).dirty, isTrue);
      expect(ComposeDraft(card: {'type': 'post', 'id': 'fpA'}).dirty, isTrue);
    });
  });

  group('@ 和 # 联想', () {
    ({String kind, int start, String query})? q(String text) =>
        composeMentionQuery(text, text.length);

    test('正在打 @ 时弹人的联想', () {
      final r = q('喊一下 @xiao');
      expect(r?.kind, '@');
      expect(r?.query, 'xiao');
      expect(r?.start, '喊一下 '.length);
    });

    test('正在打 # 时弹话题的联想', () {
      final r = q('聊聊 #周');
      expect(r?.kind, '#');
      expect(r?.query, '周');
    });

    test('刚打了个 @ 还没打字:认得出来,但先不查', () {
      final r = q('@');
      expect(r?.kind, '@');
      expect(r?.query, '');
    });

    test('@ 前面不是空白时不弹(邮箱地址、代码里的 @)', () {
      expect(q('a@b'), isNull);
      expect(q('user@example.com'), isNull);
    });

    test('打完一个空格就不弹了', () {
      expect(q('@xiaoming 你好'), isNull);
    });

    test('光标在正文中间时按光标算,不按整句算', () {
      const text = '@xiao 后面还有字';
      final r = composeMentionQuery(text, 5); // 光标停在 @xiao 后面
      expect(r?.query, 'xiao');
    });

    test('打得太长就不弹了(话题最多 30 字)', () {
      expect(q('#${'字' * 31}'), isNull);
    });

    test('选中一条填回去:替换掉已经打的那一段,后面补一个空格', () {
      const text = '喊一下 @xiao';
      final r = composeApplySuggestion(text, 4, text.length, '@', 'xiaoming');
      expect(r.text, '喊一下 @xiaoming ');
      expect(r.cursor, r.text.length);
    });

    test('填回去时后面的字留着', () {
      const text = '@xiao 后面还有字';
      final r = composeApplySuggestion(text, 0, 5, '@', 'xiaoming');
      expect(r.text, '@xiaoming  后面还有字');
      expect(r.cursor, '@xiaoming '.length);
    });
  });
}
