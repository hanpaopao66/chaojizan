import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 新单提醒的两个开关:声音、震动。存在本机,不上服务端 ——
/// 这是「这台手机怎么叫我」,换台手机重新选一次是对的。
///
/// **弹层本身关不掉。** 新单推上来那张卡是骑手唯一不看大厅也能知道
/// 来单了的地方;声音和震动是给「在骑车 / 在店里吵」的时候选的。
@immutable
class RiderAlertPrefs {
  const RiderAlertPrefs({this.sound = true, this.vibrate = true});

  final bool sound;
  final bool vibrate;

  static const _kSound = 'rider_alert_sound';
  static const _kVibrate = 'rider_alert_vibrate';

  String get label => switch ((sound, vibrate)) {
        (true, true) => '声音 + 震动',
        (true, false) => '只响声音',
        (false, true) => '只震动',
        (false, false) => '只弹卡片',
      };

  static Future<RiderAlertPrefs> load() async {
    final sp = await SharedPreferences.getInstance();
    return RiderAlertPrefs(
      sound: sp.getBool(_kSound) ?? true,
      vibrate: sp.getBool(_kVibrate) ?? true,
    );
  }

  Future<void> save() async {
    final sp = await SharedPreferences.getInstance();
    await sp.setBool(_kSound, sound);
    await sp.setBool(_kVibrate, vibrate);
  }

  RiderAlertPrefs copyWith({bool? sound, bool? vibrate}) => RiderAlertPrefs(
      sound: sound ?? this.sound, vibrate: vibrate ?? this.vibrate);
}

/// 「我的 → 新单提醒」。
class RiderAlertPrefsPage extends StatefulWidget {
  const RiderAlertPrefsPage({super.key, required this.initial, this.onChanged});

  final RiderAlertPrefs initial;
  final ValueChanged<RiderAlertPrefs>? onChanged;

  @override
  State<RiderAlertPrefsPage> createState() => _RiderAlertPrefsPageState();
}

class _RiderAlertPrefsPageState extends State<RiderAlertPrefsPage> {
  late RiderAlertPrefs _p = widget.initial;

  Future<void> _set(RiderAlertPrefs p) async {
    setState(() => _p = p);
    await p.save();
    widget.onChanged?.call(p);
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('新单提醒')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
        children: [
          SzEntryGroup(
            footnote: '新单卡片总会从底部推上来,15 秒后自己收起;'
                '收起后单子还在大厅里。不接不扣分。',
            children: [
              SzEntryTile(
                icon: Icons.volume_up_outlined,
                title: '响声音',
                trailing: SzSwitch(
                    small: true,
                    value: _p.sound,
                    onChanged: (v) => _set(_p.copyWith(sound: v))),
              ),
              SzEntryTile(
                icon: Icons.vibration,
                title: '震动',
                trailing: SzSwitch(
                    small: true,
                    value: _p.vibrate,
                    onChanged: (v) => _set(_p.copyWith(vibrate: v))),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text('骑车的时候(GPS 速度超过 8 公里/小时)界面上别的动画都会停,'
              '只留新单卡片 —— 省得分你的神。',
              style: TextStyle(fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
        ],
      ),
    );
  }
}
