import 'dart:async';
import 'dart:math';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart' show XFile;
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../outbox.dart';
import 'format.dart';

// ---------------- 放语音 ----------------

/// 全 App 同一时刻只放一条语音(点另一条时前一条停下),倍速记在这里。
class VoicePlayback extends ChangeNotifier {
  VoicePlayback._();

  static final VoicePlayback instance = VoicePlayback._();

  final AudioPlayer _player = AudioPlayer();
  bool _wired = false;

  /// 正在放 / 暂停在的那条(媒体 id)
  int? current;
  bool playing = false;
  Duration position = Duration.zero;
  Duration total = Duration.zero;
  double rate = 1.0;

  /// 放过的语音(气泡上「未听」的小蓝点据此消失)。只在本机记
  final Set<int> heard = {};

  void _wire() {
    if (_wired) return;
    _wired = true;
    _player.onPositionChanged.listen((p) {
      position = p;
      notifyListeners();
    });
    _player.onDurationChanged.listen((d) {
      total = d;
      notifyListeners();
    });
    _player.onPlayerComplete.listen((_) {
      playing = false;
      position = Duration.zero;
      notifyListeners();
    });
  }

  Future<void> toggle(int mediaId, String url, int durationMs) async {
    _wire();
    if (current == mediaId) {
      if (playing) {
        await _player.pause();
        playing = false;
      } else {
        await _player.resume();
        playing = true;
      }
      notifyListeners();
      return;
    }
    await _player.stop();
    current = mediaId;
    heard.add(mediaId);
    position = Duration.zero;
    total = Duration(milliseconds: durationMs);
    playing = true;
    notifyListeners();
    try {
      await _player.setPlaybackRate(rate);
      await _player.play(UrlSource(url));
    } catch (_) {
      playing = false;
      notifyListeners();
    }
  }

  Future<void> seek(int mediaId, double frac) async {
    if (current != mediaId) return;
    final ms = (total.inMilliseconds * frac).round();
    await _player.seek(Duration(milliseconds: ms));
  }

  Future<void> cycleRate() async {
    rate = rate == 1.0 ? 1.5 : (rate == 1.5 ? 2.0 : 1.0);
    await _player.setPlaybackRate(rate);
    notifyListeners();
  }

  Future<void> stop() async {
    await _player.stop();
    playing = false;
    current = null;
    notifyListeners();
  }
}

/// 语音气泡的内容:播放键 + 波形(已放过的部分上色、可拖着跳)+ 时长 + 倍速。
class VoiceView extends StatelessWidget {
  const VoiceView({
    super.key,
    required this.media,
    required this.url,
    required this.fg,
    required this.accent,
  });

  final MediaInfo media;

  /// 已签名的完整地址;还没换到签名时为空,按钮先不能点
  final String? url;
  final Color fg;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final pb = VoicePlayback.instance;
    return AnimatedBuilder(
      animation: pb,
      builder: (context, _) {
        final mine = pb.current == media.id && media.id != 0;
        final playing = mine && pb.playing;
        final total = media.durationMs > 0 ? media.durationMs : pb.total.inMilliseconds;
        final frac = mine && total > 0 ? (pb.position.inMilliseconds / total).clamp(0.0, 1.0) : 0.0;
        final unheard = media.id != 0 && !pb.heard.contains(media.id);
        return Row(mainAxisSize: MainAxisSize.min, children: [
          Material(
            color: accent,
            shape: const CircleBorder(),
            child: InkWell(
              customBorder: const CircleBorder(),
              onTap: url == null ? null : () => pb.toggle(media.id, url!, media.durationMs),
              child: SizedBox(
                width: 40,
                height: 40,
                child: Icon(playing ? Icons.pause : Icons.play_arrow, color: Colors.white),
              ),
            ),
          ),
          const SizedBox(width: 10),
          Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTapDown: (d) {
                final box = context.findRenderObject() as RenderBox?;
                if (box == null || !mine) return;
                pb.seek(media.id, (d.localPosition.dx / 150).clamp(0.0, 1.0));
              },
              child: SizedBox(
                width: 150,
                height: 26,
                child: CustomPaint(
                    painter: WaveformPainter(media.waveform, frac, accent, fg.withValues(alpha: .35))),
              ),
            ),
            const SizedBox(height: 2),
            Row(mainAxisSize: MainAxisSize.min, children: [
              Text(
                  mine && pb.position > Duration.zero
                      ? duration(pb.position.inMilliseconds)
                      : duration(total),
                  style: TextStyle(fontSize: kFontMicro, color: fg.withValues(alpha: .7))),
              if (unheard) ...[
                const SizedBox(width: 4),
                Container(
                    width: 6, height: 6, decoration: BoxDecoration(color: accent, shape: BoxShape.circle)),
              ],
              if (mine) ...[
                const SizedBox(width: 8),
                GestureDetector(
                  onTap: pb.cycleRate,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                    decoration: BoxDecoration(
                        color: fg.withValues(alpha: .12), borderRadius: BorderRadius.circular(6)),
                    child: Text('${pb.rate == 1.0 ? '1' : pb.rate}×',
                        style: TextStyle(fontSize: kFontMicro, color: fg)),
                  ),
                ),
              ],
            ]),
          ]),
        ]);
      },
    );
  }
}

/// 波形:64 根竖条(服务端给的 0–31),放过的部分用强调色。
class WaveformPainter extends CustomPainter {
  WaveformPainter(this.samples, this.progress, this.played, this.rest);

  final List<int> samples;
  final double progress;
  final Color played;
  final Color rest;

  @override
  void paint(Canvas canvas, Size size) {
    final data = samples.isEmpty ? List<int>.filled(40, 6) : samples;
    final n = min(data.length, 48);
    final step = data.length / n;
    final barW = size.width / n;
    final p = Paint()..strokeCap = StrokeCap.round;
    for (var i = 0; i < n; i++) {
      final v = data[(i * step).floor()].clamp(0, 31) / 31.0;
      final h = max(2.0, v * size.height);
      final x = i * barW + barW / 2;
      p
        ..color = (i + .5) / n <= progress ? played : rest
        ..strokeWidth = max(1.5, barW * .55);
      canvas.drawLine(Offset(x, (size.height - h) / 2), Offset(x, (size.height + h) / 2), p);
    }
  }

  @override
  bool shouldRepaint(WaveformPainter old) =>
      old.progress != progress || old.samples != samples || old.played != played;
}

// ---------------- 录语音 ----------------

/// 按住录音(DEV-PROMPTS-40 #347)。安卓录 AAC(m4a),网页录 opus(webm),服务端统一转成 m4a。
class VoiceRecorder {
  final AudioRecorder _rec = AudioRecorder();
  final List<double> _levels = [];
  StreamSubscription<Amplitude>? _amp;
  DateTime? _startedAt;
  String _ext = 'm4a';

  /// 当前音量 0–1(录音条上的跳动用)
  final ValueNotifier<double> level = ValueNotifier(0);
  final ValueNotifier<Duration> elapsed = ValueNotifier(Duration.zero);
  Timer? _tick;

  bool get recording => _startedAt != null;

  /// 开始录。没有麦克风权限返回 false(调用方给提示)。
  Future<bool> start() async {
    if (recording) return true;
    if (!await _rec.hasPermission()) return false;
    var encoder = kIsWeb ? AudioEncoder.opus : AudioEncoder.aacLc;
    if (!await _rec.isEncoderSupported(encoder)) encoder = AudioEncoder.wav;
    _ext = switch (encoder) {
      AudioEncoder.opus => 'webm',
      AudioEncoder.wav => 'wav',
      _ => 'm4a',
    };
    var path = '';
    if (!kIsWeb) {
      final dir = await getTemporaryDirectory();
      path = '${dir.path}/voice_${DateTime.now().millisecondsSinceEpoch}.$_ext';
    }
    await _rec.start(RecordConfig(encoder: encoder, numChannels: 1, bitRate: 48000), path: path);
    _levels.clear();
    _startedAt = DateTime.now();
    _amp = _rec.onAmplitudeChanged(const Duration(milliseconds: 100)).listen((a) {
      // dBFS:-60(几乎没声)~ 0(最大)
      final v = ((a.current + 60) / 60).clamp(0.0, 1.0);
      _levels.add(v);
      level.value = v;
    });
    _tick = Timer.periodic(const Duration(milliseconds: 200), (_) {
      elapsed.value = DateTime.now().difference(_startedAt!);
    });
    return true;
  }

  /// 停下并交出录好的附件;太短(< 1 秒)算取消。
  Future<LocalAttachment?> stop() async {
    if (!recording) return null;
    final took = DateTime.now().difference(_startedAt!);
    final out = await _rec.stop();
    _cleanup();
    if (out == null || took < const Duration(seconds: 1)) return null;
    final f = XFile(out, name: 'voice.$_ext', mimeType: _ext == 'm4a' ? 'audio/mp4' : 'audio/$_ext');
    final bytes = await f.readAsBytes();
    return LocalAttachment(
      file: XFile.fromData(bytes, name: 'voice.$_ext'),
      kind: 'voice',
      name: 'voice.$_ext',
      size: bytes.length,
      durationMs: took.inMilliseconds,
      waveform: _downsample(_levels, 64),
      preview: null,
    );
  }

  Future<void> cancel() async {
    if (!recording) return;
    await _rec.cancel();
    _cleanup();
  }

  void _cleanup() {
    _amp?.cancel();
    _amp = null;
    _tick?.cancel();
    _tick = null;
    _startedAt = null;
    level.value = 0;
    elapsed.value = Duration.zero;
  }

  Future<void> dispose() async {
    await cancel();
    await _rec.dispose();
  }

  static List<int> _downsample(List<double> xs, int n) {
    if (xs.isEmpty) return const [];
    final out = <int>[];
    for (var i = 0; i < n; i++) {
      final a = (i * xs.length / n).floor();
      final b = max(a + 1, ((i + 1) * xs.length / n).floor());
      var peak = 0.0;
      for (var k = a; k < b && k < xs.length; k++) {
        peak = max(peak, xs[k]);
      }
      out.add((peak * 31).round());
    }
    return out;
  }
}
