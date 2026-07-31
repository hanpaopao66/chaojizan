import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 协议全文里的第三方链接(#136)。
///
/// 上架审核要求隐私政策**如实列出第三方 SDK 的隐私政策链接**,而"列出"的前提
/// 是那个链接点得动 —— 印在那儿点不动等于没给。这组测试守两件事:
/// 网址真的挂上了点击手势,以及链接蓝没被当成普通强调色到处用。
void main() {
  Widget wrap(Widget child, {Brightness b = Brightness.light}) =>
      MaterialApp(theme: brandTheme(b), home: child);

  /// 从渲染出来的富文本里捞出所有带点击手势的片段
  List<TextSpan> tappableSpans(WidgetTester tester) {
    final out = <TextSpan>[];
    for (final t in tester.widgetList<Text>(find.descendant(
        of: find.byType(SelectionArea), matching: find.byType(Text)))) {
      final span = t.textSpan;
      span?.visitChildren((s) {
        if (s is TextSpan && s.recognizer is TapGestureRecognizer) out.add(s);
        return true;
      });
    }
    return out;
  }

  group('第三方隐私政策链接可点', () {
    testWidgets('隐私政策全文里的网址挂了点击手势', (tester) async {
      await tester.pumpWidget(
          wrap(const LegalPage(title: '隐私政策', body: kPrivacyText)));
      final taps = tappableSpans(tester);
      expect(taps, isNotEmpty, reason: '网址还是死文本 —— 审核要求可点可达');
      for (final s in taps) {
        expect(s.text, startsWith('http'));
      }
    });

    testWidgets('公示里列到的每个网址都可点,一个不落', (tester) async {
      await tester.pumpWidget(
          wrap(const LegalPage(title: '隐私政策', body: kPrivacyText)));
      final rendered =
          tappableSpans(tester).map((s) => s.text).toSet();
      final inText = RegExp(r'https?://[^\s;,、。)）]+')
          .allMatches(kPrivacyText)
          .map((m) => m.group(0)!)
          .toSet();
      expect(inText, isNotEmpty, reason: '正文里一个第三方隐私政策网址都没有?');
      expect(rendered, inText, reason: '有网址没被渲染成可点');
    });

    testWidgets('网址不会把句子切断:拼回去必须等于原文', (tester) async {
      await tester.pumpWidget(
          wrap(const LegalPage(title: '用户协议', body: kTermsText)));
      // 不能用 .last:AppBar 的标题也是个 Text,而且它排在后面
      final t = tester.widget<Text>(find.descendant(
          of: find.byType(SelectionArea), matching: find.byType(Text)));
      final buf = StringBuffer();
      t.textSpan?.visitChildren((s) {
        if (s is TextSpan && s.text != null) buf.write(s.text);
        return true;
      });
      expect(buf.toString(), kTermsText, reason: '切片拼不回原文,正文被吃掉了');
    });
  });

  group('链接蓝的纪律', () {
    test('link 与平台色、语义色都不同,不是换个名字的 clay', () {
      for (final c in [SzColors.light, SzColors.dark]) {
        expect(c.link, isNot(c.clay));
        expect(c.link, isNot(c.earn));
        expect(c.link, isNot(c.hold));
        expect(c.link, isNot(c.ink));
      }
    });

    test('深浅两态都给了值,且不相等', () {
      expect(SzColors.light.link, isNot(SzColors.dark.link),
          reason: '深色态直接套浅色蓝会糊在背景里');
    });

    testWidgets('链接色不进按钮主题 —— 实底主按钮仍是平台色', (tester) async {
      final t = brandTheme(Brightness.light);
      final sz = t.extension<SzColors>()!;
      expect(t.filledButtonTheme.style!.backgroundColor!.resolve({}),
          sz.clay,
          reason: '主按钮被染蓝了 —— 链接蓝只给"点了会离开当前页"的字');
    });
  });
}
