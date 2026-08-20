import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 网页版的能力边界。**只在 web 上显示。**
///
/// 写的是"哪些能用、哪些不能",不是一句笼统的"部分功能受限" ——
/// 商家要据此决定"我今天能不能只开网页版"。
class WebLimitsBanner extends StatefulWidget {
  const WebLimitsBanner({super.key});

  @override
  State<WebLimitsBanner> createState() => _WebLimitsBannerState();
}

class _WebLimitsBannerState extends State<WebLimitsBanner> {
  static const _key = 'web_limits_dismissed';
  bool? _hidden;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((sp) {
      if (mounted) setState(() => _hidden = sp.getBool(_key) ?? false);
    });
  }

  @override
  Widget build(BuildContext context) {
    // 还没读出来时什么都不画 —— 先画出来再消失比一直不画更晃眼
    if (_hidden != false) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(kPagePad, 10, 8, 10),
      color: sz.claySoft,
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('网页版:接单、菜单、对账、核销都能用',
                  style: TextStyle(
                      fontSize: kFontBody,
                      fontWeight: FontWeight.w600,
                      color: sz.ink)),
              const SizedBox(height: 2),
              Text(
                  '但**不能替代手机 App 听单** —— 浏览器没有后台常驻,'
                      '关掉这个页面就收不到新单提醒了。'
                      '蓝牙小票机也连不了(云打印可以)。',
                  style: TextStyle(
                      fontSize: kFontNote, height: 1.6, color: sz.inkMuted)),
            ],
          ),
        ),
        IconButton(
          icon: const Icon(Icons.close, size: 18),
          tooltip: '不再提示',
          onPressed: () async {
            final sp = await SharedPreferences.getInstance();
            await sp.setBool(_key, true);
            if (mounted) setState(() => _hidden = true);
          },
        ),
      ]),
    );
  }
}
