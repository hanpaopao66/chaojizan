/// 小票打印设置:云打印机(飞鹅,服务端直推)+ 蓝牙小票机(App 直连)。
///
/// 推荐商家用云打印:打印机自己联网,手机关机也照样出票。
/// 蓝牙适合起步期复用手头的便宜打印机。两者都开会各出一张,页面有提示。
library;

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
  // 云打印状态
  bool _cloudLoaded = false;
  bool _cloudEnabled = false; // 平台是否配置了服务商
  String _cloudSn = '';
  bool _cloudAuto = true;
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
      final s = await widget.api.printerStatus();
      if (mounted) {
        setState(() {
          _cloudLoaded = true;
          _cloudEnabled = s['enabled'] as bool? ?? false;
          _cloudSn = s['sn'] as String? ?? '';
          _cloudAuto = s['auto'] as bool? ?? true;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _cloudLoaded = true);
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
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('绑定云打印机'),
        content: Column(
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
          ],
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
    );
    if (ok != true) return;
    final sn = snCtrl.text.trim();
    final key = keyCtrl.text.trim();
    if (sn.isEmpty || key.isEmpty) return _toast('SN 和 KEY 都要填');
    await _guard(() async {
      final s = await widget.api.bindPrinter(sn, key, remark: widget.shopName);
      setState(() {
        _cloudSn = s['sn'] as String? ?? sn;
        _cloudAuto = s['auto'] as bool? ?? true;
      });
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
            else if (!_cloudEnabled)
              Text('平台还未开通云打印服务,先用下面的蓝牙打印;开通后这里会自动亮起。',
                  style: TextStyle(color: theme.colorScheme.error))
            else if (_cloudSn.isEmpty)
              Align(
                alignment: Alignment.centerRight,
                child: FilledButton.icon(
                  icon: const Icon(Icons.add_link),
                  label: const Text('绑定打印机'),
                  onPressed: _busy ? null : _bindCloud,
                ),
              )
            else ...[
              Row(children: [
                const Icon(Icons.check_circle, color: Colors.green, size: 18),
                const SizedBox(width: 6),
                Expanded(child: Text('已绑定:$_cloudSn')),
              ]),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('新订单自动出票'),
                value: _cloudAuto,
                onChanged: _busy
                    ? null
                    : (v) => _guard(() async {
                          await widget.api.setPrinterAuto(v);
                          setState(() => _cloudAuto = v);
                        }),
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: _busy
                        ? null
                        : () => _guard(() async {
                              await widget.api.unbindPrinter();
                              setState(() => _cloudSn = '');
                              _toast('已解绑');
                            }),
                    child: const Text('解绑'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton.tonal(
                    onPressed: _busy
                        ? null
                        : () => _guard(() async {
                              await widget.api.printerTest();
                              _toast('测试页已发送,看打印机出纸');
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

  // ---------- 蓝牙 ----------

  Future<void> _pickBtDevice() async {
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
    final picked = await showModalBottomSheet<BluetoothInfo>(
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
                const Icon(Icons.check_circle, color: Colors.green, size: 18),
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
    final both = _cloudSn.isNotEmpty && _cloudAuto && _btDevice != null && _btAuto;
    return Scaffold(
      appBar: AppBar(title: const Text('小票打印')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
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
