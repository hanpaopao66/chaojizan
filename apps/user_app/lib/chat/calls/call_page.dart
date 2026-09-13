import 'package:flutter/material.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:superz_shared/superz_shared.dart';

import '../ui/avatar.dart';
import 'call_controller.dart';

/// 通话页(来电、呼叫中、通话中、结束)。整页深色,视频通话时对方画面铺满、自己的在右上角。
///
/// 左上角的「收起」只是把页面关掉,通话继续 —— 首页顶上会出一条「通话中」,点一下回来。
class CallPage extends StatefulWidget {
  const CallPage({super.key});

  @override
  State<CallPage> createState() => _CallPageState();
}

class _CallPageState extends State<CallPage> {
  CallController get c => CallController.instance;

  @override
  void initState() {
    super.initState();
    c.pageVisible = true;
    c.addListener(_on);
  }

  @override
  void dispose() {
    c.removeListener(_on);
    c.pageVisible = false;
    super.dispose();
  }

  void _on() {
    if (!mounted) return;
    if (c.phase == CallPhase.idle) {
      Navigator.of(context).maybePop();
      return;
    }
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final showRemoteVideo = c.video && c.hasRemoteVideo && !c.peerCameraOff && c.phase == CallPhase.active;
    final showLocalVideo = c.video && !c.cameraOff && c.phase != CallPhase.incoming && c.phase != CallPhase.ended;
    return Theme(
      data: brandTheme(Brightness.dark),
      child: Scaffold(
        backgroundColor: const Color(0xFF1B1E24),
        body: Stack(children: [
          if (showRemoteVideo)
            Positioned.fill(
              child: RTCVideoView(c.remoteRenderer, objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitCover),
            )
          else
            // 纯语音 / 对方关了摄像头:也要把对方的声音放出来 —— 网页上声音跟着这个渲染器走
            Positioned(left: 0, top: 0, width: 1, height: 1, child: RTCVideoView(c.remoteRenderer)),
          SafeArea(
            child: Column(children: [
              Row(children: [
                IconButton(
                  tooltip: '收起',
                  icon: const Icon(Icons.keyboard_arrow_down, size: 30),
                  onPressed: () => Navigator.of(context).maybePop(),
                ),
                const Spacer(),
                Text(c.video ? '视频通话' : '语音通话', style: const TextStyle(color: Colors.white70)),
                const Spacer(),
                const SizedBox(width: 48),
              ]),
              if (!showRemoteVideo) ...[
                const SizedBox(height: 48),
                ChatAvatar(name: c.peerName, url: c.peerAvatar, size: 112),
                const SizedBox(height: 16),
                Text(c.peerName,
                    style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600, color: Colors.white)),
                const SizedBox(height: 8),
                Text(_statusText(), style: const TextStyle(color: Colors.white70)),
                if (c.phase == CallPhase.active && c.peerMuted)
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: Text('对方已静音', style: TextStyle(color: Colors.white54, fontSize: kFontNote)),
                  ),
                if (c.phase == CallPhase.active && c.video && c.peerCameraOff)
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: Text('对方关了摄像头', style: TextStyle(color: Colors.white54, fontSize: kFontNote)),
                  ),
              ] else ...[
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text('${c.peerName}  ${_statusText()}',
                      style: const TextStyle(color: Colors.white, shadows: [Shadow(blurRadius: 6)])),
                ),
              ],
              const Spacer(),
              _controls(),
              const SizedBox(height: 28),
            ]),
          ),
          if (showLocalVideo)
            Positioned(
              right: 16,
              top: MediaQuery.of(context).padding.top + 56,
              width: 108,
              height: 150,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: RTCVideoView(c.localRenderer,
                    mirror: true, objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitCover),
              ),
            ),
        ]),
      ),
    );
  }

  String _statusText() => switch (c.phase) {
        CallPhase.active => c.timerText,
        CallPhase.ended => c.endText,
        _ => c.status,
      };

  Widget _controls() {
    if (c.phase == CallPhase.ended) return const SizedBox(height: 72);
    if (c.phase == CallPhase.incoming) {
      return Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
        _RoundButton(icon: Icons.call_end, label: '拒绝', color: const Color(0xFFE5484D), onTap: c.decline),
        if (c.video)
          _RoundButton(icon: Icons.mic, label: '只开语音', color: Colors.white24, onTap: () => c.accept(withVideo: false)),
        _RoundButton(
          icon: c.video ? Icons.videocam : Icons.call,
          label: '接听',
          color: const Color(0xFF30A46C),
          onTap: () => c.accept(),
        ),
      ]);
    }
    return Column(children: [
      Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
        _RoundButton(
          icon: c.muted ? Icons.mic_off : Icons.mic_none,
          label: c.muted ? '已静音' : '静音',
          color: c.muted ? Colors.white : Colors.white24,
          fg: c.muted ? Colors.black : Colors.white,
          onTap: c.toggleMute,
        ),
        _RoundButton(
          icon: c.speaker ? Icons.volume_up : Icons.volume_down_outlined,
          label: '免提',
          color: c.speaker ? Colors.white : Colors.white24,
          fg: c.speaker ? Colors.black : Colors.white,
          onTap: c.toggleSpeaker,
        ),
        if (c.video)
          _RoundButton(
            icon: c.cameraOff ? Icons.videocam_off : Icons.videocam_outlined,
            label: c.cameraOff ? '摄像头已关' : '摄像头',
            color: c.cameraOff ? Colors.white : Colors.white24,
            fg: c.cameraOff ? Colors.black : Colors.white,
            onTap: c.toggleCamera,
          ),
        if (c.video)
          _RoundButton(icon: Icons.cameraswitch_outlined, label: '翻转', color: Colors.white24, onTap: c.switchCamera),
      ]),
      const SizedBox(height: 22),
      _RoundButton(icon: Icons.call_end, label: '挂断', color: const Color(0xFFE5484D), onTap: c.hangup, size: 68),
    ]);
  }
}

class _RoundButton extends StatelessWidget {
  const _RoundButton({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
    this.fg = Colors.white,
    this.size = 60,
  });

  final IconData icon;
  final String label;
  final Color color;
  final Color fg;
  final VoidCallback onTap;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Semantics(
        button: true,
        label: label,
        child: InkResponse(
          onTap: onTap,
          radius: size / 2 + 6,
          child: Container(
            width: size,
            height: size,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
            child: Icon(icon, color: fg, size: size * .45),
          ),
        ),
      ),
      const SizedBox(height: 6),
      Text(label, style: const TextStyle(color: Colors.white70, fontSize: kFontNote)),
    ]);
  }
}

/// 首页顶上的「通话中」小条:通话页收起之后显示,点一下回到通话页。
class CallPill extends StatelessWidget {
  const CallPill({super.key, required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = CallController.instance;
    final text = switch (c.phase) {
      CallPhase.active => '与 ${c.peerName} 通话中 ${c.timerText}',
      CallPhase.incoming => '${c.peerName} ${c.status}',
      _ => '${c.peerName} ${c.status}',
    };
    return SafeArea(
      bottom: false,
      child: Align(
        alignment: Alignment.topCenter,
        child: Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Material(
            color: const Color(0xFF30A46C),
            borderRadius: BorderRadius.circular(20),
            elevation: 4,
            child: InkWell(
              onTap: onTap,
              borderRadius: BorderRadius.circular(20),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(c.video ? Icons.videocam : Icons.call, color: Colors.white, size: 16),
                  const SizedBox(width: 6),
                  Text(text, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
