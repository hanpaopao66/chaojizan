import 'dart:io';

import 'package:flutter/services.dart';
import 'package:superz_shared/superz_shared.dart';

/// 把 App 真用的字体装进测试环境(只用仓库里的字体文件,哪台机器上跑都一样)。
///
/// widget 测试默认的字体里,拉丁字母和数字一个字一个 em 宽 —— 比真字体宽出
/// 一大截。量「这一行放不放得下」「这张卡多高」时,那量的是一张不存在的卡。
/// 要按商家真看到的样子量,就先调这个。
///
/// ⚠️ FontLoader 是**整个测试进程**共享的:同一个文件里调过之后,
/// 后面的用例也都换成了真字体。要保留默认字体做「悲观」检查的用例
/// (比如窄屏溢出),别和它放在一个文件里。
///
/// 中文用打包的思源宋体子集顶上系统字的位置:中文一个字一个 em 宽,
/// 宋体黑体量出来的宽度一样,只是长相不同。
Future<void> loadRealFonts() async {
  const shared = '../../packages/shared/assets/fonts';
  const cjk = '$shared/SzSerifCJK-Regular.ttf';
  Future<void> load(String family, List<String> paths) async {
    final loader = FontLoader(family);
    for (final p in paths) {
      final f = File(p);
      if (!f.existsSync()) continue;
      loader.addFont(f
          .readAsBytes()
          .then((b) => ByteData.view(Uint8List.fromList(b).buffer)));
    }
    await loader.load();
  }

  await load(kSansFamily,
      ['$shared/SzSans-Regular.ttf', '$shared/SzSans-Semibold.ttf', cjk]);
  await load(kSerifFamily,
      ['$shared/SzSerif-Regular.ttf', '$shared/SzSerif-Semibold.ttf', cjk]);
  await load(kSerifCjkFamily,
      ['$shared/SzSerifCJK-Regular.ttf', '$shared/SzSerifCJK-Semibold.ttf']);
  for (final sys in ['PingFang SC', 'Noto Sans CJK SC', 'Heiti SC', 'Roboto']) {
    await load(sys, [cjk]);
  }
}
