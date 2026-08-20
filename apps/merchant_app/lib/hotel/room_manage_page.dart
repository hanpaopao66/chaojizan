import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

/// 房型房价 tab:上段切换「房型管理 / 房价房态日历」。
/// 对标携程 eBooking:日历合并房价与房态,点单格改当日,批量按区间设置。
class RoomManagePage extends StatefulWidget {
  const RoomManagePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RoomManagePage> createState() => _RoomManagePageState();
}

class _RoomManagePageState extends State<RoomManagePage> {
  int _segment = 0; // 0 房型 / 1 日历
  List<RoomType> _roomTypes = [];
  List<RoomCalendarRow> _calendar = [];
  DateTime _calendarStart = DateTime.now();
  bool _loaded = false;

  static const _days = 14; // 日历一屏 14 天,可前后翻页

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  String _fmt(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  Future<void> _refresh() async {
    try {
      final types = await widget.api.stayRoomTypes();
      final calendar = await widget.api
          .stayCalendar(fromDate: _fmt(_calendarStart), days: _days);
      if (mounted) {
        setState(() {
          _roomTypes = types;
          _calendar = calendar;
          _loaded = true;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _loaded = true);
        _snack(e is ApiException ? e.message : '$e');
      }
    }
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return const Center(child: CircularProgressIndicator());
    }
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
        child: SegmentedButton<int>(
          segments: const [
            ButtonSegment(value: 0, label: Text('房型管理')),
            ButtonSegment(value: 1, label: Text('房价房态日历')),
          ],
          selected: {_segment},
          onSelectionChanged: (s) => setState(() => _segment = s.first),
        ),
      ),
      Expanded(child: _segment == 0 ? _typeList() : _calendarView()),
    ]);
  }

  // ---------- 房型管理 ----------

  Widget _typeList() {
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
        children: [
          if (_roomTypes.isEmpty)
            const SzEmpty(
                art: BrandArt.bowl,
                text: '还没有房型\n先建房型,再到「房价房态日历」设价开卖')
          else
            SzCard(
              padding: EdgeInsets.zero,
              child: Column(children: [
                for (final (i, rt) in _roomTypes.indexed) ...[
                  if (i > 0)
                    Divider(height: 1, color: Theme.of(context).sz.line),
                  _roomTypeRow(rt),
                ],
              ]),
            ),
          const SizedBox(height: 12),
          OutlinedButton(
            onPressed: () => _editType(null),
            child: const Text('新增房型'),
          ),
        ],
      ),
    );
  }

  /// 房型一行:缩略图 + 名称与规格 + 上下架开关 + 编辑。
  /// 下架的房型名称走弱化色而不是删除线——删除线在长名称上很难读。
  Widget _roomTypeRow(RoomType rt) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 10),
      child: Row(children: [
        SzImage(
            url: rt.imageUrls.isEmpty
                ? ''
                : widget.api.resolveUrl(rt.imageUrls.first),
            name: rt.name,
            size: 46,
            categoryIcon: Icons.bed_outlined),
        const SizedBox(width: 11),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(rt.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w600,
                      color: rt.isOnSale ? sz.ink : sz.inkMuted)),
              const SizedBox(height: 2),
              Text(
                  [
                    if (rt.bedType.isNotEmpty) rt.bedType,
                    if (rt.areaM2 > 0) '${rt.areaM2}㎡',
                    '住 ${rt.maxGuests} 人',
                    rt.policyLabel,
                  ].join(' · '),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 11, color: sz.inkMuted)),
            ],
          ),
        ),
        Switch(
          value: rt.isOnSale,
          onChanged: (v) async {
            try {
              await widget.api.updateRoomType(rt.id, {'is_on_sale': v});
              _refresh();
            } catch (e) {
              _snack(e is ApiException ? e.message : '$e');
            }
          },
        ),
        IconButton(
            tooltip: '编辑',
            icon: const Icon(Icons.edit_outlined, size: 19),
            onPressed: () => _editType(rt)),
      ]),
    );
  }

  Future<void> _editType(RoomType? existing) async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(
        builder: (_) => RoomTypeEditPage(api: widget.api, existing: existing)));
    if (saved == true) _refresh();
  }

  // ---------- 房价房态日历 ----------

  Widget _calendarView() {
    if (_roomTypes.isEmpty) {
      return const SzEmpty(
          art: BrandArt.bowl, text: '先到「房型管理」建房型\n建好后才能在这里设价开卖');
    }
    final dates = [
      for (var i = 0; i < _days; i++) _calendarStart.add(Duration(days: i))
    ];
    final byRt = {for (final row in _calendar) row.roomTypeId: row};
    return Column(children: [
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        IconButton(
            tooltip: '上一段日期',
            icon: const Icon(Icons.chevron_left),
            onPressed: _calendarStart.isAfter(DateTime.now())
                ? () {
                    setState(() => _calendarStart =
                        _calendarStart.subtract(const Duration(days: _days)));
                    _refresh();
                  }
                : null),
        Text(
            '${_fmt(dates.first).substring(5)} ~ ${_fmt(dates.last).substring(5)}',
            style: Theme.of(context).textTheme.titleSmall),
        IconButton(
            tooltip: '下一段日期',
            icon: const Icon(Icons.chevron_right),
            onPressed: () {
              setState(() => _calendarStart =
                  _calendarStart.add(const Duration(days: _days)));
              _refresh();
            }),
      ]),
      Expanded(
        child: SingleChildScrollView(
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columnSpacing: 8,
              horizontalMargin: 8,
              columns: [
                const DataColumn(label: Text('房型')),
                for (final d in dates)
                  DataColumn(label: Text('${d.month}/${d.day}')),
              ],
              rows: [
                for (final rt in _roomTypes)
                  DataRow(cells: [
                    DataCell(SizedBox(
                        width: 72,
                        child: Text(rt.name,
                            maxLines: 2, overflow: TextOverflow.ellipsis))),
                    for (final d in dates) _dayCell(rt, byRt[rt.id], d),
                  ]),
              ],
            ),
          ),
        ),
      ),
      SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              icon: const Icon(Icons.edit_calendar_outlined),
              label: const Text('批量设置(区间 × 多房型)'),
              onPressed: _batchSheet,
            ),
          ),
        ),
      ),
    ]);
  }

  DataCell _dayCell(RoomType rt, RoomCalendarRow? row, DateTime d) {
    final dateStr = _fmt(d);
    RoomDay? day;
    for (final x in row?.days ?? const <RoomDay>[]) {
      if (x.date == dateStr) {
        day = x;
        break;
      }
    }
    final isPast = d.isBefore(DateTime(
        DateTime.now().year, DateTime.now().month, DateTime.now().day));
    final sz = Theme.of(context).sz;
    Widget child;
    if (day == null) {
      child = Text('未设价', style: TextStyle(fontSize: 11, color: sz.inkMuted));
    } else if (day.closed) {
      // 关房是店家自己关的,不是错误——用弱化色不用 danger
      child = Text('关房', style: TextStyle(fontSize: 11, color: sz.inkMuted));
    } else {
      child = Column(mainAxisSize: MainAxisSize.min, children: [
        Text('¥${(day.priceCents / 100).toStringAsFixed(0)}',
            style: szMoney(
                fontSize: 12, fontWeight: FontWeight.w600, color: sz.ink)),
        Text('余 ${day.leftQty}',
            style: TextStyle(
                fontSize: 10.5,
                // 卖光了才是要你动手的信号
                color: day.leftQty <= 0 ? sz.danger : sz.inkMuted)),
      ]);
    }
    return DataCell(
      Opacity(opacity: isPast ? 0.4 : 1, child: Center(child: child)),
      onTap: isPast ? null : () => _cellSheet(rt, dateStr, day),
    );
  }

  /// 单格编辑:改这一天的价/量/开关房
  Future<void> _cellSheet(RoomType rt, String dateStr, RoomDay? day) async {
    final price = TextEditingController(
        text: day == null ? '' : (day.priceCents / 100).toStringAsFixed(0));
    final qty = TextEditingController(text: '${day?.totalQty ?? 1}');
    var closed = day?.closed ?? false;
    final ok = await szShowSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) => Padding(
          padding: EdgeInsets.only(
              left: 16, right: 16, top: 16,
              bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text('${rt.name} · $dateStr',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 12),
            TextField(
                controller: price,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: '当晚价格(元)', border: OutlineInputBorder())),
            const SizedBox(height: 12),
            TextField(
                controller: qty,
                keyboardType: TextInputType.number,
                decoration: InputDecoration(
                    labelText: '可售总量(间)',
                    helperText: day == null ? null : '已售 ${day.soldQty} 间,总量不能低于已售',
                    border: const OutlineInputBorder())),
            SwitchListTile(
                title: const Text('关房(暂停售卖当晚)'),
                value: closed,
                onChanged: (v) => setSheet(() => closed = v)),
            const SizedBox(height: 8),
            SizedBox(
                width: double.infinity,
                child: FilledButton(
                    onPressed: () => Navigator.pop(sheetContext, true),
                    child: const Text('保存'))),
          ]),
        ),
      ),
    );
    if (ok != true) return;
    final priceCents = ((double.tryParse(price.text) ?? 0) * 100).round();
    try {
      await widget.api.setStayCalendar(
        roomTypeIds: [rt.id],
        fromDate: dateStr,
        toDate: dateStr,
        priceCents: priceCents > 0 ? priceCents : null,
        totalQty: int.tryParse(qty.text),
        closed: closed,
      );
      _refresh();
    } catch (e) {
      _snack(e is ApiException ? e.message : '$e');
    }
  }

  /// 批量设置:日期区间 × 多房型,只提交填写过的项
  Future<void> _batchSheet() async {
    var from = DateTime.now();
    var to = DateTime.now().add(const Duration(days: 29));
    final selected = {for (final rt in _roomTypes) rt.id: true};
    final price = TextEditingController();
    final qty = TextEditingController();
    bool? closed;
    final ok = await szShowSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) => Padding(
          padding: EdgeInsets.only(
              left: 16, right: 16, top: 16,
              bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('批量设置', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 4),
                Text('未填写的项保持不变;首次开放的日期必须填价格',
                    style: Theme.of(context).textTheme.bodySmall),
                const SizedBox(height: 12),
                Row(children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () async {
                        final picked = await showDatePicker(
                            context: sheetContext,
                            initialDate: from,
                            firstDate: DateTime.now(),
                            lastDate:
                                DateTime.now().add(const Duration(days: 120)));
                        if (picked != null) setSheet(() => from = picked);
                      },
                      child: Text('从 ${_fmt(from).substring(5)}'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () async {
                        final picked = await showDatePicker(
                            context: sheetContext,
                            initialDate: to,
                            firstDate: DateTime.now(),
                            lastDate:
                                DateTime.now().add(const Duration(days: 120)));
                        if (picked != null) setSheet(() => to = picked);
                      },
                      child: Text('到 ${_fmt(to).substring(5)}'),
                    ),
                  ),
                ]),
                const SizedBox(height: 8),
                Wrap(spacing: 8, children: [
                  for (final rt in _roomTypes)
                    FilterChip(
                      label: Text(rt.name),
                      selected: selected[rt.id] ?? false,
                      onSelected: (v) => setSheet(() => selected[rt.id] = v),
                    ),
                ]),
                const SizedBox(height: 8),
                TextField(
                    controller: price,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        labelText: '每晚价格(元,不改就留空)',
                        border: OutlineInputBorder())),
                const SizedBox(height: 12),
                TextField(
                    controller: qty,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                        labelText: '可售总量(间,不改就留空)',
                        border: OutlineInputBorder())),
                const SizedBox(height: 4),
                SegmentedButton<int>(
                  segments: const [
                    ButtonSegment(value: 0, label: Text('不动房态')),
                    ButtonSegment(value: 1, label: Text('开房')),
                    ButtonSegment(value: 2, label: Text('关房')),
                  ],
                  selected: {closed == null ? 0 : (closed! ? 2 : 1)},
                  onSelectionChanged: (s) => setSheet(() =>
                      closed = s.first == 0 ? null : s.first == 2),
                ),
                const SizedBox(height: 12),
                SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                        onPressed: () => Navigator.pop(sheetContext, true),
                        child: const Text('应用到所选区间'))),
              ],
            ),
          ),
        ),
      ),
    );
    if (ok != true) return;
    final ids = [
      for (final e in selected.entries)
        if (e.value) e.key
    ];
    if (ids.isEmpty) return _snack('至少选择一个房型');
    final priceCents = ((double.tryParse(price.text) ?? 0) * 100).round();
    try {
      await widget.api.setStayCalendar(
        roomTypeIds: ids,
        fromDate: _fmt(from),
        toDate: _fmt(to),
        priceCents: priceCents > 0 ? priceCents : null,
        totalQty: qty.text.trim().isEmpty ? null : int.tryParse(qty.text),
        closed: closed,
      );
      _snack('已应用');
      _refresh();
    } catch (e) {
      _snack(e is ApiException ? e.message : '$e');
    }
  }
}

/// 房型新建/编辑页。下架不删(历史订单引用);取消政策改动只影响新订单。
class RoomTypeEditPage extends StatefulWidget {
  const RoomTypeEditPage({super.key, required this.api, this.existing});

  final ApiClient api;
  final RoomType? existing;

  @override
  State<RoomTypeEditPage> createState() => _RoomTypeEditPageState();
}

class _RoomTypeEditPageState extends State<RoomTypeEditPage> {
  late final _name = TextEditingController(text: widget.existing?.name ?? '');
  late final _bedType =
      TextEditingController(text: widget.existing?.bedType ?? '');
  late final _area =
      TextEditingController(text: '${widget.existing?.areaM2 ?? ''}');
  late int _maxGuests = widget.existing?.maxGuests ?? 2;
  late String _policy = widget.existing?.cancelPolicy ?? 'limited_free';
  late String _freeUntil = widget.existing?.freeCancelUntil ?? '18:00';
  late List<String> _images = [...(widget.existing?.imageUrls ?? const [])];
  bool _busy = false;

  Future<void> _addImage() async {
    if (!await PermissionRationale.ensure(context, AppPermissionKind.photos,
        reason: '用于选取房型图片并上传。\n拒绝不影响其他功能。')) {
      return;
    }
    final picked = await ImagePicker().pickImage(
        source: ImageSource.gallery, maxWidth: 1600, imageQuality: 85);
    if (picked == null) return;
    try {
      final bytes = await picked.readAsBytes();
      final url =
          await widget.api.uploadImage(bytes, picked.name, purpose: 'room');
      if (mounted) setState(() => _images = [..._images, url]);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('上传失败:$e')));
      }
    }
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请填写房型名称')));
      return;
    }
    setState(() => _busy = true);
    final fields = {
      'name': _name.text.trim(),
      'bed_type': _bedType.text.trim(),
      'area_m2': int.tryParse(_area.text) ?? 0,
      'max_guests': _maxGuests,
      'image_urls': _images,
      'cancel_policy': _policy,
      'free_cancel_until': _freeUntil,
    };
    try {
      if (widget.existing == null) {
        await widget.api.createRoomType(fields);
      } else {
        await widget.api.updateRoomType(widget.existing!.id, fields);
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(e is ApiException ? e.message : '$e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar:
          AppBar(title: Text(widget.existing == null ? '新增房型' : '编辑房型')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        TextField(
            controller: _name,
            decoration: const InputDecoration(
                labelText: '房型名称 *(如 高级大床房)',
                border: OutlineInputBorder())),
        const SizedBox(height: 12),
        TextField(
            controller: _bedType,
            decoration: const InputDecoration(
                labelText: '床型(如 1.8m 大床)', border: OutlineInputBorder())),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(
            child: TextField(
                controller: _area,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: '面积(㎡)', border: OutlineInputBorder())),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: DropdownButtonFormField<int>(
              initialValue: _maxGuests,
              decoration: const InputDecoration(
                  labelText: '可住人数', border: OutlineInputBorder()),
              items: [
                for (var n = 1; n <= 6; n++)
                  DropdownMenuItem(value: n, child: Text('$n 人')),
              ],
              onChanged: (v) => setState(() => _maxGuests = v ?? 2),
            ),
          ),
        ]),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: _policy,
          decoration: const InputDecoration(
              labelText: '取消政策 *',
              helperText: '改动只影响新订单,已有订单按下单时的政策执行',
              border: OutlineInputBorder()),
          items: [
            for (final e in kCancelPolicies.entries)
              DropdownMenuItem(value: e.key, child: Text(e.value)),
          ],
          onChanged: (v) => setState(() => _policy = v ?? 'limited_free'),
        ),
        if (_policy == 'limited_free') ...[
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _freeUntil,
            decoration: const InputDecoration(
                labelText: '入住日免费取消截止时刻',
                border: OutlineInputBorder()),
            items: [
              for (final t in ['12:00', '14:00', '16:00', '18:00', '20:00', '23:59'])
                DropdownMenuItem(value: t, child: Text('入住日 $t 前免费取消')),
            ],
            onChanged: (v) => setState(() => _freeUntil = v ?? '18:00'),
          ),
        ],
        const SizedBox(height: 12),
        Text('房型图片(最多 9 张)',
            style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final url in _images)
            Stack(children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Image(image: szNetImage(widget.api.resolveUrl(url)),
                    width: 96, height: 96, fit: BoxFit.cover),
              ),
              Positioned(
                right: 0,
                top: 0,
                child: GestureDetector(
                  onTap: () =>
                      setState(() => _images = [..._images]..remove(url)),
                  child: const CircleAvatar(
                      radius: 10,
                      backgroundColor: Colors.black54,
                      child: Icon(Icons.close, size: 14, color: Colors.white)),
                ),
              ),
            ]),
          if (_images.length < 9)
            InkWell(
              onTap: _addImage,
              borderRadius: BorderRadius.circular(8),
              child: Container(
                width: 96,
                height: 96,
                decoration: BoxDecoration(
                  border: Border.all(
                      color: Theme.of(context).colorScheme.outline),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(Icons.add_a_photo_outlined),
              ),
            ),
        ]),
        const SizedBox(height: 24),
        FilledButton(
            onPressed: _busy ? null : _save,
            child: Text(_busy ? '保存中…' : '保存')),
      ]),
    );
  }
}
