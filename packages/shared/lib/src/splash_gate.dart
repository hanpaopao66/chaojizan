import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';

/// 三端共用开屏:运营位(后台可配图文)优先,没配置回落品牌开屏。
///
/// 永不阻塞冷启动:本次启动只用「上次启动缓存好的」配置和图片,
/// 拉新配置在后台静默进行、下次启动生效。运营位带"跳过 N"倒计时;
/// 品牌开屏约 2.2 秒,点击任意处跳过。自营内容,不是广告位。
class SplashGate extends StatefulWidget {
  const SplashGate({
    super.key,
    required this.app,       // user / merchant / rider(接口端定向)
    required this.tagline,   // 品牌开屏主口号
    required this.subLines,  // 品牌开屏副文案池(按日轮换)
    required this.child,
  });

  final String app;
  final String tagline;
  final List<String> subLines;
  final Widget child;

  @override
  State<SplashGate> createState() => _SplashGateState();
}

class _SplashGateState extends State<SplashGate>
    with SingleTickerProviderStateMixin {
  static const _kCfg = 'splash_cfg';
  static const _kImg = 'splash_img_b64';
  static const _kImgUrl = 'splash_img_url';
  static const _maxImageBytes = 4 * 1024 * 1024;

  bool _done = false;
  Map<String, dynamic>? _op;   // 生效中的运营位配置(来自上次启动的缓存)
  Uint8List? _opImage;
  int _remaining = 0;
  Timer? _timer;
  Timer? _tick;
  late final AnimationController _intro = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 700))
    ..forward();

  @override
  void initState() {
    super.initState();
    _timer = Timer(const Duration(milliseconds: 2200), _finish);
    _loadCachedThenRefresh();
  }

  /// 读缓存 → 有效则切运营位模式;随后后台拉新配置存给下次启动
  Future<void> _loadCachedThenRefresh() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_kCfg);
      final img = prefs.getString(_kImg);
      if (raw != null && img != null && !_done) {
        final cfg = jsonDecode(raw) as Map<String, dynamic>;
        final ends = cfg['ends_at'] as String?;
        final expired =
            ends != null && DateTime.parse(ends).isBefore(DateTime.now());
        if (!expired) {
          setState(() {
            _op = cfg;
            _opImage = base64Decode(img);
            _remaining = (cfg['countdown_seconds'] as num?)?.toInt() ?? 3;
          });
          _timer?.cancel();
          _timer = Timer(Duration(seconds: _remaining), _finish);
          _tick = Timer.periodic(const Duration(seconds: 1), (_) {
            if (mounted && _remaining > 0) setState(() => _remaining--);
          });
        }
      }
      unawaited(_refreshForNextLaunch(prefs));
    } catch (_) {
      // 缓存坏了就当没有,品牌开屏兜底
    }
  }

  Future<void> _refreshForNextLaunch(SharedPreferences prefs) async {
    try {
      final base = ApiClient().baseUrl;
      final resp = await http
          .get(Uri.parse('$base/splash?app=${widget.app}'))
          .timeout(const Duration(seconds: 6));
      if (resp.statusCode != 200) return;
      final body = jsonDecode(resp.body);
      if (body == null) {
        await prefs.remove(_kCfg);
        await prefs.remove(_kImg);
        await prefs.remove(_kImgUrl);
        return;
      }
      final cfg = body as Map<String, dynamic>;
      final imageUrl = cfg['image_url'] as String;
      await prefs.setString(_kCfg, jsonEncode(cfg));
      if (prefs.getString(_kImgUrl) != imageUrl) {
        final full = imageUrl.startsWith('http') ? imageUrl : '$base$imageUrl';
        final img = await http
            .get(Uri.parse(full))
            .timeout(const Duration(seconds: 15));
        if (img.statusCode == 200 &&
            img.bodyBytes.length <= _maxImageBytes) {
          await prefs.setString(_kImg, base64Encode(img.bodyBytes));
          await prefs.setString(_kImgUrl, imageUrl);
        }
      }
    } catch (_) {
      // 拉不到就下次再说,开屏永远不因网络问题卡住
    }
  }

  void _finish() {
    if (mounted && !_done) setState(() => _done = true);
  }

  @override
  void dispose() {
    _timer?.cancel();
    _tick?.cancel();
    _intro.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 450),
      child: _done
          ? widget.child
          : (_op != null && _opImage != null
              ? _OperationalSplash(
                  key: const ValueKey('op'),
                  image: _opImage!,
                  title: (_op!['title'] as String?) ?? '',
                  subtitle: (_op!['subtitle'] as String?) ?? '',
                  remaining: _remaining,
                  onSkip: _finish,
                )
              : GestureDetector(
                  key: const ValueKey('brand'),
                  behavior: HitTestBehavior.opaque,
                  onTap: _finish,
                  child: _BrandSplash(
                      intro: _intro,
                      tagline: widget.tagline,
                      sub: widget.subLines[
                          DateTime.now().day % widget.subLines.length]),
                )),
    );
  }
}

/// 运营位开屏:整屏竖图 + 底部文案压黑 + 右上角"跳过 N"
class _OperationalSplash extends StatelessWidget {
  const _OperationalSplash({
    super.key,
    required this.image,
    required this.title,
    required this.subtitle,
    required this.remaining,
    required this.onSkip,
  });

  final Uint8List image;
  final String title;
  final String subtitle;
  final int remaining;
  final VoidCallback onSkip;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0B0E14),
      body: Stack(
        fit: StackFit.expand,
        children: [
          Image.memory(image, fit: BoxFit.cover, gaplessPlayback: true),
          if (title.isNotEmpty || subtitle.isNotEmpty)
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: Container(
                padding: const EdgeInsets.fromLTRB(24, 48, 24, 56),
                decoration: const BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [Colors.transparent, Color(0xCC000000)],
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (title.isNotEmpty)
                      Text(title,
                          style: const TextStyle(
                              color: Colors.white,
                              fontSize: 24,
                              fontWeight: FontWeight.w800)),
                    if (subtitle.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text(subtitle,
                          style: const TextStyle(
                              color: Colors.white70, fontSize: 14)),
                    ],
                  ],
                ),
              ),
            ),
          SafeArea(
            child: Align(
              alignment: Alignment.topRight,
              child: Padding(
                padding: const EdgeInsets.only(top: 12, right: 16),
                child: FilledButton.tonal(
                  onPressed: onSkip,
                  style: FilledButton.styleFrom(
                    backgroundColor: Colors.black45,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 6),
                    minimumSize: Size.zero,
                  ),
                  child: Text('跳过 $remaining',
                      style: const TextStyle(fontSize: 13)),
                ),
              ),
            ),
          ),
          const SafeArea(
            child: Align(
              alignment: Alignment.bottomCenter,
              child: Padding(
                padding: EdgeInsets.only(bottom: 14),
                child: Text('超级赞 · 群众帮群众',
                    style: TextStyle(color: Colors.white38, fontSize: 11)),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 品牌开屏:深色品牌底不随系统主题走——开屏是品牌时刻,要有识别度
class _BrandSplash extends StatelessWidget {
  const _BrandSplash(
      {required this.intro, required this.tagline, required this.sub});

  final Animation<double> intro;
  final String tagline;
  final String sub;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0B0E14),
      body: Container(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(0, -0.2),
            radius: 1.2,
            colors: [Color(0xFF1A2338), Color(0xFF0B0E14)],
          ),
        ),
        child: SafeArea(
          child: Column(
            children: [
              const Spacer(flex: 3),
              FadeTransition(
                opacity: CurvedAnimation(parent: intro, curve: Curves.easeOut),
                child: ScaleTransition(
                  scale: Tween(begin: 0.82, end: 1.0).animate(CurvedAnimation(
                      parent: intro, curve: Curves.easeOutBack)),
                  child: Column(
                    children: [
                      Container(
                        width: 96,
                        height: 96,
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(26),
                          gradient: const LinearGradient(
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                            colors: [Color(0xFFFF7A45), Color(0xFFFF5A1F)],
                          ),
                          boxShadow: [
                            BoxShadow(
                                color: const Color(0xFFFF5A1F)
                                    .withValues(alpha: .35),
                                blurRadius: 36,
                                offset: const Offset(0, 10)),
                          ],
                        ),
                        child: const Icon(Icons.thumb_up_alt_rounded,
                            color: Colors.white, size: 52),
                      ),
                      const SizedBox(height: 22),
                      const Text('超级赞',
                          style: TextStyle(
                              color: Color(0xFFF2F5FB),
                              fontSize: 34,
                              fontWeight: FontWeight.w800,
                              letterSpacing: 6)),
                      const SizedBox(height: 10),
                      Text(tagline,
                          style: const TextStyle(
                              color: Color(0xFFFFB84D),
                              fontSize: 16,
                              fontWeight: FontWeight.w600)),
                      const SizedBox(height: 8),
                      Text(sub,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                              color: Color(0xFF8B95AC), fontSize: 13)),
                    ],
                  ),
                ),
              ),
              const Spacer(flex: 4),
              const Padding(
                padding: EdgeInsets.only(bottom: 26),
                child: Text('群众帮群众 · 账目为证',
                    style: TextStyle(color: Color(0xFF5A6478), fontSize: 12)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
