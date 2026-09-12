/// 宿主下发给小程序的主题参数(§5.4 CSS 变量那一节):取 brand.dart 的产品层令牌,亮暗两套。
///
/// 页面拿到的是 `--sz-theme-bg-color` 这类 CSS 变量(SDK 负责写),名字和 Telegram 对齐,
/// 值是超级赞自己的骨白 / 墨 / 黏土 —— 小程序默认就长得像超级赞的一部分。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

String hexOf(Color c) =>
    '#${c.toARGB32().toRadixString(16).padLeft(8, '0').substring(2).toUpperCase()}';

Color? colorOf(String? hex) {
  if (hex == null || !RegExp(r'^#[0-9A-Fa-f]{6}$').hasMatch(hex)) return null;
  return Color(int.parse('FF${hex.substring(1)}', radix: 16));
}

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
      'line_color': hexOf(sz.line),
    };
