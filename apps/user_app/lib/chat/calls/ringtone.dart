import 'dart:math';
import 'dart:typed_data';

/// 通话的铃声和回铃音,现场合成 WAV,不打包音频文件(也就没有版权问题)。
///
/// - 来电:880 / 1100 Hz 交替的两声短响,停 1.6 秒;
/// - 回铃(主叫听到的「嘟——」):440 + 480 Hz 双音 1 秒,停 2 秒(和固话一样的节奏)。
///
/// 纯函数,单测锁住头部和长度。
Uint8List synthRingtone({required bool incoming}) {
  const rate = 16000;
  final samples = <double>[];
  void tone(double seconds, double Function(double t) f) {
    final n = (seconds * rate).round();
    for (var i = 0; i < n; i++) {
      final t = i / rate;
      // 起止各 10ms 淡入淡出,不然每一声开头都有「咔」的一下
      final edge = min(1.0, min(t, seconds - t) / 0.01);
      samples.add(f(t) * edge);
    }
  }

  void silence(double seconds) => tone(seconds, (_) => 0);
  if (incoming) {
    for (var k = 0; k < 2; k++) {
      tone(0.18, (t) => 0.45 * sin(2 * pi * 880 * t));
      tone(0.18, (t) => 0.45 * sin(2 * pi * 1100 * t));
      silence(0.12);
    }
    silence(1.6);
  } else {
    tone(1.0, (t) => 0.25 * (sin(2 * pi * 440 * t) + sin(2 * pi * 480 * t)));
    silence(2.0);
  }
  return wavPcm16(samples, rate);
}

/// [-1, 1] 的采样 → 16 位单声道 WAV。
Uint8List wavPcm16(List<double> samples, int rate) {
  final dataLen = samples.length * 2;
  final b = ByteData(44 + dataLen);
  void str(int off, String s) {
    for (var i = 0; i < s.length; i++) {
      b.setUint8(off + i, s.codeUnitAt(i));
    }
  }

  str(0, 'RIFF');
  b.setUint32(4, 36 + dataLen, Endian.little);
  str(8, 'WAVE');
  str(12, 'fmt ');
  b.setUint32(16, 16, Endian.little);
  b.setUint16(20, 1, Endian.little); // PCM
  b.setUint16(22, 1, Endian.little); // 单声道
  b.setUint32(24, rate, Endian.little);
  b.setUint32(28, rate * 2, Endian.little);
  b.setUint16(32, 2, Endian.little);
  b.setUint16(34, 16, Endian.little);
  str(36, 'data');
  b.setUint32(40, dataLen, Endian.little);
  for (var i = 0; i < samples.length; i++) {
    b.setInt16(44 + i * 2, (samples[i].clamp(-1.0, 1.0) * 32767).round(), Endian.little);
  }
  return b.buffer.asUint8List();
}
