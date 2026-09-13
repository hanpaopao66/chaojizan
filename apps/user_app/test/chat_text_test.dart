// 消息模块的纯函数:Markdown 记号、实体平移、时间 / 大小 / 时长格式、大表情判定。
import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/chat/models.dart';
import 'package:user_app/chat/ui/entity_controller.dart';
import 'package:user_app/chat/ui/format.dart';

String _dump(List<MsgEntity> es) =>
    es.map((e) => '${e.type}@${e.offset}+${e.length}${e.language != null ? '(${e.language})' : ''}').join(' ');

void main() {
  group('parseMarkdown', () {
    test('四种成对记号', () {
      final (t, e) = parseMarkdown('a **b** __c__ ~~d~~ ||e||', const []);
      expect(t, 'a b c d e');
      expect(_dump(e), 'bold@2+1 italic@4+1 strike@6+1 spoiler@8+1');
    });

    test('行内代码里面不解析', () {
      final (t, e) = parseMarkdown('run `x **y**` now', const []);
      expect(t, 'run x **y** now');
      expect(_dump(e), 'code@4+7');
    });

    test('代码块带语言,首尾换行去掉,缩进保留', () {
      final (t, e) = parseMarkdown('```dart\n  var a = 1;\n```', const []);
      expect(t, '  var a = 1;');
      expect(_dump(e), 'pre@0+12(dart)');
    });

    test('嵌套:粗体里有斜体', () {
      final (t, e) = parseMarkdown('**bold __it__**', const []);
      expect(t, 'bold it');
      expect(_dump(e), 'bold@0+7 italic@5+2');
    });

    test('不误伤:算式、蛇形命名、链接里的下划线', () {
      expect(parseMarkdown('2 ** 3 ** 4', const []).$1, '2 ** 3 ** 4');
      expect(parseMarkdown('snake__case__name', const []).$1, 'snake__case__name');
      final url = 'see https://x.com/__init__/y ok';
      expect(parseMarkdown(url, const []).$1, url);
      expect(parseMarkdown('****', const []).$1, '****');
    });

    test('偏移按 UTF-16:emoji 占两个码元', () {
      final (t, e) = parseMarkdown('😀 **hi**', const []);
      expect(t, '😀 hi');
      expect(_dump(e), 'bold@3+2');
    });

    test('手动加的格式跟着挪', () {
      // 「x **y** z」里 z 是用户选中加的斜体(offset 8)
      final (t, e) = parseMarkdown('x **y** z', const [MsgEntity('italic', 8, 1)]);
      expect(t, 'x y z');
      expect(_dump(e), 'bold@2+1 italic@4+1');
    });

    test('首尾空白去掉,实体跟着挪', () {
      final (t, e) = parseMarkdown('  **a** b \n', const []);
      expect(t, 'a b');
      expect(_dump(e), 'bold@0+1');
    });
  });

  group('shiftEntities', () {
    const bold = MsgEntity('bold', 2, 3); // 「ab[cde]f」
    test('实体前面插字:整体后移', () {
      expect(_dump(shiftEntities([bold], 'abcdef', 'XXabcdef')), 'bold@4+3');
    });
    test('实体里面打字:变长', () {
      expect(_dump(shiftEntities([bold], 'abcdef', 'abcXdef')), 'bold@2+4');
    });
    test('删掉一部分:裁掉', () {
      expect(_dump(shiftEntities([bold], 'abcdef', 'abef')), 'bold@2+1');
    });
    test('整段删掉:实体没了', () {
      expect(shiftEntities([bold], 'abcdef', 'abf'), isEmpty);
    });
  });

  group('format', () {
    final now = DateTime(2026, 9, 12, 18, 30); // 周六
    test('listTime', () {
      expect(listTime(DateTime(2026, 9, 12, 8, 5), now), '08:05');
      expect(listTime(DateTime(2026, 9, 11, 23, 0), now), '昨天');
      expect(listTime(DateTime(2026, 9, 8, 9, 0), now), '周二');
      expect(listTime(DateTime(2026, 3, 1), now), '3/1');
      expect(listTime(DateTime(2025, 12, 31), now), '2025/12/31');
    });
    test('dayLabel', () {
      expect(dayLabel(DateTime(2026, 9, 12, 1), now), '今天');
      expect(dayLabel(DateTime(2026, 9, 11, 1), now), '昨天');
      expect(dayLabel(DateTime(2026, 9, 1), now), '9月1日 周二');
      expect(dayLabel(DateTime(2024, 2, 29), now), '2024年2月29日');
    });
    test('fileSize / duration / badgeText', () {
      expect(fileSize(900), '900 B');
      expect(fileSize(1536), '1.5 KB');
      expect(fileSize(5 * 1024 * 1024 + 1), '5.0 MB');
      expect(fileSize(50 * 1024 * 1024), '50 MB');
      expect(duration(65 * 1000), '1:05');
      expect(duration(3723 * 1000), '1:02:03');
      expect(badgeText(1000), '999+');
    });
    ChatMessage svc(Map<String, dynamic> s, {String text = '', List<MsgEntity> ents = const []}) =>
        ChatMessage(chatId: 1, seq: 1, kind: 'service', service: s, text: text, entities: ents,
            createdAt: DateTime(2026));
    test('serviceText:被操作的人是我就写「你」,频道不说是谁', () {
      final add = svc({'action': 'members_add', 'user_ids': [7, 8], 'names': ['小李', '小王']});
      expect(serviceText(add, actor: '小张', meId: 8), '小张 邀请 小李、你 加入了群');
      final kick = svc({'action': 'member_kick', 'user_id': 8, 'name': '小王'});
      expect(serviceText(kick, actor: '小张', meId: 8), '小张 把 你 移出了群');
      final create = svc({'action': 'chat_create', 'title': '火锅'});
      expect(serviceText(create, actor: '小张', channel: true), '频道「火锅」创建了');
      expect(serviceText(create, actor: '你'), '你 创建了「火锅」');
    });
    test('预览里剧透打码', () {
      final m = ChatMessage(chatId: 1, seq: 2, kind: 'text', text: '结局是😀他死了', createdAt: DateTime(2026),
          entities: const [MsgEntity('spoiler', 3, 5)]);
      expect(previewOf(m), '结局是▒▒▒▒');
    });
    test('isBigEmoji', () {
      expect(isBigEmoji('😀'), isTrue);
      expect(isBigEmoji('👍🏽👍'), isTrue);
      expect(isBigEmoji('🇨🇳'), isTrue);
      expect(isBigEmoji('好😀'), isFalse);
      expect(isBigEmoji(''), isFalse);
    });
  });
}
