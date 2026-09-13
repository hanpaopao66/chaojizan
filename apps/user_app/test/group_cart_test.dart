import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/group_cart_page.dart';

/// 拼单页(设计稿 G 发起人 / H 同伴):锁单前后各自看到什么、能做什么。
void main() {
  final shop = Merchant.fromJson(const {
    'id': 7,
    'name': '张记面馆',
    'lat': 30.0,
    'lng': 104.0,
    'is_open': true,
    'min_order_cents': 2000,
    'promo_rules': [
      {'threshold_cents': 5000, 'off_cents': 800},
    ],
  });

  final dishes = [
    {
      'id': 1,
      'merchant_id': 7,
      'name': '牛肉面',
      'price_cents': 1600,
      'stock': 50
    },
    {'id': 2, 'merchant_id': 7, 'name': '卤蛋', 'price_cents': 250, 'stock': 50},
    {
      'id': 3,
      'merchant_id': 7,
      'name': '油泼扯面',
      'price_cents': 1400,
      'stock': 50,
      'options': [
        {
          'name': '份量',
          'required': true,
          'choices': [
            {'name': '小份', 'delta_cents': 0},
          ],
        },
      ],
    },
    {
      'id': 4,
      'merchant_id': 7,
      'name': '凉皮',
      'price_cents': 800,
      'stock': 0,
      'sold_out_today': true
    },
    {'id': 5, 'merchant_id': 7, 'name': '冰峰', 'price_cents': 350, 'stock': 50},
  ];

  Map<String, dynamic> item(
          int uid, String by, int dish, String name, int price, int qty) =>
      {
        'uid': uid,
        'by': by,
        'dish_id': dish,
        'name': name,
        'price_cents': price,
        'quantity': qty
      };

  /// 一车三个人:发起人王小明(1)、赵六(2)、孙七(3)。合计 ¥67.00,够满 50 减 8
  Map<String, dynamic> cartFor(int me, {required bool locked}) {
    final items = [
      item(1, '王小明', 1, '牛肉面', 1600, 1),
      item(1, '王小明', 2, '卤蛋', 250, 2),
      item(2, '赵六', 1, '牛肉面', 1600, 1),
      item(2, '赵六', 5, '冰峰', 350, 2),
      item(3, '孙七', 1, '牛肉面', 1600, 1),
      item(3, '孙七', 5, '冰峰', 350, 2),
    ];
    return {
      'code': '123456',
      'merchant_id': 7,
      'merchant_name': '张记面馆',
      'owner_id': 1,
      'locked': locked,
      'members': {'1': '王小明', '2': '赵六', '3': '孙七'},
      'items': items,
      'me': me,
      'is_owner': me == 1,
      'total_cents': items.fold<int>(
          0, (a, i) => a + (i['price_cents'] as int) * (i['quantity'] as int)),
    };
  }

  late Map<String, dynamic> server;
  final lockCalls = <bool>[];

  Future<void> pump(WidgetTester t, Map<String, dynamic> cart) async {
    server = cart;
    lockCalls.clear();
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final p = req.url.path;
        Object? body;
        if (p == '/merchants/7/dishes') {
          body = dishes;
        } else if (p == '/group-carts/123456/lock') {
          final locked = (jsonDecode(req.body) as Map)['locked'] as bool;
          lockCalls.add(locked);
          server = {...server, 'locked': locked};
          body = server;
        } else if (p == '/group-carts/123456') {
          body = server;
        } else {
          body = {};
        }
        return http.Response(jsonEncode(body), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: GroupCartPage(api: api, merchant: shop, code: '123456'),
    ));
    await t.pumpAndSettle();
    // 3 秒一次的同步定时器:用例结束前把页面拆掉,定时器跟着停
    addTearDown(() => t.pumpWidget(const SizedBox()));
  }

  testWidgets('同伴 · 已锁单:说清锁了、在等什么、自己点了多少,不给改菜', (t) async {
    await pump(t, cartFor(3, locked: true));
    expect(find.text('已锁单 · 不能再改菜'), findsOneWidget);
    expect(find.textContaining('这一车共 3 人、¥67.00;你点的 ¥23.00'), findsOneWidget);
    expect(find.text('发起人结算中…'), findsOneWidget);
    // 这一车按人列小计,发起人标出来
    expect(find.text('王小明(发起人)'), findsWidgets);
    expect(find.text('¥21.00'), findsWidgets);
    // 满减按合计算:67 ≥ 50
    expect(find.text('满 50 减 8 · 结算时按合计算'), findsOneWidget);
    expect(find.text('−¥8.00'), findsOneWidget);
    // 同伴锁单后不能改菜:没有加减,也没有结算按钮
    expect(find.byType(SzStepper), findsNothing);
    expect(find.text('锁单并去结算'), findsNothing);
    expect(find.text('去结算'), findsNothing);
  });

  testWidgets('同伴那句说明照实写:订单只在发起人名下,不说「会出现在你的订单里」', (t) async {
    await pump(t, cartFor(3, locked: true));
    expect(find.textContaining('你的「我的订单」里不会有这一单'), findsOneWidget);
    expect(find.textContaining('会出现在你的'), findsNothing);
  });

  testWidgets('发起人 · 没锁:大号拼单码、按人分组的已点、只列能拼的菜', (t) async {
    await pump(t, cartFor(1, locked: false));
    expect(find.text('123456'), findsOneWidget);
    expect(find.text('复制'), findsOneWidget);
    expect(find.text('发给朋友'), findsOneWidget);
    expect(find.text('你(发起人)'), findsOneWidget);
    expect(find.text('3 人在车上'), findsOneWidget);
    // 按人分组:「我」一组,小计 ¥21.00
    expect(find.text('我'), findsWidgets);
    expect(find.text('还差 ¥20.00 起送'), findsNothing,
        reason: '合计 ¥67.00 已够 ¥20 起送');
    expect(find.text('已够起送'), findsOneWidget);
    expect(find.text('锁单并去结算'), findsOneWidget);
    // 加菜在页尾:先滑到底,再连屏外的一起查(不然「找不到」可能只是还没建出来)
    await t.drag(find.byType(ListView), const Offset(0, -800));
    await t.pumpAndSettle();
    expect(find.text('冰峰', skipOffstage: false), findsWidgets);
    // 要选规格的、今日售罄的不列
    expect(find.text('油泼扯面', skipOffstage: false), findsNothing);
    expect(find.text('凉皮', skipOffstage: false), findsNothing);
    expect(find.text('要选规格的菜暂时不能拼:拼单车还不支持选规格。'), findsOneWidget);
  });

  testWidgets('发起人 · 已锁单:加菜点不了,能「解锁」,解开后回到没锁的样子', (t) async {
    await pump(t, cartFor(1, locked: true));
    expect(find.text('已锁单 · 不能再改菜'), findsOneWidget);
    expect(find.text('去结算'), findsOneWidget);
    final stepperGuard = t.widget<IgnorePointer>(find
        .ancestor(
            of: find.byType(SzStepper).first,
            matching: find.byType(IgnorePointer))
        .first);
    expect(stepperGuard.ignoring, isTrue, reason: '锁单后谁都不能改菜');

    await t.tap(find.text('解锁'));
    await t.pumpAndSettle();
    expect(lockCalls, [false]);
    expect(find.text('锁单并去结算'), findsOneWidget);
    expect(find.text('123456'), findsOneWidget);
  });

  testWidgets('同伴 · 没锁:底栏只说等发起人结算,没有结算按钮', (t) async {
    await pump(t, cartFor(2, locked: false));
    expect(find.text('点好了等发起人锁单结算就行'), findsOneWidget);
    expect(find.text('锁单并去结算'), findsNothing);
    expect(find.byType(SzStepper), findsWidgets);
  });
}
