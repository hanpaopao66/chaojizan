/// 小票打印设置:云打印机(飞鹅,服务端直推)+ 蓝牙小票机(App 直连)。
///
/// 推荐商家用云打印:打印机自己联网,手机关机也照样出票。
/// 蓝牙适合起步期复用手头的便宜打印机。两者都开会各出一张,页面有提示。
library;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';
import 'package:superz_shared/superz_shared.dart';

import 'printer_service.dart';

class PrinterPage extends StatefulWidget {
  const PrinterPage({super.key, required this.api, required this.shopName});

  final ApiClient api;
  final String shopName;

  @override
  State<PrinterPage> createState() => _PrinterPageState();
}

class _PrinterPageState extends State<PrinterPage> {
  // 云打印状态。**一家店可以挂多台**:前厅出顾客小票、后厨出备餐单,
  // 是餐饮的标配 —— 共用一台的话出餐的人得跑到前台去拿
  bool _cloudLoaded = false;

  /// 非空 = 云打印配置没拉到。**不能**因此显示成「平台还未开通」——
  /// 那是一句关于平台的事实陈述,商家据此就不去绑打印机了
  String _cloudError = '';
  bool _cloudEnabled = false; // 平台是否配置了服务商
  List<Map<String, dynamic>> _printers = const [];
  List<Map<String, dynamic>> _purposes = const [];
  String _printerNote = '';
  bool _busy = false;

  // 蓝牙状态
  (String, String)? _btDevice;
  bool _btAuto = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await widget.api.printers();
      if (mounted) {
        setState(() {
          _cloudLoaded = true;
          _cloudEnabled = s['enabled'] as bool? ?? false;
          _printers = ((s['items'] as List?) ?? const [])
              .cast<Map<String, dynamic>>();
          _purposes = ((s['purposes'] as List?) ?? const [])
              .cast<Map<String, dynamic>>();
          _printerNote = '${s['note'] ?? ''}';
          _cloudError = '';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _cloudLoaded = true;
          _cloudError = e is ApiException ? e.message : '$e';
        });
      }
    }
    final device = await BtPrinter.savedDevice();
    final auto = await BtPrinter.autoPrintEnabled();
    if (mounted) {
      setState(() {
        _btDevice = device;
        _btAuto = auto;
      });
    }
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _guard(Future<void> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
    } catch (e) {
      _toast(e is ApiException ? e.message : '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ---------- 云打印 ----------

  Future<void> _bindCloud() async {
    final snCtrl = TextEditingController();
    final keyCtrl = TextEditingController();
    final nameCtrl = TextEditingController();
    var purpose = 'front';
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setLocal) => SzDialog(
        title: const Text('绑定云打印机'),
        content: SingleChildScrollView(
          child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('SN 和 KEY 在打印机机身贴纸上',
                style: TextStyle(fontSize: 13)),
            const SizedBox(height: 12),
            TextField(
                controller: snCtrl,
                decoration: const InputDecoration(
                    labelText: 'SN(编号)', border: OutlineInputBorder())),
            const SizedBox(height: 12),
            TextField(
                controller: keyCtrl,
                decoration: const InputDecoration(
                    labelText: 'KEY(识别码)', border: OutlineInputBorder())),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: purpose,
              decoration: const InputDecoration(
                  labelText: '这台放在哪、印什么',
                  border: OutlineInputBorder()),
              items: [
                for (final p in (_purposes.isEmpty
                    ? const [
                        {'value': 'front', 'label': '前厅小票'},
                        {'value': 'kitchen', 'label': '后厨备餐单'},
                        {'value': 'label', 'label': '标签'},
                      ]
                    : _purposes))
                  DropdownMenuItem(
                      value: '${p['value']}', child: Text('${p['label']}')),
              ],
              onChanged: (v) => setLocal(() => purpose = v ?? 'front'),
            ),
            const SizedBox(height: 8),
            Text(
              purpose == 'kitchen'
                  ? '后厨备餐单**不印顾客手机号和地址** —— 后厨用不到,'
                      '而单子会被随手丢在操作台上。'
                  : purpose == 'label'
                      ? '标签贴在打包袋外面,只印店名与单号后六位。'
                      : '前厅小票含收件人与地址 —— 骑手来取要核对。',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            TextField(
                controller: nameCtrl,
                decoration: const InputDecoration(
                    labelText: '备注名(选填,如「后厨那台」)',
                    border: OutlineInputBorder())),
          ],
        ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('绑定')),
        ],
      ),
      ),
    );
    if (ok != true) return;
    final sn = snCtrl.text.trim();
    final key = keyCtrl.text.trim();
    if (sn.isEmpty || key.isEmpty) return _toast('SN 和 KEY 都要填');
    await _guard(() async {
      await widget.api.addPrinter(
          sn: sn, key: key, purpose: purpose, name: nameCtrl.text.trim());
      await _load();
      _toast('绑定成功,可以打一张测试页试试');
    });
  }

  Widget _cloudCard() {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Icon(Icons.cloud_outlined),
              const SizedBox(width: 8),
              Text('云打印机(推荐)', style: theme.textTheme.titleMedium),
            ]),
            const SizedBox(height: 4),
            Text('打印机自带流量卡/WiFi 联网,新订单支付成功后平台直接推送出票——'
                '手机没电、App 被杀都不影响。支持飞鹅系列云打印机。',
                style: theme.textTheme.bodySmall),
            const SizedBox(height: 12),
            if (!_cloudLoaded)
              const Center(child: CircularProgressIndicator())
            else if (_cloudError.isNotEmpty)
              SzRetryBanner(
                  text: '云打印配置没拉到($_cloudError),开没开通现在说不准。点这里重试',
                  onRetry: _load)
            else if (!_cloudEnabled)
              Text('平台还未开通云打印服务,先用下面的蓝牙打印;开通后这里会自动亮起。',
                  style: TextStyle(color: theme.colorScheme.error))
            else ...[
              for (final p in _printers) _printerTile(p),
              if (_printers.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Text('还没有绑定打印机'),
                ),
              if (_printerNote.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 4, bottom: 8),
                  child: Text(_printerNote,
                      style: theme.textTheme.bodySmall),
                ),
              Align(
                alignment: Alignment.centerRight,
                child: FilledButton.icon(
                  icon: const Icon(Icons.add_link),
                  label: Text(_printers.isEmpty ? '绑定打印机' : '再绑一台'),
                  onPressed: _busy ? null : _bindCloud,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// 一台打印机:用途 + 自动出票开关 + 解绑。
  ///
  /// 用途单独标出来,因为它决定这台印什么 —— 后厨那张不带顾客手机号和
  /// 地址,商家得能一眼看出哪台是哪台。
  Widget _printerTile(Map<String, dynamic> p) {
    final theme = Theme.of(context);
    final purpose = '${p['purpose']}';
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Icon(
                purpose == 'kitchen'
                    ? Icons.soup_kitchen_outlined
                    : purpose == 'label'
                        ? Icons.label_outline
                        : Icons.receipt_long_outlined,
                size: 18,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  '${p['name']}'.isEmpty
                      ? '${p['purpose_label']}'
                      : '${p['name']}',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
              Chip(
                label: Text('${p['purpose_label']}',
                    style: const TextStyle(fontSize: 11)),
                visualDensity: VisualDensity.compact,
              ),
            ]),
            Text('SN ${p['sn']}', style: theme.textTheme.bodySmall),
            if (purpose == 'kitchen')
              Text('这张不印顾客手机号和地址',
                  style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant)),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              title: const Text('新订单自动出票'),
              value: p['auto'] == true,
              onChanged: _busy
                  ? null
                  : (v) => _guard(() async {
                        await widget.api
                            .updatePrinter(p['id'] as int, {'auto': v});
                        await _load();
                      }),
            ),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: _busy
                    ? null
                    : () => _guard(() async {
                          await widget.api.removePrinter(p['id'] as int);
                          await _load();
                          _toast('已解绑');
                        }),
                child: const Text('解绑'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ---------- 蓝牙 ----------

  Future<void> _pickBtDevice() async {
    if (!await PermissionRationale.ensure(
        context, AppPermissionKind.bluetooth)) {
      return;
    }
    if (!await BtPrinter.ensurePermission()) {
      return _toast('需要「附近设备/蓝牙」权限才能连接打印机');
    }
    List<BluetoothInfo> devices;
    try {
      devices = await BtPrinter.pairedDevices();
    } catch (e) {
      return _toast('$e');
    }
    if (devices.isEmpty) {
      return _toast('没有已配对的蓝牙设备:请先在手机系统蓝牙里配对小票机');
    }
    if (!mounted) return;
    final picked = await szShowSheet<BluetoothInfo>(
      context: context,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('选择小票打印机(已配对设备)',
                  style: TextStyle(fontWeight: FontWeight.bold)),
            ),
            for (final d in devices)
              ListTile(
                leading: const Icon(Icons.print_outlined),
                title: Text(d.name.isEmpty ? d.macAdress : d.name),
                subtitle: Text(d.macAdress),
                onTap: () => Navigator.pop(context, d),
              ),
          ],
        ),
      ),
    );
    if (picked == null) return;
    await BtPrinter.saveDevice(picked.macAdress,
        picked.name.isEmpty ? picked.macAdress : picked.name);
    await _load();
    _toast('已选择打印机,打一张测试页确认一下');
  }

  Widget _btCard() {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Icon(Icons.bluetooth),
              const SizedBox(width: 8),
              Text('蓝牙小票机', style: theme.textTheme.titleMedium),
            ]),
            const SizedBox(height: 4),
            Text('通用 58mm 蓝牙热敏打印机即插即用,零月租。'
                '依赖本机在场:请保持商家端常驻、手机和打印机放一起。',
                style: theme.textTheme.bodySmall),
            const SizedBox(height: 12),
            if (_btDevice == null)
              Align(
                alignment: Alignment.centerRight,
                child: FilledButton.icon(
                  icon: const Icon(Icons.bluetooth_searching),
                  label: const Text('选择打印机'),
                  onPressed: _busy ? null : _pickBtDevice,
                ),
              )
            else ...[
              Row(children: [
                Icon(Icons.check_circle, color: Theme.of(context).sz.earn, size: 18),
                const SizedBox(width: 6),
                Expanded(child: Text('已选择:${_btDevice!.$2}')),
                TextButton(
                    onPressed: _busy ? null : _pickBtDevice,
                    child: const Text('换一台')),
              ]),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('来单自动打印'),
                subtitle: const Text('新订单到达商家端时自动出票'),
                value: _btAuto,
                onChanged: (v) async {
                  await BtPrinter.setAutoPrint(v);
                  setState(() => _btAuto = v);
                },
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: _busy
                        ? null
                        : () async {
                            await BtPrinter.clearDevice();
                            await _load();
                            _toast('已移除');
                          },
                    child: const Text('移除'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton.tonal(
                    onPressed: _busy
                        ? null
                        : () => _guard(() async {
                              final err =
                                  await BtPrinter.printTest(widget.shopName);
                              _toast(err ?? '测试页已发送');
                            }),
                    child: const Text('打印测试页'),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // 云打印和蓝牙都开着会出两张一样的单 —— 提醒一句
    final cloudAuto = _printers.any((p) => p['auto'] == true);
    final both = cloudAuto && _btDevice != null && _btAuto;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('小票打印')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          // 网页版说清楚:云打印照常,蓝牙直连不行。
          //
          // 浏览器里没有经典蓝牙 SPP(Web Bluetooth 只有 BLE,
          // 而热敏小票机基本都是 SPP)—— 这是浏览器的能力边界,
          // 不是我们没做。云打印走服务端,和在手机上一模一样。
          if (kIsWeb)
            Container(
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Theme.of(context).sz.claySoft,
                borderRadius: BorderRadius.circular(kRadiusSm),
              ),
              child: Text(
                  '网页版可以用云打印,但连不了蓝牙小票机 —— '
                  '浏览器没有经典蓝牙(Web Bluetooth 只有 BLE,'
                  '而热敏小票机基本都是 SPP)。要用蓝牙机请在手机 App 里配。',
                  style: TextStyle(
                      color: Theme.of(context).sz.ink,
                      fontSize: kFontBody,
                      height: 1.6)),
            ),
          _cloudCard(),
          const SizedBox(height: 12),
          _btCard(),
          if (both)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text('提示:云打印和蓝牙的自动出票都开着,每单会打两张小票。'
                  '只想要一张的话,关掉其中一个的自动开关即可。',
                  style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                      fontSize: 13)),
            ),
        ],
      ),
    );
  }
}
