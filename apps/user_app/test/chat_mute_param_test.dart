import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/chat/pages/pickers.dart' show muteParam;

/// 免打扰:服务端 `PATCH /chat/v1/dialogs/{id}` 的 `muted_until` 收的是「从现在起多少秒」或 "forever"
/// (chat_store.update_dialog,e2e_chat_private 也是这么传的)。客户端原来传 ISO 时间,每一次点免打扰都是 422。
void main() {
  test('免打扰传给服务端的是秒数或 forever,不是时间戳', () {
    final t = DateTime(2026, 9, 13, 12);
    expect(muteParam(null), isNull, reason: 'null = 取消免打扰');
    expect(muteParam(t.add(const Duration(hours: 1)), t), 3600);
    expect(muteParam(t.add(const Duration(hours: 8)), t), 28800);
    expect(muteParam(t.add(const Duration(days: 2)), t), 172800);
    expect(muteParam(t.add(const Duration(days: 3650)), t), 'forever', reason: '「永久」是 3650 天');
    expect(muteParam(t.subtract(const Duration(seconds: 5)), t), 1, reason: '已经过去的时刻也不能传负数');
  });
}
