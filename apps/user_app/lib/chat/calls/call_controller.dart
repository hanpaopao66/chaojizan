import 'dart:async';
import 'dart:math';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';

import '../store.dart';
import 'ringtone.dart';

/// 通话进行到哪一步。
enum CallPhase { idle, outgoing, incoming, connecting, active, ended }

/// 1 对 1 语音 / 视频通话(DEV-PROMPTS-40 §5.12,#354)。单例:同一时间只有一通。
///
/// 信令走 `/ws/v2` 的 call 帧(服务端 services/calls.py 转发、记录),媒体走 WebRTC:
///
/// - 主叫:拿麦克风(和摄像头)→ 建 PeerConnection → createOffer → 发 invite;
///   收到 accept 设对方的 answer;
/// - 被叫:收到 incoming(带 offer)先响铃,点接听才拿麦克风 → 设 offer → createAnswer → 发 accept;
/// - 两边的 ICE 候选互相转;对方的 sdp 还没设好时先攒着,设好了再一起加。
///
/// 页面用 [CallController.instance] 听状态;首页挂了 [presenter](有来电 / 开始打电话时推出通话页)。
class CallController extends ChangeNotifier {
  CallController._();

  static final CallController instance = CallController._();

  CallPhase phase = CallPhase.idle;
  String? callId;
  bool video = false;
  bool outgoing = false;
  int peerId = 0;
  String peerName = '';
  String peerAvatar = '';

  /// 状态说明(「正在呼叫…」「对方响铃中…」「连接中…」)
  String status = '';

  /// 结束时说一句(「对方已拒绝」「通话结束 01:23」)
  String endText = '';
  DateTime? answeredAt;

  bool muted = false;
  bool speaker = false;
  bool cameraOff = false;
  bool peerCameraOff = false;
  bool peerMuted = false;

  final RTCVideoRenderer localRenderer = RTCVideoRenderer();
  final RTCVideoRenderer remoteRenderer = RTCVideoRenderer();
  bool _renderers = false;
  bool hasRemoteVideo = false;

  RTCPeerConnection? _pc;
  MediaStream? _local;
  String? _offerSdp;
  final List<RTCIceCandidate> _pendingIce = [];
  bool _remoteSet = false;
  Timer? _tick;
  Timer? _closeTimer;
  AudioPlayer? _ring;

  /// 首页设:把通话页推出来(来电、开始呼叫时)
  VoidCallback? presenter;

  /// 通话页现在是不是开着(关着的时候首页顶上显示「通话中」小条)
  bool get pageVisible => _pageVisible;
  bool _pageVisible = false;
  set pageVisible(bool v) {
    if (_pageVisible == v) return;
    _pageVisible = v;
    notifyListeners();
  }

  bool _attached = false;

  ChatStore get _store => ChatStore.instance;

  bool get busy => phase != CallPhase.idle && phase != CallPhase.ended;

  /// 通话时长(秒),没接通是 0
  int get seconds => answeredAt == null ? 0 : DateTime.now().difference(answeredAt!).inSeconds;

  void attach() {
    if (_attached) return;
    _attached = true;
    _store.realtime.addListener(_onFrame);
  }

  void detach() {
    if (!_attached) return;
    _attached = false;
    _store.realtime.removeListener(_onFrame);
    if (busy) hangup();
  }

  static String _newCallId() {
    final r = Random.secure();
    return List.generate(16, (_) => r.nextInt(16).toRadixString(16)).join();
  }

  // ---------------- 主叫 ----------------

  /// 给某人打电话。已经在通话里就不打(返回 false)。
  Future<bool> start(int userId, String name, String avatar, {required bool video}) async {
    if (busy) return false;
    _reset();
    outgoing = true;
    this.video = video;
    peerId = userId;
    peerName = name;
    peerAvatar = avatar;
    callId = _newCallId();
    phase = CallPhase.outgoing;
    status = '正在呼叫…';
    notifyListeners();
    presenter?.call();
    try {
      await _ensureRenderers();
      await _openPeer();
      await _openLocal();
      final offer = await _pc!.createOffer({'offerToReceiveAudio': true, 'offerToReceiveVideo': video});
      await _pc!.setLocalDescription(offer);
      if (phase != CallPhase.outgoing) return true; // 这期间已经挂了
      _send({'a': 'invite', 'to': userId, 'video': video, 'sdp': offer.sdp});
      unawaited(_playRing(incoming: false));
    } catch (e) {
      _finishLocal(_mediaError(e));
    }
    return true;
  }

  // ---------------- 被叫 ----------------

  Future<void> accept({bool withVideo = true}) async {
    if (phase != CallPhase.incoming) return;
    await _stopRing();
    if (!withVideo) video = false;
    phase = CallPhase.connecting;
    status = '连接中…';
    notifyListeners();
    try {
      await _ensureRenderers();
      await _openPeer();
      await _openLocal();
      await _pc!.setRemoteDescription(RTCSessionDescription(_offerSdp, 'offer'));
      _remoteSet = true;
      await _flushIce();
      final answer = await _pc!.createAnswer({'offerToReceiveAudio': true, 'offerToReceiveVideo': true});
      await _pc!.setLocalDescription(answer);
      _send({'a': 'accept', 'sdp': answer.sdp});
    } catch (e) {
      _send({'a': 'hangup'});
      _finishLocal(_mediaError(e));
    }
  }

  void decline() {
    if (phase != CallPhase.incoming) return;
    _send({'a': 'decline'});
    _finishLocal('已拒绝');
  }

  // ---------------- 通话中 ----------------

  void hangup() {
    if (!busy) return;
    _send({'a': 'hangup'});
    _finishLocal(answeredAt == null ? (outgoing ? '已取消' : '已拒绝') : '通话结束 ${_fmt(seconds)}');
  }

  void toggleMute() {
    muted = !muted;
    for (final t in _local?.getAudioTracks() ?? const <MediaStreamTrack>[]) {
      t.enabled = !muted;
    }
    _send({'a': 'media', 'video': video && !cameraOff, 'muted': muted});
    notifyListeners();
  }

  Future<void> toggleSpeaker() async {
    speaker = !speaker;
    if (!kIsWeb) {
      try {
        await Helper.setSpeakerphoneOn(speaker);
      } catch (_) {}
    }
    notifyListeners();
  }

  void toggleCamera() {
    final tracks = _local?.getVideoTracks() ?? const <MediaStreamTrack>[];
    if (tracks.isEmpty) return;
    cameraOff = !cameraOff;
    for (final t in tracks) {
      t.enabled = !cameraOff;
    }
    _send({'a': 'media', 'video': !cameraOff, 'muted': muted});
    notifyListeners();
  }

  Future<void> switchCamera() async {
    final tracks = _local?.getVideoTracks() ?? const <MediaStreamTrack>[];
    if (tracks.isEmpty) return;
    try {
      await Helper.switchCamera(tracks.first);
    } catch (_) {}
  }

  // ---------------- 信令 ----------------

  void _send(Map<String, dynamic> f) {
    if (callId == null) return;
    _store.realtime.send({'t': 'call', 'call_id': callId, ...f});
  }

  void _onFrame(Map<String, dynamic> f) {
    if (f['t'] != 'call') return;
    final a = '${f['a']}';
    final id = '${f['call_id'] ?? ''}';
    if (a == 'incoming') {
      _onIncoming(f);
      return;
    }
    if (id.isEmpty || id != callId) return;
    switch (a) {
      case 'ringing':
        if (phase == CallPhase.outgoing) {
          status = '对方响铃中…';
          notifyListeners();
        }
      case 'accept':
        unawaited(_onAccepted('${f['sdp'] ?? ''}'));
      case 'taken':
        // 我的另一台设备接了 / 拒了:这台别再响
        if (phase == CallPhase.incoming) _finishLocal('已在其他设备上处理', quiet: true);
      case 'ice':
        unawaited(_onIce((f['candidate'] as Map?)?.cast<String, dynamic>()));
      case 'media':
        peerCameraOff = f['video'] == false;
        peerMuted = f['muted'] == true;
        notifyListeners();
      case 'declined':
        _finishLocal('对方已拒绝');
      case 'busy':
        _finishLocal('对方正在通话中');
      case 'missed':
        _finishLocal(outgoing ? '无人接听' : '未接来电');
      case 'hangup':
        _finishLocal(answeredAt == null ? (outgoing ? '对方已拒绝' : '对方已取消') : '对方已挂断 ${_fmt(seconds)}');
      case 'gone':
        _finishLocal('这通电话已经结束了');
      case 'error':
        _finishLocal('${f['message'] ?? '没打通'}');
    }
  }

  void _onIncoming(Map<String, dynamic> f) {
    if (busy) return; // 服务端会给对方回忙线;这里保险起见再挡一次
    _reset();
    final from = (f['from'] as Map?)?.cast<String, dynamic>() ?? const {};
    outgoing = false;
    callId = '${f['call_id']}';
    video = f['video'] == true;
    peerId = (from['id'] as num?)?.toInt() ?? 0;
    final u = _store.users[peerId];
    peerName = (u?.displayName.isNotEmpty ?? false) ? u!.displayName : '${from['name'] ?? '对方'}';
    peerAvatar = '${from['avatar'] ?? u?.avatar ?? ''}';
    _offerSdp = '${f['sdp'] ?? ''}';
    phase = CallPhase.incoming;
    status = video ? '邀请你视频通话' : '邀请你语音通话';
    _send({'a': 'ringing'});
    notifyListeners();
    unawaited(_playRing(incoming: true));
    presenter?.call();
  }

  Future<void> _onAccepted(String sdp) async {
    if (phase != CallPhase.outgoing || _pc == null) return;
    await _stopRing();
    phase = CallPhase.connecting;
    status = '连接中…';
    notifyListeners();
    try {
      await _pc!.setRemoteDescription(RTCSessionDescription(sdp, 'answer'));
      _remoteSet = true;
      await _flushIce();
    } catch (e) {
      hangup();
    }
  }

  Future<void> _onIce(Map<String, dynamic>? c) async {
    if (c == null) return;
    final cand = RTCIceCandidate('${c['candidate'] ?? ''}', c['sdpMid'] as String?, (c['sdpMLineIndex'] as num?)?.toInt());
    if (_pc == null || !_remoteSet) {
      _pendingIce.add(cand);
      return;
    }
    try {
      await _pc!.addCandidate(cand);
    } catch (_) {}
  }

  Future<void> _flushIce() async {
    final list = [..._pendingIce];
    _pendingIce.clear();
    for (final c in list) {
      try {
        await _pc!.addCandidate(c);
      } catch (_) {}
    }
  }

  // ---------------- WebRTC ----------------

  Future<void> _ensureRenderers() async {
    if (_renderers) return;
    await localRenderer.initialize();
    await remoteRenderer.initialize();
    _renderers = true;
  }

  Future<void> _openPeer() async {
    final ice = await _store.api.iceServers();
    final pc = await createPeerConnection({
      'iceServers': ice,
      'sdpSemantics': 'unified-plan',
    });
    _pc = pc;
    pc.onIceCandidate = (c) {
      if (c.candidate == null || c.candidate!.isEmpty) return;
      _send({
        'a': 'ice',
        'candidate': {'candidate': c.candidate, 'sdpMid': c.sdpMid, 'sdpMLineIndex': c.sdpMLineIndex},
      });
    };
    pc.onTrack = (e) {
      if (e.streams.isEmpty) return;
      remoteRenderer.srcObject = e.streams.first;
      if (e.track.kind == 'video') hasRemoteVideo = true;
      notifyListeners();
    };
    pc.onConnectionState = (s) {
      switch (s) {
        case RTCPeerConnectionState.RTCPeerConnectionStateConnected:
          if (phase == CallPhase.connecting || phase == CallPhase.outgoing) {
            phase = CallPhase.active;
            answeredAt ??= DateTime.now();
            status = '';
            _tick?.cancel();
            _tick = Timer.periodic(const Duration(seconds: 1), (_) => notifyListeners());
            notifyListeners();
          }
        case RTCPeerConnectionState.RTCPeerConnectionStateFailed:
          if (busy) {
            _send({'a': 'hangup'});
            _finishLocal('网络断了,通话结束');
          }
        default:
      }
    };
  }

  Future<void> _openLocal() async {
    final stream = await navigator.mediaDevices.getUserMedia({
      'audio': true,
      'video': video ? {'facingMode': 'user', 'width': 640, 'height': 480} : false,
    });
    _local = stream;
    localRenderer.srcObject = stream;
    for (final t in stream.getTracks()) {
      await _pc!.addTrack(t, stream);
    }
    // 视频通话默认外放(和打电话贴耳朵不一样)
    if (video && !kIsWeb) {
      speaker = true;
      try {
        await Helper.setSpeakerphoneOn(true);
      } catch (_) {}
    }
  }

  static String _mediaError(Object e) {
    final s = '$e'.toLowerCase();
    if (s.contains('permission') || s.contains('notallowed') || s.contains('denied')) {
      return '没有麦克风或摄像头权限,到系统设置里打开';
    }
    return '没能打开麦克风或摄像头';
  }

  // ---------------- 铃声 ----------------

  Future<void> _playRing({required bool incoming}) async {
    await _stopRing();
    try {
      final p = AudioPlayer();
      _ring = p;
      await p.setReleaseMode(ReleaseMode.loop);
      await p.play(BytesSource(synthRingtone(incoming: incoming), mimeType: 'audio/wav'));
    } catch (_) {
      // 放不出声(网页没交互过、静音模式)不影响通话本身
    }
  }

  Future<void> _stopRing() async {
    final p = _ring;
    _ring = null;
    if (p == null) return;
    try {
      await p.stop();
      await p.dispose();
    } catch (_) {}
  }

  // ---------------- 收尾 ----------------

  void _finishLocal(String text, {bool quiet = false}) {
    if (phase == CallPhase.idle) return;
    endText = text;
    phase = CallPhase.ended;
    _cleanup();
    notifyListeners();
    _closeTimer?.cancel();
    _closeTimer = Timer(Duration(milliseconds: quiet ? 10 : 1600), () {
      if (phase == CallPhase.ended) {
        phase = CallPhase.idle;
        callId = null;
        notifyListeners();
      }
    });
  }

  void _cleanup() {
    unawaited(_stopRing());
    _tick?.cancel();
    _tick = null;
    try {
      for (final t in _local?.getTracks() ?? const <MediaStreamTrack>[]) {
        t.stop();
      }
      _local?.dispose();
    } catch (_) {}
    _local = null;
    try {
      _pc?.close();
    } catch (_) {}
    _pc = null;
    if (_renderers) {
      localRenderer.srcObject = null;
      remoteRenderer.srcObject = null;
    }
    _pendingIce.clear();
    _remoteSet = false;
    if (speaker && !kIsWeb) {
      unawaited(Helper.setSpeakerphoneOn(false).catchError((_) {}));
    }
  }

  void _reset() {
    _closeTimer?.cancel();
    _cleanup();
    callId = null;
    answeredAt = null;
    muted = false;
    speaker = false;
    cameraOff = false;
    peerCameraOff = false;
    peerMuted = false;
    hasRemoteVideo = false;
    endText = '';
    status = '';
    _offerSdp = null;
  }

  static String _fmt(int s) => '${(s ~/ 60).toString().padLeft(2, '0')}:${(s % 60).toString().padLeft(2, '0')}';

  String get timerText => _fmt(seconds);
}
