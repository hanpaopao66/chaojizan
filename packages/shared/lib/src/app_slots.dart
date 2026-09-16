import 'package:flutter/widgets.dart';

/// 底部导航**上方**那条常驻条的插槽。
///
/// 谁用:音乐在放歌时把迷你播放条放进来,离开音乐页面照样跟着;不放歌时是 null,什么都不占。
///
/// **方向是反的才对**:外壳(main.dart 的 HomePage)不认识音乐模块,它只是画出插槽里的东西;
/// 音乐模块自己往里放、自己收走。以后别的模块(比如通话中的悬浮条)也能用同一个插槽。
final ValueNotifier<Widget?> szAboveNavSlot = ValueNotifier<Widget?>(null);
