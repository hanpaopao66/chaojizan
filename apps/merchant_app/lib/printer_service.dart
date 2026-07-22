/// 蓝牙小票机直连:通用 58mm ESC/POS 热敏打印机(市面几十块的蓝牙小票机都认)。
///
/// 与云打印(服务端飞鹅直推)互为补充:蓝牙零成本复用商家现有设备,
/// 但依赖商家手机在场;云打印反之。两者都配置时会各出一张,设置页有提示。
///
/// 中文用 GBK 编码——热敏机的字库不认 UTF-8,这是行业约定而不是我们的选择。
library;

import 'dart:io' show Platform;

import 'package:fast_gbk/fast_gbk.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:permission_handler/permission_handler.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

const _kMac = 'bt_printer_mac';
const _kName = 'bt_printer_name';
const _kAuto = 'bt_auto_print';

bool get _btSupported => !kIsWeb && (Platform.isAndroid || Platform.isIOS);

/// 58mm 纸宽 = 32 个 ASCII 列(汉字占 2 列)。
const _cols = 32;

class BtPrinter {
  BtPrinter._();

  // ---------- 设备记忆 ----------

  static Future<(String mac, String name)?> savedDevice() async {
    final p = await SharedPreferences.getInstance();
    final mac = p.getString(_kMac);
    if (mac == null || mac.isEmpty) return null;
    return (mac, p.getString(_kName) ?? mac);
  }

  static Future<void> saveDevice(String mac, String name) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kMac, mac);
    await p.setString(_kName, name);
  }

  static Future<void> clearDevice() async {
    final p = await SharedPreferences.getInstance();
    await p.remove(_kMac);
    await p.remove(_kName);
    try {
      await PrintBluetoothThermal.disconnect;
    } catch (_) {}
  }

  /// 来单自动打印开关(默认开;仅在已选择过打印机时生效)
  static Future<bool> autoPrintEnabled() async {
    final p = await SharedPreferences.getInstance();
    return (p.getBool(_kAuto) ?? true) && (p.getString(_kMac) ?? '').isNotEmpty;
  }

  static Future<void> setAutoPrint(bool on) async {
    final p = await SharedPreferences.getInstance();
    await p.setBool(_kAuto, on);
  }

  // ---------- 连接与设备列表 ----------

  /// Android 12+ 的「附近设备」运行时权限;老系统/iOS 直接放行
  static Future<bool> ensurePermission() async {
    if (!_btSupported || !Platform.isAndroid) return _btSupported;
    final statuses = await [
      Permission.bluetoothConnect,
      Permission.bluetoothScan,
    ].request();
    return statuses.values.every(
        (s) => s.isGranted || s.isLimited || s.isRestricted);
  }

  /// 系统里已配对的蓝牙设备(先在系统设置里配对小票机)
  static Future<List<BluetoothInfo>> pairedDevices() async {
    if (!_btSupported) return const [];
    if (!await PrintBluetoothThermal.bluetoothEnabled) {
      throw Exception('蓝牙未开启,请先打开手机蓝牙');
    }
    return PrintBluetoothThermal.pairedBluetooths;
  }

  static Future<bool> _connected() async {
    try {
      return await PrintBluetoothThermal.connectionStatus;
    } catch (_) {
      return false;
    }
  }

  /// 写入字节流;断连自动重连重试一次
  static Future<String?> _write(String mac, List<int> bytes) async {
    for (var attempt = 0; attempt < 2; attempt++) {
      try {
        if (!await _connected()) {
          final ok =
              await PrintBluetoothThermal.connect(macPrinterAddress: mac);
          if (!ok) {
            if (attempt == 0) continue;
            return '连不上打印机,请确认打印机已开机且在附近';
          }
        }
        final sent = await PrintBluetoothThermal.writeBytes(bytes);
        if (sent) return null;
        await PrintBluetoothThermal.disconnect;
      } catch (_) {
        try {
          await PrintBluetoothThermal.disconnect;
        } catch (_) {}
      }
    }
    return '打印失败,请重试(打印机可能被其他设备占用)';
  }

  // ---------- 打印 ----------

  /// 打订单小票。返回 null = 成功;其他 = 中文错误提示。
  /// 未选择过打印机返回 'NO_DEVICE'(调用方决定是否走云打印兜底)。
  static Future<String?> printOrder(Order order,
      {required String shopName}) async {
    final device = await savedDevice();
    if (device == null) return 'NO_DEVICE';
    return _write(device.$1, _orderTicket(order, shopName));
  }

  static Future<String?> printTest(String shopName) async {
    final device = await savedDevice();
    if (device == null) return 'NO_DEVICE';
    return _write(device.$1, _testTicket(shopName));
  }
}

// ---------- ESC/POS 排版 ----------

class _Esc {
  final List<int> _out = [0x1B, 0x40]; // 初始化

  void _align(int n) => _out.addAll([0x1B, 0x61, n]);
  void _bold(bool on) => _out.addAll([0x1B, 0x45, on ? 1 : 0]);
  void _size(bool big) => _out.addAll([0x1D, 0x21, big ? 0x11 : 0x00]);

  void line(String text,
      {bool bold = false, bool big = false, int align = 0}) {
    _align(align);
    _bold(bold);
    _size(big);
    _out.addAll(gbk.encode(text));
    _out.add(0x0A);
    if (big) _size(false);
    if (bold) _bold(false);
  }

  void divider() => line('-' * _cols);

  /// 左右两端对齐(按 GBK 字节宽度补空格;放大字体时每列占双宽)
  void kv(String left, String right, {bool bold = false, bool big = false}) {
    final width = big ? _cols ~/ 2 : _cols;
    final used = gbk.encode(left).length + gbk.encode(right).length;
    final pad = used >= width ? 1 : width - used;
    line('$left${' ' * pad}$right', bold: bold, big: big);
  }

  List<int> done() {
    _out.addAll([0x1B, 0x64, 3]); // 走纸 3 行
    _out.addAll([0x1D, 0x56, 0x42, 0x00]); // 半切(不支持切刀的机器忽略)
    return _out;
  }
}

String _yuanTxt(int cents) => (cents / 100).toStringAsFixed(2);

String _timeTxt(String iso) {
  final t = DateTime.tryParse(iso)?.toLocal();
  if (t == null) return '';
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(t.month)}-${two(t.day)} ${two(t.hour)}:${two(t.minute)}';
}

List<int> _orderTicket(Order order, String shopName) {
  final e = _Esc();
  final tail =
      order.orderNo.length > 6 ? order.orderNo.substring(order.orderNo.length - 6) : order.orderNo;
  e.line('超级赞 #$tail', big: true, bold: true, align: 1);
  e.line(shopName, align: 1);
  if (order.pickup) {
    e.line('自取单 取餐码 ${order.pickupCode}', big: true, bold: true, align: 1);
  }
  if (order.parentOrderNo.isNotEmpty) {
    e.line(
        '追加单 随#${order.parentOrderNo.substring(order.parentOrderNo.length - 6)}一起出',
        bold: true,
        align: 1);
  }
  e.divider();
  e.line('单号 ${order.orderNo}');
  e.line('下单 ${_timeTxt(order.createdAt)}');
  if (order.scheduledLabel != null) {
    e.line('预约:${order.scheduledLabel}', bold: true);
  }
  if (order.remark.isNotEmpty) e.line('备注:${order.remark}', bold: true);
  if (order.hasAlcohol) e.line('含酒精饮品 请查验收件人年龄', bold: true);
  e.divider();
  for (final item in order.items) {
    e.kv('${item.name} x${item.quantity}',
        _yuanTxt(item.priceCents * item.quantity),
        bold: true);
  }
  e.divider();
  e.kv('菜品', _yuanTxt(order.foodCents));
  if (order.packingFeeCents > 0) e.kv('打包费', _yuanTxt(order.packingFeeCents));
  if (order.discountCents > 0) e.kv('满减', '-${_yuanTxt(order.discountCents)}');
  if (order.pickup) {
    e.line('到店自取 免配送费');
  } else {
    e.kv('配送费(全归骑手)', _yuanTxt(order.deliveryFeeCents));
  }
  e.kv('用户实付', _yuanTxt(order.totalCents), bold: true, big: true);
  e.divider();
  if (order.pickup) {
    e.line('顾客到店自取,核对取餐码 ${order.pickupCode}', bold: true);
    if (order.contactPhone.isNotEmpty) {
      e.line('${order.contactName} ${order.contactPhone}');
    }
  } else {
    e.line('${order.contactName} ${order.contactPhone}', bold: true);
    e.line(order.address, bold: true, big: true);
  }
  e.divider();
  e.line('平台只抽5% 账目公开可查', align: 1);
  return e.done();
}

List<int> _testTicket(String shopName) {
  final e = _Esc();
  e.line('超级赞 测试页', big: true, bold: true, align: 1);
  e.line(shopName, align: 1);
  e.divider();
  e.line('看到这张小票,说明蓝牙打印一切正常。');
  e.line('新订单到达时会自动出票。');
  e.divider();
  e.line('平台只抽5% 账目公开可查', align: 1);
  return e.done();
}
