/// 宿主下发给小程序的主题参数(§5.4 CSS 变量那一节):取 brand.dart 的产品层令牌,亮暗两套。
///
/// 键名和 Telegram Mini Apps 的 ThemeParams 一致 —— Telegram 的 15 个键全都下发,再加一个超级赞自己的
/// `line_color`(发丝线)。页面拿到的是 `--sz-theme-bg-color` / `--tg-theme-bg-color` 这类 CSS 变量(SDK 负责写),
/// 值是超级赞自己的骨白 / 墨 / 黏土 —— 小程序默认就长得像超级赞的一部分。
///
/// 后加的 6 个键(header_bg_color 起)取的都是前 10 个里已有的令牌:老版本 App 只发 10 个,
/// SDK 按同一张对应表补齐(packages/miniapp-sdk 的 DERIVED_THEME),新老 App 里页面读到的是同一套值。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

String hexOf(Color c) =>
    '#${c.toARGB32().toRadixString(16).padLeft(8, '0').substring(2).toUpperCase()}';

Color? colorOf(String? hex) {
  if (hex == null || !RegExp(r'^#[0-9A-Fa-f]{6}$').hasMatch(hex)) return null;
  return Color(int.parse('FF${hex.substring(1)}', radix: 16));
}

/// Telegram 的 15 个主题色键(顺序照 Telegram 文档)。宿主一个不少地下发,测试按这张表核对。
const kTelegramThemeKeys = [
  'bg_color', 'text_color', 'hint_color', 'link_color', 'button_color', 'button_text_color',
  'secondary_bg_color', 'header_bg_color', 'bottom_bar_bg_color', 'accent_text_color',
  'section_bg_color', 'section_header_text_color', 'section_separator_color', 'subtitle_text_color',
  'destructive_text_color',
];

Map<String, String> miniAppThemeParams(SzColors sz, Brightness b) => {
      'bg_color': hexOf(sz.paper),
      'secondary_bg_color': hexOf(sz.surface),
      'text_color': hexOf(sz.ink),
      'hint_color': hexOf(sz.inkMuted),
      'link_color': hexOf(sz.link),
      'button_color': hexOf(sz.clay),
      'button_text_color': hexOf(b == Brightness.dark ? sz.paper : sz.surface),
      'accent_text_color': hexOf(sz.clay),
      'destructive_text_color': hexOf(sz.danger),
      // 顶栏默认和页面同底(骨白),靠一条发丝线分开
      'header_bg_color': hexOf(sz.paper),
      // 底栏(主按钮那一条)用卡片色托起来:一眼看得出这一条归宿主
      'bottom_bar_bg_color': hexOf(sz.surface),
      'section_bg_color': hexOf(sz.surface),
      // 分组标题、副标题都要读得清:用 inkMuted(骨白底上 5.32),不用只给装饰的 inkFaint
      'section_header_text_color': hexOf(sz.inkMuted),
      'section_separator_color': hexOf(sz.line),
      'subtitle_text_color': hexOf(sz.inkMuted),
      // 超级赞多出来的一个键,Telegram 没有
      'line_color': hexOf(sz.line),
    };
