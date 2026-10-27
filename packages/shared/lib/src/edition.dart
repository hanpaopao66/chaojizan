/// 产品形态(编译期):完整版 / 单门店版。
///
/// ## 为什么有单门店版
///
/// 增值电信业务的两张证(ICP 经营许可证、EDI 在线数据处理与交易处理)还没下来。
/// 应用商店审核给的路是:**先以「一家店自己的点餐 App」上架** —— 不撮合多个商家、
/// 不招骑手、不做聊天视频论坛小程序这类信息服务,也就不落在那两张证的范围里。
///
/// 所以商店包(用户端)这样打:
///
///     flutter build apk --release -PSUPERZ_CHANNEL=store -PSUPERZ_EDITION=single \
///         --dart-define=SUPERZ_CHANNEL=store --dart-define=SUPERZ_EDITION=single
///
/// `-P` 给 Gradle(摘掉相机、麦克风这些单门店版用不到的权限,见
/// apps/user_app/android/app/src/single/AndroidManifest.xml),`--dart-define` 给 Dart(收起入口)。
/// 完整命令在 scripts/release_apks.sh 和 `make store-user`。
///
/// ## 为什么是编译期,不是后台开关
///
/// 后台开关能在过审之后把平台功能拨回来 —— 商店把这个当「审核后变更功能」,下架处理;
/// 审核包里只要还有点得进去的入口也会被驳回。所以单门店版里这些入口**根本不编进去**
/// (const 判断,AOT 会把整支分支剪掉),拿到许可证之后发一个完整版的商店包才放出来。
///
/// 官网直链包、网页版、电脑版、商家端、骑手端都不传这个参数,行为一点不变。
/// 「显示哪家店」不在这里,是后台「平台开关」里的 `single_store_merchant_id`
/// (/config 的 single_store 下发),换店不用重新打包。
library;

/// 形态名:`full`(缺省)或 `single`。
const String kEdition = String.fromEnvironment('SUPERZ_EDITION', defaultValue: 'full');

/// 单门店版(应用商店包)。见本文件开头。
const bool kSingleStore = kEdition == 'single';
