/// 设计层公共入口:设计令牌(SzColors)、主题(brandTheme)、通用组件。
///
/// 与 superz_shared.dart 的区别:这里**不引任何平台插件**(jpush / 定位 /
/// 地图),所以走查页、web 预览、纯 UI 测试都能安全 import。
/// 三端 App 照旧 import 'package:superz_shared/superz_shared.dart' 即可,
/// 那个入口已经把这些一并导出。
library;

export 'src/brand.dart';
export 'src/brand_art.dart';
export 'src/sz_widgets.dart';
export 'src/ui_bits.dart';
