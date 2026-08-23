/// 门店相册:环境/后厨/食材实拍,展示在用户点单页「商家」标签。
///
/// ## 为什么独立成一页
///
/// 它原来是店铺页里的一张内联卡:**空态就要 196px**,传满九张更高 ——
/// 而相册是**开店时传一次**的东西。一次性的事不该天天占着首屏,
/// 尤其是这一页首屏本来只放得下 5 个入口。
///
/// 现在它是「门店资料」那行网格里的一格(合下来 16px),点开是这一页。
library;

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

class ShopAlbumPage extends StatefulWidget {
  const ShopAlbumPage({super.key, required this.api, required this.shop});

  final ApiClient api;

  /// 进来时的店铺快照。照片增删后以本页自己拉到的为准。
  final Merchant shop;

  @override
  State<ShopAlbumPage> createState() => _ShopAlbumPageState();
}

class _ShopAlbumPageState extends State<ShopAlbumPage> {
  late List<String> _photos = List.of(widget.shop.photoUrls);
  bool _uploading = false;

  /// 最多九张。和用户端商家页的展示位一致,再多也放不下
  static const _max = 9;

  Future<void> _reload() async {
    try {
      final shop = await widget.api.myShop();
      if (!mounted || shop == null) return;
      setState(() => _photos = List.of(shop.photoUrls));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _add() async {
    if (_photos.length >= _max) return;
    if (!await PermissionRationale.ensure(context, AppPermissionKind.photos)) {
      return;
    }
    final picked = await ImagePicker()
        .pickImage(source: ImageSource.gallery, maxWidth: 1280, imageQuality: 85);
    if (picked == null) return;
    setState(() => _uploading = true);
    try {
      final url = await widget.api.uploadImage(
          await picked.readAsBytes(), picked.name,
          purpose: 'gallery');
      await widget.api.updateShop({
        'photo_urls': [..._photos, url]
      });
      await _reload();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  Future<void> _remove(String url) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
        title: const Text('删除这张照片?'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('删除')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await widget.api.updateShop(
          {'photo_urls': _photos.where((u) => u != url).toList()});
      await _reload();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SzPageScaffold(
      appBar: AppBar(title: Text('门店相册(${_photos.length}/$_max)')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
              '店面环境、后厨、食材实拍,展示在用户点单页「商家」标签 —— '
              '真实门店是最好的信任素材。',
              style: TextStyle(
                  fontSize: kFontNote, height: 1.5, color: theme.sz.inkMuted)),
          const SizedBox(height: 12),
          if (_photos.isEmpty)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 28),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerHighest
                    .withValues(alpha: 0.4),
                borderRadius: BorderRadius.circular(kRadiusMd),
              ),
              child: const Center(child: Text('还没有照片,点下面的按钮传第一张')),
            )
          else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final url in _photos)
                  Stack(children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(kRadiusSm),
                      child: Image(
                        image: szNetImage(widget.api.resolveUrl(url)),
                        width: 92,
                        height: 92,
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => Container(
                            width: 92,
                            height: 92,
                            color: theme.colorScheme.surfaceContainerHighest,
                            child: const Icon(Icons.broken_image_outlined)),
                      ),
                    ),
                    Positioned(
                      top: 2,
                      right: 2,
                      child: InkWell(
                        onTap: () => _remove(url),
                        child: Container(
                          padding: const EdgeInsets.all(2),
                          decoration: BoxDecoration(
                            color: Colors.black.withValues(alpha: 0.55),
                            shape: BoxShape.circle,
                          ),
                          child: const Icon(Icons.close,
                              size: 14, color: Colors.white),
                        ),
                      ),
                    ),
                  ]),
              ],
            ),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed:
                _uploading || _photos.length >= _max ? null : _add,
            icon: _uploading
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.add_photo_alternate_outlined),
            label: Text(_uploading
                ? '上传中…'
                : (_photos.length >= _max ? '已满 $_max 张' : '添加照片')),
          ),
        ],
      ),
    );
  }
}
