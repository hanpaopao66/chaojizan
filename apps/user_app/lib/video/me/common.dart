// 视频「我的」、创作中心、互动消息三块共用的小件:按游标翻页的列表、错误怎么摆、提示和确认框。
//
// 放在 me/ 下是因为这三块只有这里是「我的」一侧的公共地基;creator/、notify/ 直接引这个文件。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../api.dart';

/// 一页结果:条目 + 下一页游标(null = 没有了,VIDEO-API 0.5)+ 响应里的其他字段。
typedef CursorPage<T> = ({List<T> items, String? next, Map<String, dynamic> extra});

/// 按游标翻页的列表状态。
///
/// 游标是服务端给的不透明字符串,原样传回;`next_cursor` 为 null 就是到底了。
/// 下拉刷新和上拉加载可能同时在飞:刷新会把代数加一,晚回来的旧页直接丢掉,
/// 不然会出现「刷新后的第一页后面又接上了刷新前的第二页」。
class CursorPager<T> extends ChangeNotifier {
  CursorPager(this._fetch);

  final Future<CursorPage<T>> Function(String? cursor) _fetch;

  final List<T> items = [];
  Map<String, dynamic> extra = const {};
  String? _next;
  bool _end = false;
  int _gen = 0;
  bool _disposed = false;

  bool loading = false;
  bool loaded = false;

  /// 第一页就失败了(整页错误态)
  Object? error;

  /// 翻页 / 刷新失败但手里还有旧数据:列表尾巴上给一个重试
  Object? moreError;

  bool get hasMore => !_end;

  Future<void> refresh() => _load(reset: true);

  Future<void> more() async {
    if (loading || _end || !loaded) return;
    await _load(reset: false);
  }

  Future<void> _load({required bool reset}) async {
    final gen = reset ? ++_gen : _gen;
    loading = true;
    moreError = null;
    if (reset && items.isEmpty) error = null;
    _notify();
    try {
      final page = await _fetch(reset ? null : _next);
      if (gen != _gen || _disposed) return;
      if (reset) items.clear();
      items.addAll(page.items);
      extra = page.extra;
      _next = page.next;
      _end = page.next == null;
      loaded = true;
      error = null;
    } catch (e) {
      if (gen != _gen || _disposed) return;
      if (items.isEmpty && !loaded) {
        error = e;
      } else {
        moreError = e;
      }
    } finally {
      if (gen == _gen && !_disposed) {
        loading = false;
        _notify();
      }
    }
  }

  void removeWhere(bool Function(T item) test) {
    items.removeWhere(test);
    _notify();
  }

  /// 换掉满足条件的那一条;没有的话 [orInsert] 为真就插到最前面(别的设备新建的稿件)
  void upsert(bool Function(T item) test, T item, {bool orInsert = false}) {
    final i = items.indexWhere(test);
    if (i >= 0) {
      items[i] = item;
    } else if (orInsert) {
      items.insert(0, item);
    }
    _notify();
  }

  void touch() => _notify();

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

/// 视频接口的错误怎么摆:503「暂未开放」是开关关着(VIDEO-API 0.2),给空状态、**不给重试**;
/// 其他错误给重试按钮。
Widget videoErrorView(Object? error, VoidCallback onRetry) {
  if (error != null && VideoApi.isOff(error)) {
    return SzEmpty(text: '$error');
  }
  return SzError(error: error, onRetry: onRetry);
}

/// 给用户看的一句话:服务端的 detail 原样展示(VIDEO-API 0.3),网络问题 ApiClient 已经翻成人话。
String videoErrorText(Object e) => e is ApiException ? e.message : '$e';

void vToast(BuildContext context, Object message) {
  ScaffoldMessenger.maybeOf(context)
      ?.showSnackBar(SnackBar(content: Text(message is String ? message : videoErrorText(message))));
}

/// 确认框。[danger] 的确认按钮用错误色(删除、清空这类回不去的动作)。
Future<bool> vConfirm(BuildContext context,
    {required String title, String? body, String ok = '确定', bool danger = false}) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (ctx) => SzDialog(
      title: Text(title),
      content: body == null ? null : Text(body),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
        TextButton(
          style: danger ? TextButton.styleFrom(foregroundColor: Theme.of(ctx).sz.danger) : null,
          onPressed: () => Navigator.pop(ctx, true),
          child: Text(ok),
        ),
      ],
    ),
  );
  return r == true;
}

/// 一行文字输入框(改名、申诉理由)。取消返回 null。
Future<String?> vPrompt(BuildContext context,
    {required String title,
    String initial = '',
    String? hint,
    int? maxLength,
    int maxLines = 1,
    String ok = '确定',
    String? Function(String text)? validate}) async {
  final c = TextEditingController(text: initial);
  String? err;
  // 控制器跟着对话框卸载时再销毁(SzDisposeWith):pop 之后对话框还在退场,不能马上 dispose
  return showDialog<String>(
    context: context,
    builder: (ctx) => SzDisposeWith(
      controllers: [c],
      child: StatefulBuilder(
        builder: (ctx, setLocal) => SzDialog(
          title: Text(title),
          content: TextField(
            controller: c,
            autofocus: true,
            maxLength: maxLength,
            maxLines: maxLines,
            decoration: InputDecoration(hintText: hint, errorText: err),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
            FilledButton(
              onPressed: () {
                final e = validate?.call(c.text);
                if (e != null) {
                  setLocal(() => err = e);
                  return;
                }
                Navigator.pop(ctx, c.text);
              },
              child: Text(ok),
            ),
          ],
        ),
      ),
    ),
  );
}

/// 按游标翻页的列表:下拉刷新、滑到底自动加载下一页、空状态、错误态、尾巴上的「没有更多了」。
///
/// [rowsBuilder] 给了就用它把整页条目摊成若干行(历史按天分组要在中间插日期行);
/// 不给就一条一行走 [itemBuilder]。
class PagedListView<T> extends StatelessWidget {
  const PagedListView({
    super.key,
    required this.pager,
    this.itemBuilder,
    this.rowsBuilder,
    this.header = const [],
    this.emptyText = '这里还没有内容',
    this.divider = true,
    this.padding = const EdgeInsets.only(bottom: 24),
  }) : assert(itemBuilder != null || rowsBuilder != null);

  final CursorPager<T> pager;
  final Widget Function(BuildContext context, T item, int index)? itemBuilder;
  final List<Widget> Function(BuildContext context, List<T> items)? rowsBuilder;
  final List<Widget> header;
  final String emptyText;
  final bool divider;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: pager,
      builder: (context, _) {
        if (!pager.loaded) {
          if (pager.error != null) {
            return ListView(children: [...header, videoErrorView(pager.error, pager.refresh)]);
          }
          return ListView(children: [
            ...header,
            const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator())),
          ]);
        }
        final sz = Theme.of(context).sz;
        final List<Widget> rows;
        if (pager.items.isEmpty) {
          rows = [Padding(padding: const EdgeInsets.only(top: 24), child: SzEmpty(text: emptyText))];
        } else if (rowsBuilder != null) {
          rows = rowsBuilder!(context, pager.items);
        } else {
          rows = [
            for (var i = 0; i < pager.items.length; i++) ...[
              if (divider && i > 0) Divider(height: 1, indent: kPagePad, endIndent: kPagePad, color: sz.line),
              itemBuilder!(context, pager.items[i], i),
            ],
          ];
        }
        final all = [...header, ...rows, _tail(context)];
        return RefreshIndicator(
          onRefresh: pager.refresh,
          // 两种通知都要听:滑动时是 ScrollNotification;一页没铺满屏幕(大屏、条目矮)时根本滑不动,
          // 只有布局完成时的 ScrollMetricsNotification —— 不听它的话下一页永远不会来
          child: NotificationListener<ScrollMetricsNotification>(
            onNotification: (n) {
              if (n.metrics.extentAfter < 400) unawaited(pager.more());
              return false;
            },
            child: NotificationListener<ScrollNotification>(
              onNotification: (n) {
                // 离底部还剩不到一屏的一半就去拿下一页,滑到底的时候数据已经在了
                if (n.metrics.extentAfter < 400) unawaited(pager.more());
                return false;
              },
              child: ListView.builder(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: padding,
                itemCount: all.length,
                itemBuilder: (context, i) => all[i],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _tail(BuildContext context) {
    final sz = Theme.of(context).sz;
    if (pager.moreError != null) {
      return Center(
        child: TextButton(
          onPressed: pager.hasMore ? pager.more : pager.refresh,
          child: Text('${videoErrorText(pager.moreError!)},点这里重试'),
        ),
      );
    }
    if (pager.loading) {
      return const Padding(
        padding: EdgeInsets.all(16),
        child: Center(child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))),
      );
    }
    if (!pager.hasMore && pager.items.isNotEmpty) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Center(child: Text('没有更多了', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted))),
      );
    }
    return const SizedBox(height: 16);
  }
}

/// 要登录才有内容的页:没登录时整页是一个登录引导,登录成功后 [onLoggedIn] 重新加载。
class VideoLoginGate extends StatelessWidget {
  const VideoLoginGate({super.key, required this.text, required this.onLoggedIn});

  final String text;
  final VoidCallback onLoggedIn;

  @override
  Widget build(BuildContext context) => SzEmpty(
        text: text,
        actionLabel: '登录 / 注册',
        onAction: () async {
          if (await ensureLoggedIn(context)) onLoggedIn();
        },
      );
}

/// 小节标题(和 lib/chat 的设置页一个样子:clay 色小字)。
class VSection extends StatelessWidget {
  const VSection(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 18, kPagePad, 8),
      child: Row(children: [
        Expanded(
          child: Text(text, style: TextStyle(fontSize: kFontBodyLg, color: sz.clay, fontWeight: FontWeight.w600)),
        ),
        if (trailing != null) trailing!,
      ]),
    );
  }
}

/// 状态小标签(描边胶囊,颜色按语义给)。
class VTag extends StatelessWidget {
  const VTag(this.label, {super.key, this.color});

  final String label;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final c = color ?? sz.inkMuted;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
        border: Border.all(color: c.withValues(alpha: .6)),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(label, style: TextStyle(fontSize: kFontMicro, color: c, height: 1.4)),
    );
  }
}

/// 两位数补零 + 「M月D日 HH:mm」这类时间文字,几个页面都要用。
String vTwo(int n) => n.toString().padLeft(2, '0');

String vHm(DateTime t) => '${vTwo(t.hour)}:${vTwo(t.minute)}';

/// 「9月14日 20:00」;不是今年的带年份。
String vDateTime(DateTime t, [DateTime? now]) {
  final n = now ?? DateTime.now();
  final d = t.year == n.year ? '${t.month}月${t.day}日' : '${t.year}年${t.month}月${t.day}日';
  return '$d ${vHm(t)}';
}
