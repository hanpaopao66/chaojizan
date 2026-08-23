import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 明厨亮灶接入(#155-#157)。
///
/// ## 这一页是法规里「平台提供技术支持」的落点
///
/// 总局令第 123 号第十三条要求平台"为入网餐饮服务提供者实施
/// 「互联网+明厨亮灶」**提供技术支持**"。技术支持不是一句客服电话 ——
/// 是让商家能自己走完接入,不用打电话问怎么弄。
///
/// 所以这一页要写清楚三件事:去哪儿拿地址、镜头该对哪儿、什么情况会掉线。
///
/// ## 不做的
///
/// 不卖摄像头、不绑定品牌。萤石、海康、大华、通用 NVR 都能接 ——
/// 绑定单一厂商等于变相收费,和「低抽成」的立场冲突。
class KitchenCamSetupPage extends StatefulWidget {
  const KitchenCamSetupPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<KitchenCamSetupPage> createState() => _KitchenCamSetupPageState();
}

class _KitchenCamSetupPageState extends State<KitchenCamSetupPage> {
  Map<String, dynamic>? _data;
  Object? _error;
  bool _saving = false;

  final _url = TextEditingController();
  String _vendor = '';
  bool _notified = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final d = await widget.api.merchantKitchenCam();
      if (!mounted) return;
      setState(() {
        _data = d;
        if (_url.text.isEmpty) _url.text = '${d['url'] ?? ''}';
        _vendor = '${d['vendor'] ?? ''}';
        _notified = d['notified'] == true;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _submit() async {
    if (_saving) return;
    setState(() => _saving = true);
    try {
      final d = await widget.api.setMerchantKitchenCam(
        url: _url.text.trim(),
        notified: _notified,
        vendor: _vendor,
      );
      if (!mounted) return;
      setState(() => _data = d);
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已提交,平台会看一眼画面再放行')));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _remove() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => SzDialog(
        title: const Text('撤下明厨亮灶?'),
        content: const Text('撤下后顾客看到的是「无明厨亮灶」。'
            '这是你的选择 —— 法规对商家是倡导,不是强制。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('再想想')),
          TextButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('撤下')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      final d = await widget.api.removeMerchantKitchenCam();
      if (!mounted) return;
      setState(() {
        _data = d;
        _url.text = '';
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      // 限宽用宽档:后厨视频挤在 720 里看不清 —— 
      // 宽度上限按**内容形态**选,不是统一限死
      contentMaxWidth: kWideMaxWidth,
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
    final status = '${d['status']}';
    final caps = d['capabilities'] as Map<String, dynamic>? ?? const {};

    return ListView(
      padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 32),
      children: [
        _statusCard(sz, status, d),
        const SizedBox(height: 14),

        // ---- 为什么值得装:给商家一个真实的理由,不画饼 ----
        SzCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('装了有什么用',
                style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 7),
            Text(
              '顾客在列表里能看到你的店标着「有明厨亮灶」,点开能看到后厨实时画面。'
              '干净的后厨本来就是你的优势,只是以前顾客看不见。\n\n'
              '要说在前面:平台不会因为你装了就多给你流量。'
              '一旦标识能换流量,就会有人对着天花板装一个来骗标识 —— '
              '那这个标识对谁都没用了。',
              style: TextStyle(fontSize: 12.5, height: 1.65, color: sz.inkMuted),
            ),
          ]),
        ),
        const SizedBox(height: 14),

        // ---- 接入:平台的「技术支持」义务落在这里 ----
        SzCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('接入',
                style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            Text('用你现在的摄像头就行,我们不卖硬件、也不挑品牌',
                style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
            const SizedBox(height: 12),

            Text('① 摄像头品牌', style: TextStyle(fontSize: 12.5, color: sz.ink)),
            const SizedBox(height: 6),
            Wrap(spacing: 8, children: [
              for (final v in const ['萤石', '海康', '大华', '其他'])
                ChoiceChip(
                  label: Text(v, style: const TextStyle(fontSize: 12.5)),
                  selected: _vendor == v,
                  onSelected: (_) => setState(() => _vendor = v),
                ),
            ]),
            const SizedBox(height: 6),
            Text(_vendorHint(), style: TextStyle(fontSize: 11.5, height: 1.5, color: sz.inkMuted)),
            const SizedBox(height: 14),

            Text('② 播放地址', style: TextStyle(fontSize: 12.5, color: sz.ink)),
            const SizedBox(height: 6),
            TextField(
              controller: _url,
              decoration: const InputDecoration(
                hintText: 'https://…/live.m3u8',
                helperText: '支持 https / http / rtsp / rtmp;必须是公网能打开的地址',
                helperMaxLines: 2,
                border: OutlineInputBorder(),
              ),
              style: const TextStyle(fontSize: 13),
            ),
            const SizedBox(height: 14),

            // ---- ③ 镜头对哪儿:#157 的边界在接入这一刻就要讲清楚 ----
            Text('③ 镜头对哪儿', style: TextStyle(fontSize: 12.5, color: sz.ink)),
            const SizedBox(height: 7),
            _coverList(sz, '要拍', (d['should_cover'] as List?) ?? const [],
                sz.earn, Icons.check),
            const SizedBox(height: 6),
            _coverList(sz, '不要拍', (d['must_not_cover'] as List?) ?? const [],
                sz.hold, Icons.close),
            const SizedBox(height: 6),
            Text(
              '法规要求覆盖的是「加工制作的关键环节」,不是整个店。'
              '拍到休息区、更衣、卫生间的会被退回 —— '
              '后厨里站着的也是人,不该被 24 小时看着。',
              style: TextStyle(fontSize: 11.5, height: 1.5, color: sz.inkMuted),
            ),
            const SizedBox(height: 14),

            // ---- ④ 告知员工:硬门槛,服务端也会拦 ----
            Container(
              padding: const EdgeInsets.all(11),
              decoration: BoxDecoration(
                color: sz.hold.withValues(alpha: .08),
                borderRadius: BorderRadius.circular(kRadiusSm),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  CheckboxListTile(
                    value: _notified,
                    onChanged: (v) => setState(() => _notified = v ?? false),
                    contentPadding: EdgeInsets.zero,
                    controlAffinity: ListTileControlAffinity.leading,
                    dense: true,
                    title: const Text('我已告知后厨全体员工:这个区域有对外直播的摄像头',
                        style: TextStyle(fontSize: 12.5, height: 1.4)),
                  ),
                  Text(
                    '这一条是必填的。个人信息保护法要求采集图像要先有显著提示 —— '
                    '更重要的是,你的员工有权知道自己在被拍。'
                    '接入说明里有一张可打印的告知牌,贴在后厨就行。',
                    style: TextStyle(
                        fontSize: 11, height: 1.5, color: sz.inkMuted),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),

            // 不写死高度:#134 把密度做成了主题层的事,
            // FilledButton 的尺寸由 szTheme(density: operate) 统一放大,
            // 组件自己去读密度反而会和主题打架
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _saving ? null : _submit,
                child: Text(_saving
                    ? '提交中…'
                    : status == 'none' ? '提交接入' : '更新地址'),
              ),
            ),
            if (status != 'none') ...[
              const SizedBox(height: 6),
              TextButton(
                onPressed: _remove,
                child: Text('撤下明厨亮灶',
                    style: TextStyle(fontSize: 12.5, color: sz.inkMuted)),
              ),
            ],
          ]),
        ),
        const SizedBox(height: 14),

        // ---- 平台怎么验:把规则摆出来,免得掉线时觉得是平台在整他 ----
        SzCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('平台怎么验',
                style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 7),
            Text(
              '每 ${d['probe_interval_minutes']} 分钟探一次画面。'
              '连着探不到两次,标识会自动变回「无明厨亮灶」,并推送提醒你 —— '
              '修好后一次探通就自动恢复。\n\n'
              '为什么要这么做:如果标着「有」而实际是黑屏,'
              '顾客是被我们骗了,这个责任在平台身上。'
              '所以标识必须跟着实际情况走。',
              style: TextStyle(fontSize: 12.5, height: 1.65, color: sz.inkMuted),
            ),
            const SizedBox(height: 8),
            // 能验哪几项要照实说 —— 不能让商家以为我们全都验了
            Text('当前检测:${caps['note'] ?? ''}',
                style: TextStyle(fontSize: 11.5, height: 1.5, color: sz.inkMuted)),
          ]),
        ),
      ],
    );
  }

  Widget _statusCard(SzColors sz, String status, Map<String, dynamic> d) {
    final has = status == 'active';
    final color = has
        ? sz.earn
        : status == 'degraded'
            ? sz.hold
            : sz.inkMuted;
    return SzCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(has ? Icons.videocam_outlined : Icons.videocam_off_outlined,
              size: 20, color: color),
          const SizedBox(width: 8),
          Text('${d['listed_label']}',
              style: TextStyle(
                  fontSize: 16, fontWeight: FontWeight.w600, color: color)),
          const Spacer(),
          Text(_statusWord(status),
              style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
        ]),
        if ('${d['note'] ?? ''}'.isNotEmpty) ...[
          const SizedBox(height: 7),
          Text('${d['note']}',
              style: TextStyle(fontSize: 12.5, height: 1.5, color: sz.inkMuted)),
        ],
        const SizedBox(height: 6),
        Text('这是顾客在列表里看到你的店时显示的标识',
            style: TextStyle(fontSize: 11, color: sz.inkMuted)),
      ]),
    );
  }

  String _statusWord(String s) => switch (s) {
        'active' => '在线',
        'pending' => '待平台核验',
        'degraded' => '连不上',
        _ => '未接入',
      };

  String _vendorHint() => switch (_vendor) {
        '萤石' => '萤石云 App → 设备设置 → 直播管理 → 开启直播 → 复制播放地址',
        '海康' => '海康萤石开放平台或本地 NVR 的 HLS 转发地址;'
            '本地 NVR 需要在路由器上做端口映射,并确保公网能访问',
        '大华' => '乐橙云 App → 设备详情 → 分享/直播 → 获取播放地址',
        '其他' => '在摄像头或 NVR 的后台找「直播」「HLS」「RTSP」地址;'
            '找不到的话把品牌型号发给平台客服,我们帮你找',
        _ => '选一个品牌,给你对应的取址步骤',
      };

  Widget _coverList(
      SzColors sz, String title, List<dynamic> items, Color color, IconData icon) {
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SizedBox(
        width: 44,
        child: Text(title,
            style: TextStyle(fontSize: 12, color: color)),
      ),
      Expanded(
        child: Wrap(spacing: 4, runSpacing: 4, children: [
          for (final it in items)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: color.withValues(alpha: .10),
                borderRadius: BorderRadius.circular(3),
              ),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(icon, size: 10, color: color),
                const SizedBox(width: 3),
                Text('$it', style: TextStyle(fontSize: 11, color: sz.ink)),
              ]),
            ),
        ]),
      ),
    ]);
  }
}
