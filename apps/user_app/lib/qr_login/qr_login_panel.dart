import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:superz_shared/superz_shared.dart';

import 'qr_login.dart';

/// 网页版 / 桌面版登录页上的扫码登录、一键登录面板(挂在 [SmsLoginPage.altLogin] 上)。
///
/// - 这台设备记得上次扫码登录的账号:先显示头像昵称和「一键登录」,点了之后给手机发确认请求,
///   手机上点确认就进去;「切换账号」回到扫码;
/// - 不记得(或者点了「切换账号」):显示二维码。过期了自动换一张新的,手机上取消了说一声。
///
/// 一次只挂一个长轮询。换会话、离开页面时代数 [_gen] 加一,旧的那个轮询回来一看对不上就自己停。
class QrLoginPanel extends StatefulWidget {
  const QrLoginPanel({
    super.key,
    required this.api,
    required this.host,
    this.client,
    this.platform,
  });

  final ApiClient api;
  final SzAltLoginHost host;

  /// 报给服务端的客户端类型 / 系统。不给按当前平台([qrClientKind]、[qrDesktopPlatform]),测试里指定
  final String? client;
  final String? platform;

  @override
  State<QrLoginPanel> createState() => _QrLoginPanelState();
}

class _QrLoginPanelState extends State<QrLoginPanel> {
  /// 还在读本地记住的账号
  bool _loading = true;
  QrLoginMemory? _memory;

  /// 显示二维码(没有记住的账号,或者点了「切换账号」)
  bool _qrMode = false;

  Map<String, dynamic>? _session;

  /// 当前会话的状态:''(还没建)/ pending / scanned / cancelled / expired
  String _status = '';

  /// 「已扫码」时服务端给的打码昵称和头像
  Map<String, dynamic>? _who;

  /// 出错时给人看的一句话(断网、限流)。轮询恢复正常就清掉
  String _error = '';

  /// 为什么现在是扫码(一键登录失效了)。自动换二维码不清,人点「刷新」才清
  String _notice = '';

  int _gen = 0;

  /// 连着自动换了几张二维码。页面开着没人扫的话,换到第 5 张就停,等人点一下再换 ——
  /// 标签页忘在后台一整天,不该每两分钟去服务端建一个会话
  int _autoRefreshes = 0;

  String get _client => widget.client ?? qrClientKind;
  String get _platform => widget.platform ?? qrDesktopPlatform;

  @override
  void initState() {
    super.initState();
    unawaited(_init());
  }

  Future<void> _init() async {
    final memory = await QrLoginMemory.load();
    if (!mounted) return;
    setState(() {
      _memory = memory;
      _loading = false;
      _qrMode = memory == null;
    });
    if (memory == null) await _startQr();
  }

  @override
  void dispose() {
    _gen++;
    super.dispose();
  }

  /// 换一张新的二维码。**不等轮询结束就返回** —— 轮询要挂到有人扫、过期或者离开页面为止
  Future<void> _startQr({bool manual = false, String notice = ''}) async {
    final gen = ++_gen;
    if (manual) _autoRefreshes = 0;
    setState(() {
      _qrMode = true;
      _session = null;
      _status = '';
      _who = null;
      _error = '';
      if (manual) _notice = notice;
    });
    try {
      final s = await widget.api.createQrLogin(
          client: _client,
          platform: _platform,
          prevDeviceKey: _memory?.deviceKey ?? '');
      if (!mounted || gen != _gen) return;
      setState(() {
        _session = s;
        _status = '${s['status']}';
      });
      unawaited(_poll(gen));
    } on ApiException catch (e) {
      if (mounted && gen == _gen) setState(() => _error = e.message);
    }
  }

  Future<void> _startOneClick() async {
    final memory = _memory;
    if (memory == null) return;
    final gen = ++_gen;
    setState(() {
      _status = 'sending';
      _error = '';
    });
    try {
      final s = await widget.api.createQrLogin(
          client: _client, platform: _platform, deviceKey: memory.deviceKey);
      if (!mounted || gen != _gen) return;
      setState(() {
        _session = s;
        _status = '${s['status']}';
      });
      unawaited(_poll(gen));
    } on ApiException catch (e) {
      if (!mounted || gen != _gen) return;
      if (e.statusCode == 403) {
        // 手机上移除了、太久没用、或者这把 key 已经换过了:忘掉它,改成扫码
        await QrLoginMemory.clear();
        if (!mounted) return;
        setState(() => _memory = null);
        await _startQr(manual: true, notice: e.message);
        return;
      }
      setState(() {
        _status = '';
        _error = e.message;
      });
    }
  }

  /// 挂着长轮询,直到登录成功、被取消、过期,或者这一代作废
  Future<void> _poll(int gen) async {
    while (mounted && gen == _gen) {
      final s = _session;
      if (s == null) return;
      Map<String, dynamic> r;
      try {
        r = await widget.api.pollQrLogin('${s['sid']}', '${s['secret']}', state: _status);
      } on ApiException catch (e) {
        if (!mounted || gen != _gen) return;
        // 断网、服务端重启:等一下再接着问,不在界面上刷一屏错误
        setState(() => _error = e.isNetwork ? '网络不太顺,正在重试…' : e.message);
        await Future<void>.delayed(const Duration(seconds: 3));
        continue;
      }
      if (!mounted || gen != _gen) return;
      final status = '${r['status']}';
      switch (status) {
        case 'confirmed':
          await _finish(r, gen);
          return;
        case 'pending':
        case 'scanned':
          setState(() {
            _status = status;
            _error = '';
            if (r['user'] is Map) _who = (r['user'] as Map).cast<String, dynamic>();
          });
        case 'expired':
          if (_qrMode && _autoRefreshes < 4) {
            _autoRefreshes++;
            unawaited(_startQr());
          } else {
            setState(() => _status = 'expired');
          }
          return;
        default:
          setState(() => _status = status);
          return;
      }
    }
  }

  Future<void> _finish(Map<String, dynamic> r, int gen) async {
    try {
      await widget.api.adoptQrLogin(r);
    } catch (e) {
      if (mounted && gen == _gen) setState(() => _error = '$e');
      return;
    }
    await QrLoginMemory(
      deviceKey: '${r['device_key']}',
      deviceId: (r['device_id'] as num?)?.toInt() ?? 0,
      userId: (r['user_id'] as num?)?.toInt() ?? 0,
      name: widget.api.userName ?? '${r['name'] ?? ''}',
      avatarUrl: '${r['avatar_url'] ?? ''}',
    ).save();
    if (mounted && gen == _gen) widget.host.loggedIn();
  }

  void _stopWaiting() {
    _gen++;
    setState(() {
      _status = '';
      _session = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const SizedBox(
          height: 240, child: Center(child: CircularProgressIndicator()));
    }
    return _qrMode || _memory == null ? _qrPanel(context) : _oneClickPanel(context, _memory!);
  }

  Widget _oneClickPanel(BuildContext context, QrLoginMemory m) {
    final sz = Theme.of(context).sz;
    final waiting = _status == 'sending' || _status == 'scanned';
    final hint = switch (_status) {
      'sending' => '正在发到你的手机…',
      'scanned' => '已发到你的手机,请在手机上点「登录」',
      'cancelled' => '你在手机上取消了这次登录',
      'expired' => '手机上没有确认,可以再点一次',
      _ => '这台设备上次登录的账号',
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        SzImage(url: widget.api.resolveUrl(m.avatarUrl), name: m.name, size: 72, circle: true),
        const SizedBox(height: 10),
        Text(m.name,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
                fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink)),
        const SizedBox(height: 4),
        Text(hint,
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        if (_error.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(_error,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: kFontNote, color: sz.danger)),
        ],
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: waiting ? null : _startOneClick,
            child: Text(waiting ? '等待手机确认…' : '一键登录'),
          ),
        ),
        if (waiting)
          TextButton(onPressed: _stopWaiting, child: const Text('不等了'))
        else
          TextButton(
              onPressed: () => _startQr(manual: true), child: const Text('切换账号')),
        const SizedBox(height: 4),
        Text('一键登录要在手机 App 上点确认才能进去',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
      ],
    );
  }

  Widget _qrPanel(BuildContext context) {
    final sz = Theme.of(context).sz;
    final s = _session;
    // 底部那一格的名字后台能改(nav.chat,默认「聊天」)。这句话指导的是**手机上**的操作,
    // 而网页版永远是新的、手机上可能还是 2026-09-15 以前的版本(那时叫「消息」),所以把旧名也写上
    final tab = RemoteCopy.text('nav.chat', '聊天');
    final where = tab == '消息' ? '「消息」' : '「$tab」(旧版 App 里叫「消息」)';
    final line = switch (_status) {
      'scanned' => '已扫码,请在手机上点「登录」',
      'cancelled' => '你在手机上取消了这次登录',
      'expired' => '二维码已过期',
      _ => '打开超级赞 App,在$where右上角点「新建」,选「扫一扫」',
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text('扫码登录',
            style: TextStyle(
                fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink)),
        const SizedBox(height: 12),
        // 二维码必须白底黑码才扫得出来,不跟随深色主题
        Container(
          width: 220,
          height: 220,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(kRadiusMd),
            border: Border.all(color: sz.line),
          ),
          child: Stack(alignment: Alignment.center, children: [
            if (s != null && '${s['qr']}'.isNotEmpty)
              Opacity(
                opacity: _status == 'pending' ? 1 : 0.12,
                child: QrImageView(
                    data: '${s['qr']}', size: 196, padding: EdgeInsets.zero),
              )
            else if (_error.isEmpty)
              const CircularProgressIndicator(),
            if (_status == 'scanned') _scannedBadge(),
            if (_status == 'expired' || _status == 'cancelled' || (s == null && _error.isNotEmpty))
              FilledButton.tonal(
                  onPressed: () => _startQr(manual: true), child: const Text('刷新二维码')),
          ]),
        ),
        const SizedBox(height: 12),
        Text(line,
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: kFontBody, color: sz.ink, height: 1.5)),
        if (_error.isNotEmpty || _notice.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(_error.isNotEmpty ? _error : _notice,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: kFontNote, color: sz.danger)),
        ],
        const SizedBox(height: 6),
        Text('登录后,这台设备会出现在手机「设置 → 已登录的网页和电脑」里,随时可以移除',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted, height: 1.5)),
      ],
    );
  }

  /// 「已扫码」:扫码的人(服务端打过码的昵称)和头像
  Widget _scannedBadge() {
    final who = _who ?? const {};
    final name = '${who['name'] ?? ''}';
    return Column(mainAxisSize: MainAxisSize.min, children: [
      SzImage(
          url: widget.api.resolveUrl('${who['avatar_url'] ?? ''}'),
          name: name.isEmpty ? '已' : name,
          size: 56,
          circle: true),
      const SizedBox(height: 8),
      Text(name.isEmpty ? '已扫码' : name,
          // 二维码框永远是白底(见 _qrPanel),这里取浅色那一套的墨色,不跟深色主题走
          style: TextStyle(
              fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: SzColors.light.ink)),
    ]);
  }
}
