import 'package:flutter/material.dart';

import 'brand.dart';
import 'sz_widgets.dart';

/// 明厨亮灶标识与直播页(#155-#157)。
///
/// ## 这个标识是法定要求,不是装饰
///
/// 《网络餐饮服务经营者落实食品安全主体责任监督管理规定》
/// (国家市场监督管理总局令第 123 号,**2026-06-01 施行**)第十三条:
/// 平台应当"根据入网餐饮服务提供者是否实施「互联网+明厨亮灶」,
/// 在入网餐饮服务提供者列表页面展示「无明厨亮灶」、「有明厨亮灶」标识"。
///
/// 注意要标的是**两种** —— 所以 [SzKitchenCamChip] 对没装的店也会渲染,
/// 只是渲染成灰色的「无明厨亮灶」。**不要因为"没装就不显示更好看"而省掉它**,
/// 省掉的那个列表就是个合规缺口。
///
/// ## 「有」必须是能看的「有」
///
/// 行业里的乱象是:标着明厨亮灶,点开却是黑屏、或者镜头对着天花板。
/// 服务端每 30 分钟探一次,连不上就把状态降级 —— 客户端这边**只认服务端给的
/// 布尔值**,不自己缓存、不自己兜底成"应该是有的吧"。
///
/// 用户看到的标识和实际能不能看,必须是同一件事。
class SzKitchenCamChip extends StatelessWidget {
  const SzKitchenCamChip({
    super.key,
    required this.has,
    this.label,
    this.compact = false,
    this.onTap,
  });

  /// 服务端给的 kitchen_cam。**不要在客户端二次推断**
  final bool has;

  /// 服务端给的 kitchen_cam_label;缺省时按 has 生成
  final String? label;

  /// 列表项里用紧凑版(只有「有明厨亮灶」时才占位,见下)
  final bool compact;

  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final text = label ?? (has ? '有明厨亮灶' : '无明厨亮灶');

    // 紧凑版(列表项):没装的店只留一行浅灰小字,不占彩色徽章的位置。
    // 法规要求「无」也要标,但没要求标得一样显眼 ——
    // 把「无」做成大红标签是在羞辱没装的商家,而法规对商家是「倡导」不是强制
    if (compact && !has) {
      return Text(text,
          style: TextStyle(fontSize: 10.5, color: sz.inkMuted));
    }

    return GestureDetector(
      onTap: has ? onTap : null,
      child: Container(
        padding: EdgeInsets.symmetric(
            horizontal: compact ? 5 : 7, vertical: compact ? 1.5 : 3),
        decoration: BoxDecoration(
          color: has
              ? sz.earn.withValues(alpha: .12)
              : sz.inkFaint.withValues(alpha: .10),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(has ? Icons.videocam_outlined : Icons.videocam_off_outlined,
              size: compact ? 11 : 13,
              color: has ? sz.earn : sz.inkMuted),
          const SizedBox(width: 3),
          Text(text,
              style: TextStyle(
                  fontSize: compact ? 10.5 : 12,
                  color: has ? sz.earn : sz.inkMuted)),
          if (has && onTap != null && !compact) ...[
            const SizedBox(width: 2),
            Icon(Icons.chevron_right, size: 13, color: sz.earn),
          ],
        ]),
      ),
    );
  }
}

/// 后厨直播页。
///
/// 拿不到画面时**直说**,不要转圈转到天荒地老 ——
/// 服务端已经把标识改回「无明厨亮灶」了,这里再假装加载中是自相矛盾。
class KitchenCamPage extends StatefulWidget {
  const KitchenCamPage({
    super.key,
    required this.shopName,
    required this.load,
    this.playerBuilder,
  });

  final String shopName;

  /// 通常是 `() => api.kitchenCamOf(merchantId)`
  final Future<Map<String, dynamic>> Function() load;

  /// 播放器构建器,由宿主 App 注入(用户端接 video_player)。
  ///
  /// **shared 不依赖任何播放器实现** —— 骑手端/商家端不需要看直播,
  /// 让它们跟着装一个几 MB 的原生播放器不划算。
  ///
  /// 不注入时退化为"给地址不给画面",页面其余部分照常可用。
  final Widget Function(String url)? playerBuilder;

  @override
  State<KitchenCamPage> createState() => _KitchenCamPageState();
}

class _KitchenCamPageState extends State<KitchenCamPage> {
  Map<String, dynamic>? _data;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await widget.load();
      if (mounted) setState(() => _data = d);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Scaffold(
      appBar: AppBar(title: const Text('明厨亮灶')),
      body: _error != null
          ? SzError(error: _error, onRetry: _load)
          : _data == null
              ? const Center(child: CircularProgressIndicator())
              : _content(sz),
    );
  }

  Widget _content(SzColors sz) {
    final d = _data!;
    final has = d['has_kitchen_cam'] == true;
    final url = '${d['url'] ?? ''}';

    return ListView(
      padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
      children: [
        Text(widget.shopName,
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        SzKitchenCamChip(has: has, label: '${d['label']}'),
        const SizedBox(height: 16),

        if (!has)
          // 看不了就直说为什么。**不甩锅给商家,也不含糊**
          SzCard(
            child: Column(children: [
              Icon(Icons.videocam_off_outlined, size: 34, color: sz.inkFaint),
              const SizedBox(height: 10),
              Text('${d['message']}',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 13.5, height: 1.5, color: sz.ink)),
            ]),
          )
        else ...[
          // 播放器由宿主注入(用户端接 video_player);
          // 没注入就退化成占位 —— 骑手端/商家端不看直播,
          // 不该为此各装一个几 MB 的原生播放器
          if (widget.playerBuilder != null && url.isNotEmpty)
            ClipRRect(
              borderRadius: BorderRadius.circular(kRadiusSm),
              child: widget.playerBuilder!(url),
            )
          else
            SzCard(
              padding: EdgeInsets.zero,
              child: AspectRatio(
                aspectRatio: 16 / 9,
                child: Container(
                  decoration: BoxDecoration(
                    color: Colors.black,
                    borderRadius: BorderRadius.circular(kRadiusSm),
                  ),
                  child: Center(
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      const Icon(Icons.play_circle_outline,
                          size: 44, color: Colors.white70),
                      const SizedBox(height: 8),
                      Text('这一端不播放直播',
                          style: TextStyle(
                              fontSize: 12.5,
                              color: Colors.white.withValues(alpha: .7))),
                    ]),
                  ),
                ),
              ),
            ),
        ],

        const SizedBox(height: 18),
        // 这两条不是免责声明,是对**后厨那些人**的交代(#157)。
        // 顾客有权知道自己在看什么,后厨员工有权被限定拍摄范围
        _note(sz, Icons.crop_free, '${d['coverage_note']}'),
        const SizedBox(height: 8),
        _note(sz, Icons.history_toggle_off, '${d['no_playback']}'),
        if (d['checked_at'] != null) ...[
          const SizedBox(height: 8),
          _note(sz, Icons.verified_outlined,
              '平台每半小时探一次画面;连不上会自动把标识改回「无明厨亮灶」'),
        ],
      ],
    );
  }

  Widget _note(SzColors sz, IconData icon, String text) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 14, color: sz.inkFaint),
          const SizedBox(width: 7),
          Expanded(
            child: Text(text,
                style: TextStyle(
                    fontSize: 11.5, height: 1.5, color: sz.inkMuted)),
          ),
        ],
      );
}
