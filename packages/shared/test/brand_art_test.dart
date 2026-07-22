import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

void main() {
  testWidgets('五款品牌插画都能渲染', (tester) async {
    for (final art in BrandArt.values) {
      await tester.pumpWidget(MaterialApp(
          theme: brandTheme(Brightness.light),
          home: Scaffold(body: Center(child: BrandArtView(art)))));
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byType(BrandArtView), findsOneWidget, reason: '$art');
    }
  });

  testWidgets('空态自动匹配插画并带弹性入场', (tester) async {
    await tester.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: const Scaffold(
            body: EmptyState(
                icon: Icons.storefront_outlined, text: '附近暂时没有商家'))));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byType(BrandArtView), findsOneWidget);
    expect(find.byType(PopIn), findsOneWidget);
    expect(find.text('附近暂时没有商家'), findsOneWidget);
  });

  testWidgets('无匹配插画的图标退回灰图标', (tester) async {
    await tester.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: const Scaffold(
            body: EmptyState(icon: Icons.support_agent, text: 'x'))));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.byType(BrandArtView), findsNothing);
    expect(find.byIcon(Icons.support_agent), findsOneWidget);
  });

  testWidgets('FadeSlideIn 前 8 项做动画,之后直接渲染', (tester) async {
    await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
            body: Column(children: [
      FadeSlideIn(index: 0, child: Text('a')),
      FadeSlideIn(index: 99, child: Text('b')),
    ]))));
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.text('a'), findsOneWidget);
    expect(find.text('b'), findsOneWidget);
  });

  testWidgets('BrandLogo 矢量渲染', (tester) async {
    await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: BrandLogo(size: 96))));
    expect(find.byType(BrandLogo), findsOneWidget);
  });
}
