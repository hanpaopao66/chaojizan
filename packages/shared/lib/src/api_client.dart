import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'models.dart';

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);

  final int statusCode;
  final String message;

  /// 网络层问题(断网/超时/连不上),不是服务端返回的业务错误。
  /// 页面据此决定是"给个重试按钮"还是"照实说明原因"。
  bool get isNetwork => statusCode == 0;

  @override
  String toString() => message;
}

/// 把底层网络异常翻成人话。
///
/// 不翻的后果实测过:首页断网时界面上会出现
/// 「ClientException with SocketException: Connection refused (OS Error...),
/// uri=http://10.0.2.2:8010/merchants?lat=30.66&lng=104.08&sort=distance」——
/// 用户看不懂,而且把内部接口地址、端口、查询参数都暴露在界面上,
/// 截图发出去就是一次信息泄露。所以网络类异常一律不许原样冒到 UI。
ApiException _asFriendly(Object error) {
  if (error is ApiException) return error;
  final raw = error.toString();
  if (error is TimeoutException || raw.contains('TimeoutException')) {
    return ApiException(0, '连接超时,换个网络或稍后再试');
  }
  if (error is SocketException ||
      raw.contains('SocketException') ||
      raw.contains('Connection refused') ||
      raw.contains('Network is unreachable') ||
      raw.contains('Failed host lookup')) {
    return ApiException(0, '网络好像断了,检查一下网络再试');
  }
  if (error is HandshakeException || raw.contains('HandshakeException')) {
    return ApiException(0, '安全连接建立失败,换个网络再试');
  }
  if (error is http.ClientException || raw.contains('ClientException')) {
    return ApiException(0, '网络不太顺,请稍后再试');
  }
  if (error is FormatException || raw.contains('FormatException')) {
    // 服务端返回了非 JSON:多半是被网关/校园网劫持到了门户页
    return ApiException(0, '返回内容异常,可能被网络劫持,换个网络再试');
  }
  return ApiException(0, '出了点问题,请稍后再试');
}

/// 三端共用的 API 客户端。
///
/// baseUrl 说明:
///  - iOS 模拟器 / macOS:http://127.0.0.1:8000
///  - Android 模拟器:http://10.0.2.2:8000(模拟器里 localhost 指向手机自身)
///  - 真机调试:换成电脑的局域网 IP
/// 可用 --dart-define=SUPERZ_API=http://x.x.x.x:8000 覆盖。
class ApiClient {
  ApiClient({String? baseUrl})
      : baseUrl = baseUrl ??
            const String.fromEnvironment('SUPERZ_API',
                defaultValue: 'http://127.0.0.1:8000');

  final String baseUrl;
  String? _token;
  DateTime? _tokenIssuedAt;
  bool _refreshing = false;
  int? userId;
  String? userName;

  /// 当前会话的账号角色(customer/merchant/rider)。账号按 (手机号, 角色) 分立,
  /// 持久化它用于冷启动校验"存的会话是不是本端的角色"——历史上曾出现
  /// 旧代码把用户端账号的 token 存进商家端,重启后恢复出来全程 403
  String? userRole;

  bool get isLoggedIn => _token != null;

  /// WebSocket 地址拼接用(听单通道要带 token)
  String? get token => _token;
  String get wsBaseUrl =>
      baseUrl.replaceFirst('https://', 'wss://').replaceFirst('http://', 'ws://');

  /// 连锁:当前操作的门店 id。
  ///
  /// 单店商家永远是 null —— 不发这个头时后端退回"我唯一的那家店",
  /// 与加连锁之前一字不差。这个头只是**选哪家**不是**有权限**:
  /// 后端在权限解析那一处照样全量校验,填别人家的 id 只会拿到 404。
  int? shopId;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_token != null) 'Authorization': 'Bearer $_token',
        if (shopId != null) 'X-Shop-Id': '$shopId',
      };

  /// 切换当前门店并落盘(冷启动后仍停在上次那家)。
  Future<void> setShopId(int? id) async {
    shopId = id;
    try {
      final sp = await SharedPreferences.getInstance();
      if (id == null) {
        await sp.remove('merchant_shop_id');
      } else {
        await sp.setInt('merchant_shop_id', id);
      }
    } catch (_) {}
  }

  /// token 无感续期:服务端 token 7 天过期,超过 1 天龄就顺手换新。
  /// 商家端接单机长期挂机,靠这里保持不掉线;失败静默(下次请求再试)。
  Future<void> _maybeRefreshToken() async {
    if (_token == null || _refreshing || _tokenIssuedAt == null) return;
    if (DateTime.now().difference(_tokenIssuedAt!) < const Duration(days: 1)) {
      return;
    }
    _refreshing = true;
    try {
      final data = await _request('POST', '/auth/refresh');
      _token = data['token'] as String;
      _tokenIssuedAt = DateTime.now();
      await _persistSession();
    } catch (_) {
      // 静默:网络抖动或 token 已失效都不打断当前操作
    } finally {
      _refreshing = false;
    }
  }

  /// token 真失效(401)时的全局兜底:AuthGate 挂上后静默回到登录页
  static void Function()? onUnauthorized;

  /// 会话被清空(退出登录/换账号)时的钩子。用回调而不是直接调 Analytics:
  /// analytics.dart 已经 import 本文件,反向再 import 就成了环
  static void Function()? onSessionCleared;

  Future<dynamic> _request(String method, String path,
      {Object? body, Map<String, String>? query}) async {
    try {
      return await _rawRequest(method, path, body: body, query: query);
    } catch (e) {
      // 出口只放两种东西:服务端的业务错误(中文)、翻好的网络提示。
      // 底层异常原文一律不许出去(见 _asFriendly 的注释)
      throw _asFriendly(e);
    }
  }

  Future<dynamic> _rawRequest(String method, String path,
      {Object? body, Map<String, String>? query}) async {
    if (path != '/auth/refresh') await _maybeRefreshToken();
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
    final request = http.Request(method, uri)..headers.addAll(_headers);
    if (body != null) request.body = jsonEncode(body);
    final response = await http.Response.fromStream(
        await request.send().timeout(const Duration(seconds: 15)));
    final text = utf8.decode(response.bodyBytes);
    if (response.statusCode >= 400) {
      String message = '请求失败(${response.statusCode})';
      try {
        final detail = (jsonDecode(text) as Map)['detail'];
        if (detail is String) message = detail;
      } catch (_) {}
      if (response.statusCode == 401 && _token != null &&
          !path.startsWith('/auth/')) {
        // 登录态失效:清会话,静默回登录页(不弹一屏报错)
        await clearSession();
        onUnauthorized?.call();
      }
      throw ApiException(response.statusCode, message);
    }
    return text.isEmpty ? null : jsonDecode(text);
  }

  // ---------- 会话持久化(冷启动免登录,在线永不掉线) ----------
  Future<void> _persistSession() async {
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setString('auth_token', _token ?? '');
      await sp.setString(
          'auth_token_at', _tokenIssuedAt?.toIso8601String() ?? '');
      await sp.setInt('auth_user_id', userId ?? 0);
      await sp.setString('auth_user_name', userName ?? '');
      await sp.setString('auth_role', userRole ?? '');
    } catch (_) {}
  }

  /// 冷启动恢复会话:有本地 token 即恢复,并向服务端校验一次。
  /// 网络不通时保留本地会话(离线不登出);仅 401 才判失效。
  ///
  /// [expectRole] 传本端角色(customer/merchant/rider):账号按角色分立,
  /// 存的会话若不是本端角色(如商家端里存着用户端账号的 token),
  /// 恢复出来会全程 403——直接判失效重新登录,App 自愈不用用户猜。
  Future<bool> restoreSession({String? expectRole}) async {
    try {
      final sp = await SharedPreferences.getInstance();
      final token = sp.getString('auth_token');
      if (token == null || token.isEmpty) return false;
      _token = token;
      _tokenIssuedAt =
          DateTime.tryParse(sp.getString('auth_token_at') ?? '') ??
              DateTime.now();
      userId = sp.getInt('auth_user_id');
      userName = sp.getString('auth_user_name');
      userRole = sp.getString('auth_role');
      shopId = sp.getInt('merchant_shop_id');
      // 本地先核一道角色(离线也能拦住错角色会话);
      // 旧版本没存过角色(空)的放行,交给下面 /auth/me 补齐后再核
      if (expectRole != null &&
          userRole != null && userRole!.isNotEmpty && userRole != expectRole) {
        await clearSession();
        return false;
      }
      try {
        final me = await _request('GET', '/auth/me') as Map<String, dynamic>;
        userId = me['id'] as int;
        userName = me['name'] as String;
        userRole = me['role'] as String?;
        if (expectRole != null && userRole != expectRole) {
          await clearSession();
          return false;
        }
        await _persistSession();
      } on ApiException catch (e) {
        if (e.statusCode == 401) {
          await clearSession();
          return false;
        }
        // 其他服务端错误不登出
      } catch (_) {
        // 网络不通:先信本地会话,进得去首页(数据加载各页自行兜底)
      }
      return _token != null;
    } catch (_) {
      return false;
    }
  }

  Future<void> clearSession() async {
    _token = null;
    _tokenIssuedAt = null;
    userId = null;
    userName = null;
    userRole = null;
    // 门店选择跟着会话一起清:不清的话换个商家账号登录,请求还带着
    // 上一个人的 X-Shop-Id,轻则全程 404,重则看着别人的店名发懵
    shopId = null;
    onSessionCleared?.call();  // 会话级状态(如埋点去重)跟着会话走
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.remove('auth_token');
      await sp.remove('auth_token_at');
      await sp.remove('auth_user_id');
      await sp.remove('auth_user_name');
      await sp.remove('auth_role');
      await sp.remove('merchant_shop_id');
    } catch (_) {}
  }

  // ---------- 认证 ----------
  /// 轻量设备指纹(首次生成随机串持久化):登录时上报,服务端风控用
  /// (同设备多账号/商家关联下单识别),不含任何硬件隐私信息。
  Future<String> _deviceId() async {
    try {
      final sp = await SharedPreferences.getInstance();
      var id = sp.getString('device_id');
      if (id == null || id.isEmpty) {
        final rand = Random.secure();
        id = List.generate(32,
            (_) => rand.nextInt(16).toRadixString(16)).join();
        await sp.setString('device_id', id);
      }
      return id;
    } catch (_) {
      return ''; // 拿不到就不上报,不影响登录
    }
  }

  Future<void> login(String phone, String password) async {
    final data = await _request('POST', '/auth/login', body: {
      'phone': phone,
      'password': password,
      'device_id': await _deviceId(),
    });
    _token = data['token'] as String;
    _tokenIssuedAt = DateTime.now();
    userId = data['user_id'] as int;
    userName = data['name'] as String;
    userRole = data['role'] as String?;
  }

  Future<void> register(
      String phone, String password, String name, String role) async {
    final data = await _request('POST', '/auth/register',
        body: {'phone': phone, 'password': password, 'name': name, 'role': role});
    _token = data['token'] as String;
    _tokenIssuedAt = DateTime.now();
    userId = data['user_id'] as int;
    userName = data['name'] as String;
    userRole = data['role'] as String?;
  }

  /// 发验证码。短信服务未配置时返回开发模式验证码(devCode),已配置返回 null
  Future<String?> sendSmsCode(String phone,
      {String ticket = '', int? slide}) async {
    final data = await _request('POST', '/auth/sms-code', body: {
      'phone': phone,
      if (ticket.isNotEmpty) 'ticket': ticket,
      if (slide != null) 'slide': slide,
    });
    return (data as Map)['dev_code'] as String?;
  }

  /// 验证码登录,新手机号自动注册为用户
  Future<void> smsLogin(String phone, String code,
      {String role = 'customer'}) async {
    final data = await _request('POST', '/auth/sms-login', body: {
      'phone': phone,
      'code': code,
      'device_id': await _deviceId(),
      'role': role,
    });
    _token = data['token'] as String;
    _tokenIssuedAt = DateTime.now();
    userId = data['user_id'] as int;
    userName = data['name'] as String;
    userRole = data['role'] as String?;
    await _persistSession();
  }

  /// 滑块验证挑战(发码被 409 captcha_required 拒绝时调用)
  Future<Map<String, dynamic>> sliderChallenge() async {
    return await _request('GET', '/auth/slider') as Map<String, dynamic>;
  }

  // ---------- 团购券 ----------
  /// 在售团购列表(用户端)
  Future<List<VoucherDeal>> voucherDeals() async {
    final data = await _request('GET', '/vouchers');
    return (data as List)
        .map((e) => VoucherDeal.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<VoucherTicket> purchaseVoucher(int voucherId) async {
    final data = await _request('POST', '/vouchers/$voucherId/purchase');
    return VoucherTicket.fromJson(data as Map<String, dynamic>);
  }

  Future<VoucherTicket> payVoucherMock(String purchaseNo) async {
    final data =
        await _request('POST', '/vouchers/purchases/$purchaseNo/pay/mock');
    return VoucherTicket.fromJson(data as Map<String, dynamic>);
  }

  /// 我的券包
  Future<List<VoucherTicket>> myVoucherTickets() async {
    final data = await _request('GET', '/vouchers/purchases/mine');
    return (data as List)
        .map((e) => VoucherTicket.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<VoucherTicket> refundVoucher(String purchaseNo) async {
    final data =
        await _request('POST', '/vouchers/purchases/$purchaseNo/refund');
    return VoucherTicket.fromJson(data as Map<String, dynamic>);
  }

  /// 商家:发券
  Future<VoucherDeal> createVoucher(Map<String, dynamic> fields) async {
    final data = await _request('POST', '/vouchers', body: fields);
    return VoucherDeal.fromJson(data as Map<String, dynamic>);
  }

  /// 商家:我的券列表
  Future<List<VoucherDeal>> myVoucherDeals() async {
    final data = await _request('GET', '/vouchers/mine');
    return (data as List)
        .map((e) => VoucherDeal.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  // ---------- 商家子账号(店员分权)----------
  Future<List<Map<String, dynamic>>> myStaff() async {
    final data = await _request('GET', '/merchants/me/staff');
    return (data as List).cast<Map<String, dynamic>>();
  }

  Future<void> addStaff(String phone, String name) =>
      _request('POST', '/merchants/me/staff',
          body: {'phone': phone, 'name': name});

  Future<void> removeStaff(int userId) =>
      _request('DELETE', '/merchants/me/staff/$userId');

  // ---------- 商家店铺券(成本商家承担)----------
  /// 商家:建店铺券批次
  Future<Map<String, dynamic>> createShopCouponBatch(
      Map<String, dynamic> fields) async {
    final data =
        await _request('POST', '/merchants/me/coupon-batches', body: fields);
    return data as Map<String, dynamic>;
  }

  /// 商家:我的店铺券批次
  Future<List<Map<String, dynamic>>> myShopCouponBatches() async {
    final data = await _request('GET', '/merchants/me/coupon-batches');
    return (data as List).cast<Map<String, dynamic>>();
  }

  /// 商家:启用/停用某批次
  Future<Map<String, dynamic>> toggleShopCouponBatch(int batchId) async {
    final data = await _request(
        'POST', '/merchants/me/coupon-batches/$batchId/toggle');
    return data as Map<String, dynamic>;
  }

  /// 商家:老客召回概览(只有计数,平台不给顾客名单)
  Future<Map<String, dynamic>> merchantWinback() async =>
      await _request('GET', '/merchants/me/winback') as Map<String, dynamic>;

  /// 用户:某店可领的店铺券
  Future<List<Map<String, dynamic>>> claimableShopCoupons(
      int merchantId) async {
    final data = await _request('GET', '/merchants/$merchantId/coupons');
    return (data as List).cast<Map<String, dynamic>>();
  }

  /// 用户:领取某店铺券
  Future<Map<String, dynamic>> claimShopCoupon(
      int merchantId, int batchId) async {
    final data = await _request(
        'POST', '/merchants/$merchantId/coupons/$batchId/claim');
    return data as Map<String, dynamic>;
  }

  Future<VoucherDeal> updateVoucher(int id, Map<String, dynamic> fields) async {
    final data = await _request('PATCH', '/vouchers/$id', body: fields);
    return VoucherDeal.fromJson(data as Map<String, dynamic>);
  }

  /// 商家:输码核销
  Future<VoucherTicket> redeemVoucher(String code) async {
    final data =
        await _request('POST', '/vouchers/redeem', body: {'code': code});
    return VoucherTicket.fromJson(data as Map<String, dynamic>);
  }

  /// 微信 App 支付统一下单;商户号未配置时抛 ApiException(503)
  Future<Map<String, dynamic>> wechatPrepay(String orderNo) async {
    final data = await _request('POST', '/orders/$orderNo/pay/wechat');
    return (data as Map).cast<String, dynamic>();
  }

  // ---------- 个人资料 ----------
  Future<UserProfile> me() async {
    final data = await _request('GET', '/auth/me');
    return UserProfile.fromJson(data as Map<String, dynamic>);
  }

  /// 注销账号(软删除,匿名化)。有在途订单/店铺/未提余额时服务端返回 409。
  Future<void> deleteAccount() => _request('DELETE', '/auth/me');

  // ---------- 实名认证(按需触发,购买酒类等受限品类时要求) ----------
  /// 返回 {verified, is_adult, real_name(打码)};证号明文不出接口
  Future<Map<String, dynamic>> identityStatus() async =>
      await _request('GET', '/auth/identity-status') as Map<String, dynamic>;

  Future<Map<String, dynamic>> verifyIdentity(
          String realName, String idNo) async =>
      await _request('POST', '/auth/verify-identity',
          body: {'real_name': realName, 'id_no': idNo}) as Map<String, dynamic>;

  Future<UserProfile> updateMe(
      {String? name,
      String? avatarUrl,
      String? birthday, // MM-DD,空串清除
      bool? marketingPush}) async {
    final data = await _request('PATCH', '/auth/me', body: {
      if (name != null) 'name': name,
      if (avatarUrl != null) 'avatar_url': avatarUrl,
      if (birthday != null) 'birthday': birthday,
      if (marketingPush != null) 'marketing_push': marketingPush,
    });
    final profile = UserProfile.fromJson(data as Map<String, dynamic>);
    userName = profile.name;
    return profile;
  }

  // ---------- 收藏 ----------
  Future<List<int>> favoriteIds() async {
    final data = await _request('GET', '/favorites/ids');
    return (data as List).cast<int>();
  }

  Future<List<Merchant>> favorites() async {
    final data = await _request('GET', '/favorites');
    return (data as List)
        .map((e) => Merchant.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 收藏/取消收藏。收藏时如果商家开了「收藏有礼」,返回体里带 coupon ——
  /// **调用方要把它告诉用户**:商家掏了钱,券却默默躺进券包的话,
  /// 「收藏即送」想促成的下一单根本不会发生
  Future<Map<String, dynamic>> setFavorite(
      int merchantId, bool favorited) async {
    final data = await _request(
        favorited ? 'POST' : 'DELETE', '/favorites/$merchantId');
    return data is Map ? data.cast<String, dynamic>() : <String, dynamic>{};
  }

  // ---------- 用户端 ----------
  /// sort: distance(综合) / rating(评分优先) / sales(月售优先)
  /// 筛选(与 /merchants/search 同口径):radiusM 距离上限、minRating 评分下限、
  /// hasPromo 只看有优惠的、maxMinOrderCents 起送价上限
  Future<List<Merchant>> merchants(
      {double? lat, double? lng, String sort = 'distance',
      String? category, int? radiusM, double? minRating,
      bool hasPromo = false, int? maxMinOrderCents}) async {
    final data = await _request('GET', '/merchants', query: {
      if (lat != null) 'lat': '$lat',
      if (lng != null) 'lng': '$lng',
      'sort': sort,
      if (category != null && category.isNotEmpty) 'category': category,
      if (radiusM != null) 'radius_m': '$radiusM',
      if (minRating != null) 'min_rating': '$minRating',
      if (hasPromo) 'has_promo': 'true',
      if (maxMinOrderCents != null) 'max_min_order_cents': '$maxMinOrderCents',
    });
    return (data as List)
        .map((e) => Merchant.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 我的常点:近 90 天点得最多的「店+菜」,只列还在售的
  Future<List<FrequentDish>> myFrequentDishes({int limit = 5}) async {
    final data = await _request('GET', '/orders/frequent?limit=$limit')
        as Map<String, dynamic>;
    return ((data['items'] as List?) ?? const [])
        .map((e) => FrequentDish.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 店铺详情(带月售、公告),点单页头部用
  Future<Merchant> merchantDetail(int merchantId) async {
    final data = await _request('GET', '/merchants/$merchantId');
    return Merchant.fromJson(data as Map<String, dynamic>);
  }

  /// 把服务端返回的相对路径(/uploads/x.jpg)拼成完整 URL
  String resolveUrl(String path) =>
      path.startsWith('/') ? '$baseUrl$path' : path;

  /// 搜索营业中的商家(店名或菜名命中)
  Future<List<Merchant>> searchMerchants(
    String q, {
    double? lat,
    double? lng,
    String sort = 'comprehensive',
    int? maxDistanceM,
    double? minRating,
    bool hasPromo = false,
    int? maxMinOrderCents,
  }) async {
    final query = <String, String>{'q': q, 'sort': sort};
    if (lat != null && lng != null) {
      query['lat'] = '$lat';
      query['lng'] = '$lng';
    }
    if (maxDistanceM != null) query['max_distance_m'] = '$maxDistanceM';
    if (minRating != null) query['min_rating'] = '$minRating';
    if (hasPromo) query['has_promo'] = 'true';
    if (maxMinOrderCents != null) {
      query['max_min_order_cents'] = '$maxMinOrderCents';
    }
    final data = await _request('GET', '/merchants/search', query: query);
    return (data as List)
        .map((e) => Merchant.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 搜索联想:返回 {shops:[店名], dishes:[菜名]}
  Future<({List<String> shops, List<String> dishes})> searchSuggest(
      String q) async {
    final data = await _request('GET', '/merchants/suggest', query: {'q': q});
    final m = data as Map<String, dynamic>;
    return (
      shops: (m['shops'] as List? ?? const []).cast<String>(),
      dishes: (m['dishes'] as List? ?? const []).cast<String>(),
    );
  }

  Future<List<Dish>> menu(int merchantId) async {
    final data = await _request('GET', '/merchants/$merchantId/dishes');
    return (data as List)
        .map((e) => Dish.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 我常买:该店近 90 天出现 ≥2 次的在售菜(按常买程度降序)
  Future<List<Dish>> frequentDishes(int merchantId) async {
    final data =
        await _request('GET', '/merchants/$merchantId/frequent-dishes');
    return (data as List)
        .map((e) => Dish.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 取云端购物车该店的一份(返回 items 快照 [{dish_id, choices, quantity}])
  Future<List<Map<String, dynamic>>> getCart(int merchantId) async {
    final data = await _request('GET', '/cart/$merchantId');
    return ((data as Map)['items'] as List? ?? const [])
        .cast<Map<String, dynamic>>();
  }

  /// 整份覆盖保存云端购物车(空 items = 清空该店)
  Future<void> putCart(
      int merchantId, List<Map<String, dynamic>> items) async {
    await _request('PUT', '/cart/$merchantId', body: {'items': items});
  }

  /// 下单。items 每行 {dish_id, quantity, choices:[规格/加料名]};
  /// scheduledAt 为预约送达时间(null = 尽快送)。
  /// 配送费预览。**别在客户端复算** —— 夜间加价、恶劣天气、上门难度
  /// 都在服务端判,客户端自己算一遍就会漏(结算页显示 ¥3、实际收 ¥5,
  /// 用户到付款那一步才发现)。
  ///
  /// 返回 parts(拆分)+ labels(中文名)+ door_fee_cents(送上门要多少,
  /// 让顾客在选之前就能比较)。
  Future<Map<String, dynamic>> previewDeliveryFee({
    required int merchantId,
    required double lat,
    required double lng,
    int? floor,
    bool? hasElevator,
    bool toDoor = true,
  }) async {
    final data = await _request('GET', '/orders/delivery-fee', query: {
      'merchant_id': '$merchantId',
      'lat': '$lat',
      'lng': '$lng',
      if (floor != null) 'floor': '$floor',
      if (hasElevator != null) 'has_elevator': '$hasElevator',
      'to_door': '$toDoor',
    });
    return data as Map<String, dynamic>;
  }

  Future<Order> createOrder({
    required int merchantId,
    required List<Map<String, dynamic>> items,
    Address? address, // 自取单可不传
    bool pickup = false,
    String appendTo = '', // 加菜:原单号(免配送费随原单配送)
    String remark = '',
    DateTime? scheduledAt,
    int tipCents = 0, // 小费,100% 归骑手
    int? couponId, // 平台券抵扣(超时安抚券等,平台承担)
    String groupCode = '', // 拼单码(发起人结算,原子关车)
    /// 送上门 / 送到楼下。**顾客自己选** —— 选楼下就不收上门难度费,
    /// 骑手也没有义务上楼。默认送上门(与此前行为一致)
    bool toDoor = true,
  }) async {
    final data = await _request('POST', '/orders', body: {
      'merchant_id': merchantId,
      'items': items,
      'pickup': pickup,
      'append_to': appendTo,
      'tip_cents': tipCents,
      if (couponId != null) 'coupon_id': couponId,
      if (groupCode.isNotEmpty) 'group_code': groupCode,
      if (address != null) ...{
        'address': address.fullAddress,
        'lat': address.lat,
        'lng': address.lng,
        'contact_name': address.contactName,
        'contact_phone': address.contactPhone,
        // 地址保护:骑手只见粗地址(POI/小区)与中性称呼,门牌送达前不下发
        'to_door': toDoor,
        // 楼层:无电梯高楼层会收上门难度费(全额归骑手),
        // 也会让 ETA 诚实一点 —— 爬 6 楼确实更慢
        if (address.floor != null) 'floor': address.floor,
        if (address.hasElevator != null)
          'has_elevator': address.hasElevator,
        'addr_protect': address.protect,
        if (address.protect) 'address_public': address.address,
        'salutation': address.salutation,
      },
      'remark': remark,
      if (scheduledAt != null)
        'scheduled_at': scheduledAt.toUtc().toIso8601String(),
    });
    return Order.fromJson(data as Map<String, dynamic>);
  }

  /// 商家月度对账单 CSV(原文;调用方存文件/系统分享)
  Future<String> merchantStatementCsv(String month) async {
    try {
      return await _statementCsv(month);
    } catch (e) {
      throw _asFriendly(e);
    }
  }

  Future<String> _statementCsv(String month) async {
    await _maybeRefreshToken();
    final uri = Uri.parse('$baseUrl/merchants/me/statement.csv?month=$month');
    final resp = await http
        .get(uri, headers: _headers)
        .timeout(const Duration(seconds: 20));
    final text = utf8.decode(resp.bodyBytes);
    if (resp.statusCode >= 400) {
      String message = '导出失败(${resp.statusCode})';
      try {
        final detail = (jsonDecode(text) as Map)['detail'];
        if (detail is String) message = detail;
      } catch (_) {}
      throw ApiException(resp.statusCode, message);
    }
    return text;
  }

  /// 商家经营分析(近 7/30 天,只读统计)
  Future<Map<String, dynamic>> merchantAnalytics({int days = 7}) async =>
      await _request('GET', '/merchants/me/analytics?days=$days')
          as Map<String, dynamic>;

  /// 我的实测出餐时长(#150)。P50/P80/P95 + 与自己承诺值的差距。
  ///
  /// 这个数**不用于**给商家排名、扣分或影响曝光 —— 服务端的
  /// `never_used_for` 字段把这条红线一并返回,界面上要原样显示出来。
  Future<Map<String, dynamic>> merchantPrepTime() async =>
      await _request('GET', '/merchants/me/prep-time') as Map<String, dynamic>;

  /// 经营趋势与流失诊断(#151/#152)。按自然周聚合,含环比与可归因流失。
  Future<Map<String, dynamic>> merchantTrend({int weeks = 8}) async =>
      await _request('GET', '/merchants/me/trend?weeks=$weeks')
          as Map<String, dynamic>;

  /// 我的明厨亮灶状态(#155)
  Future<Map<String, dynamic>> merchantKitchenCam() async =>
      await _request('GET', '/merchants/me/kitchen-cam')
          as Map<String, dynamic>;

  /// 接入/更新明厨亮灶。notified 必须为 true —— 后厨里站着的也是劳动者,
  /// 服务端会拒绝未确认"已告知员工"的提交(#157)
  Future<Map<String, dynamic>> setMerchantKitchenCam({
    required String url,
    required bool notified,
    String vendor = '',
    String shotUrl = '',
  }) async =>
      await _request('PUT', '/merchants/me/kitchen-cam', body: {
        'url': url,
        'notified': notified,
        'vendor': vendor,
        'shot_url': shotUrl,
      }) as Map<String, dynamic>;

  /// 撤下明厨亮灶(法规对商家是「倡导」,随时可撤)
  Future<Map<String, dynamic>> removeMerchantKitchenCam() async =>
      await _request('DELETE', '/merchants/me/kitchen-cam')
          as Map<String, dynamic>;

  /// 顾客看的明厨亮灶。只有 active 才给播放地址 ——
  /// 不可用时 url 为空、message 说明原因
  Future<Map<String, dynamic>> kitchenCamOf(int merchantId) async =>
      await _request('GET', '/merchants/$merchantId/kitchen-cam')
          as Map<String, dynamic>;

  /// 某家店的明厨亮灶(公开,无需登录 —— 法规要的是"接受社会监督")。
  ///
  /// **只有在线可看时才给播放地址。** 待核验、掉线一律按「无明厨亮灶」
  /// 对外,并如实说明为什么现在看不了 —— 转圈转到天荒地老比直说更糟。
  Future<Map<String, dynamic>> kitchenCam(int merchantId) async =>
      await _request('GET', '/merchants/$merchantId/kitchen-cam')
          as Map<String, dynamic>;

  /// 可选城市(地址搜索的城市切换器用)。清单来自**实际有商家的城市**
  /// 或管理员配置的开城清单 —— 列一个没有商家的城市,
  /// 用户切过去只会看到空列表。
  ///
  /// 公开接口:选城市这一步在登录前就可能发生。
  Future<List<({String name, int merchants})>> openCities() async {
    final d = await _request('GET', '/geo/cities') as Map<String, dynamic>;
    return (d['items'] as List)
        .map((e) => (
              name: (e as Map<String, dynamic>)['name'] as String,
              merchants: e['merchants'] as int? ?? 0,
            ))
        .toList();
  }

  /// 商家推广物料:店铺短码 + 海报要印的内容(短码首次调用时懒生成)
  Future<Map<String, dynamic>> merchantPromo() async =>
      await _request('GET', '/merchants/me/promo') as Map<String, dynamic>;

  /// 高峰备货建议(近 14 天同餐段 P80;meal 缺省按当前时刻)
  Future<Map<String, dynamic>> merchantStocking({String meal = ''}) async =>
      await _request('GET',
              '/merchants/me/stocking${meal.isEmpty ? '' : '?meal=$meal'}')
          as Map<String, dynamic>;

  /// 批量补库存(一键采纳备货建议;补货自动解除估清)
  Future<void> batchStock(List<Map<String, int>> items) async =>
      await _request('POST', '/merchants/me/dishes/batch-stock',
          body: {'items': items});

  /// 追评(首评后 7 天内一次;匿名评价的追评继承匿名)
  Future<Review> appendReview(int reviewId,
          {String content = '', List<String> images = const []}) async =>
      Review.fromJson(await _request('POST', '/reviews/$reviewId/append',
          body: {'content': content, 'images': images})
          as Map<String, dynamic>);

  /// 商家回复追评
  Future<Review> replyAppendReview(int reviewId, String reply) async =>
      Review.fromJson(await _request(
              'POST', '/merchants/me/reviews/$reviewId/append-reply',
              body: {'reply': reply}) as Map<String, dynamic>);

  /// 公开平台配置:营销开关关闭时客户端隐藏相关入口
  Future<Map<String, dynamic>> platformConfig() async =>
      await _request('GET', '/config') as Map<String, dynamic>;

  // ---------- 邀请有礼 ----------
  Future<Map<String, dynamic>> myReferral() async =>
      await _request('GET', '/referrals/me') as Map<String, dynamic>;

  Future<Map<String, dynamic>> claimReferral(String code) async =>
      await _request('POST', '/referrals/claim', body: {'code': code})
          as Map<String, dynamic>;

  // ---------- 拼单(共享购物车) ----------
  Future<Map<String, dynamic>> openGroupCart(int merchantId) async =>
      await _request('POST', '/group-carts',
          body: {'merchant_id': merchantId}) as Map<String, dynamic>;

  Future<Map<String, dynamic>> joinGroupCart(String code) async =>
      await _request('POST', '/group-carts/$code/join')
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> getGroupCart(String code) async =>
      await _request('GET', '/group-carts/$code') as Map<String, dynamic>;

  Future<Map<String, dynamic>> setGroupCartItem(
          String code, int dishId, int quantity) async =>
      await _request('POST', '/group-carts/$code/items',
              body: {'dish_id': dishId, 'quantity': quantity})
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> lockGroupCart(String code,
          {bool locked = true}) async =>
      await _request('POST', '/group-carts/$code/lock',
          body: {'locked': locked}) as Map<String, dynamic>;

  /// 地址保护单:临时放行完整门牌(骑手到楼下后)
  Future<Order> revealAddress(String orderNo) async =>
      Order.fromJson(await _request('POST', '/orders/$orderNo/reveal-address')
          as Map<String, dynamic>);

  /// 骑手反馈「地址不准」(每单一条,只沉淀不追责)
  Future<void> addressFeedback(String orderNo, String note) async =>
      await _request('POST', '/orders/$orderNo/address-feedback',
          body: {'note': note});

  // ---------- 订单内聊天 ----------
  Future<Map<String, dynamic>> orderMessages(String orderNo,
          {String peer = ''}) async =>
      await _request('GET',
              '/orders/$orderNo/messages${peer.isEmpty ? '' : '?peer=$peer'}')
          as Map<String, dynamic>;

  Future<void> sendOrderMessage(String orderNo, String content,
          {String to = '', String kind = 'text'}) async =>
      await _request('POST', '/orders/$orderNo/messages', body: {
        if (to.isNotEmpty) 'to': to,
        'kind': kind,
        'content': content,
      });

  Future<int> orderUnread(String orderNo) async =>
      ((await _request('GET', '/orders/$orderNo/unread')
              as Map<String, dynamic>)['unread'] as num)
          .toInt();

  /// 我的券包(可用在前):超时安抚券等平台券
  Future<List<dynamic>> myCoupons() async =>
      await _request('GET', '/orders/coupons/mine') as List<dynamic>;

  /// 骑手规则中心数据:当日转单计数与软约束阈值
  Future<Map<String, dynamic>> riderDiscipline() async =>
      await _request('GET', '/riders/discipline') as Map<String, dynamic>;

  /// 自取单核销:商家核对顾客报的取餐码,订单完成并结算
  Future<Order> pickupVerify(String orderNo, String code) async {
    final data = await _request('POST', '/orders/$orderNo/pickup-verify',
        body: {'code': code});
    return Order.fromJson(data as Map<String, dynamic>);
  }

  // ---------- 售后 ----------
  /// 申请售后。举证照片必传(服务端强制):有图才能判责
  Future<AfterSale> submitAfterSale(String orderNo, String reason,
      {List<String> images = const []}) async {
    final data = await _request('POST', '/orders/$orderNo/after-sale',
        body: {'reason': reason, 'images': images});
    return AfterSale.fromJson(data as Map<String, dynamic>);
  }

  /// 该订单的售后申请;没有返回 null
  Future<AfterSale?> orderAfterSale(String orderNo) async {
    try {
      final data = await _request('GET', '/orders/$orderNo/after-sale');
      return AfterSale.fromJson(data as Map<String, dynamic>);
    } on ApiException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }

  /// 商家:本店售后申请列表
  Future<List<AfterSale>> myAfterSales({String? status}) async {
    final data = await _request('GET', '/merchants/me/after-sales',
        query: {if (status != null) 'status': status});
    return (data as List)
        .map((e) => AfterSale.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 商家:处理售后(同意=全额退款 / 拒绝),必须带回复
  Future<AfterSale> processAfterSale(
      int id, {required bool accept, required String reply}) async {
    final data = await _request(
        'POST', '/after-sales/$id/${accept ? "accept" : "reject"}',
        body: {'reply': reply});
    return AfterSale.fromJson(data as Map<String, dynamic>);
  }

  // ---------- 评价 ----------
  Future<Review> submitReview(
    String orderNo, {
    required int merchantRating,
    int? riderRating,
    String comment = '',
    bool isAnonymous = false,
    List<String> imageUrls = const [],
    List<String> tags = const [],
    List<String> riderTags = const [], // 配送标签(只挂骑手评分)
  }) async {
    final data = await _request('POST', '/orders/$orderNo/review', body: {
      'merchant_rating': merchantRating,
      if (riderRating != null) 'rider_rating': riderRating,
      'comment': comment,
      'image_urls': imageUrls,
      'tags': tags,
      'rider_tags': riderTags,
    });
    return Review.fromJson(data as Map<String, dynamic>);
  }

  /// 商家:近 N 天负向标签聚合({merchant_neg, delivery_neg, reviews, days})
  Future<Map<String, dynamic>> myReviewTagStats({int days = 30}) async {
    final data = await _request(
        'GET', '/merchants/me/reviews/tag-stats', query: {'days': '$days'});
    return (data as Map).cast<String, dynamic>();
  }

  /// 热搜词(近 30 天热销菜名)
  Future<List<String>> hotKeywords() async {
    final data = await _request('GET', '/merchants/hot-keywords');
    return ((data as Map)['keywords'] as List).cast<String>();
  }

  /// 该订单的评价;还没评过返回 null
  Future<Review?> orderReview(String orderNo) async {
    try {
      final data = await _request('GET', '/orders/$orderNo/review');
      return Review.fromJson(data as Map<String, dynamic>);
    } on ApiException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }

  Future<List<Review>> merchantReviews(int merchantId) async {
    final data = await _request('GET', '/merchants/$merchantId/reviews');
    return (data as List)
        .map((e) => Review.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 商家看自己店的评价。[maxRating] 只看 ≤N 星;[unreplied] 只看未回复;
  /// [before] 游标分页(上一页最后一条的 id)
  Future<List<Review>> myReviews(
      {int? maxRating, bool unreplied = false, int? before}) async {
    final query = <String, String>{
      if (maxRating != null) 'max_rating': '$maxRating',
      if (unreplied) 'unreplied': 'true',
      if (before != null) 'before': '$before',
    };
    final data = await _request('GET', '/merchants/me/reviews',
        query: query.isEmpty ? null : query);
    return (data as List)
        .map((e) => Review.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 商家回复评价(可修改)
  Future<Review> replyReview(int reviewId, String reply) async {
    final data = await _request(
        'POST', '/merchants/me/reviews/$reviewId/reply',
        body: {'reply': reply});
    return Review.fromJson(data as Map<String, dynamic>);
  }

  /// 配送中骑手实时位置;还没骑手或无位置返回 null
  Future<RiderLocation?> riderLocation(String orderNo) async {
    try {
      final data = await _request('GET', '/orders/$orderNo/rider-location');
      return RiderLocation.fromJson(data as Map<String, dynamic>);
    } on ApiException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }

  // ---------- 收货地址 ----------
  Future<List<Address>> addresses() async {
    final data = await _request('GET', '/addresses');
    return (data as List)
        .map((e) => Address.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Address> addAddress({
    required String contactName,
    required String contactPhone,
    required String address,
    required double lat,
    required double lng,
    String detail = '',
    bool isDefault = false,
    bool protect = false,
    String salutation = '',
    String tag = '',
    /// 楼层与电梯(选填)。填了两件事会变准:ETA 更诚实(爬 6 楼确实更慢)、
    /// 无电梯高楼层可以选「送上门」并付一笔归骑手的上门难度费
    int? floor,
    bool? hasElevator,
  }) async {
    final data = await _request('POST', '/addresses', body: {
      'contact_name': contactName,
      'contact_phone': contactPhone,
      'address': address,
      'detail': detail,
      'lat': lat,
      'lng': lng,
      'is_default': isDefault,
      'protect': protect,
      'salutation': salutation,
      'tag': tag,
      if (floor != null) 'floor': floor,
      if (hasElevator != null) 'has_elevator': hasElevator,
    });
    return Address.fromJson(data as Map<String, dynamic>);
  }

  Future<Address> updateAddress(int id, Map<String, dynamic> fields) async {
    final data = await _request('PATCH', '/addresses/$id', body: fields);
    return Address.fromJson(data as Map<String, dynamic>);
  }

  Future<void> deleteAddress(int id) => _request('DELETE', '/addresses/$id');

  /// 智能识别:一段粘贴文本 → {name, phone, address, detail, salutation}。
  ///
  /// 用户的地址往往已经存在于别处(微信里同事发的、上一个平台复制的)。
  /// 让他对着现成的文字重新手打一遍是在制造错误 —— 打错一个数字,
  /// 骑手就打不通电话。
  ///
  /// **返回的是建议值,必须填进表单让用户过目** —— 服务端用本地正则
  /// (不把姓名手机号外发给第三方),解析不了刁钻写法是常态。
  Future<Map<String, dynamic>> parseAddress(String text) async =>
      await _request('POST', '/addresses/parse', body: {'text': text})
          as Map<String, dynamic>;

  /// POI 输入提示(服务端代理腾讯位置服务,Key 不下发 ——
  /// key 一旦进了 APK 就等于公开,配额按 key 计费,被盗刷是迟早的事)
  /// POI 输入提示。
  ///
  /// ⚠️ [city] **必须传对**:服务端用腾讯的 `region_fix=1` 把结果限死在
  /// 指定城市 —— 城市选错,用户搜自己家会**一条都搜不到**
  /// (实测:西安的「紫薇臻品」在 city=成都 时返回 0 条)。
  /// 所以这个参数没有安全的默认值,调用方要从城市切换器/定位拿。
  Future<List<PoiTip>> geoTips(String keywords, {required String city}) async {
    final data = await _request('GET', '/geo/tips',
        query: {'keywords': keywords, 'city': city});
    return (data as List)
        .map((e) => PoiTip.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 坐标 → 地址(地图选点用)。
  ///
  /// 回来的 lat/lng 是**你传进去的那个坐标**,不是匹配到的 POI 坐标 ——
  /// 用户拖到自家单元门口,不该被吸附到几十米外的小区大门。
  Future<PoiTip> geoReverse(double lat, double lng) async {
    final data = await _request('GET', '/geo/reverse',
        query: {'lat': '$lat', 'lng': '$lng'});
    return PoiTip.fromJson(data as Map<String, dynamic>);
  }
  /// 图钉周边的可选地点(地图选点页下方的列表)。
  ///
  /// 光给一个图钉 + 反查出来的一行地址,用户很难确认"这就是我家" ——
  /// 反查给的往往是路名,而他要的是「XX 小区 10 号楼」。
  /// 列一串周边地点带距离,**认地名比认坐标容易得多**。
  Future<List<NearbyPlace>> geoAround(double lat, double lng) async {
    final data = await _request('GET', '/geo/around?lat=$lat&lng=$lng');
    return ((data as Map<String, dynamic>)['items'] as List)
        .map((e) => NearbyPlace.fromJson(e as Map<String, dynamic>))
        .toList();
  }


  /// 顾客对我的评价(#148)。
  ///
  /// 返回里**没有排名、没有同行对比** —— 那是段位体系的入口。
  /// 判断标准:这个数字会不会影响他能看到的单?会就是绳索,不会才是反馈。
  Future<Map<String, dynamic>> riderReviews({int limit = 30}) async {
    final data = await _request('GET', '/riders/me/reviews',
        query: {'limit': '$limit'});
    return data as Map<String, dynamic>;
  }

  /// 连续在线时长与疲劳提醒(#144)。**只提醒不断单。**
  Future<Map<String, dynamic>> riderFatigue() async {
    final data = await _request('GET', '/riders/me/fatigue');
    return data as Map<String, dynamic>;
  }

  /// 派单算法公开说明(/transparency/dispatch,无需鉴权)。
  ///
  /// 服务端从排序代码的常量直接读,不另抄一份 —— 所以这里拿到的
  /// 就是抢单池真正在用的那几个数。
  Future<Map<String, dynamic>> dispatchSpec() async {
    final data = await _request('GET', '/transparency/dispatch');
    return data as Map<String, dynamic>;
  }

  Future<Order> mockPay(String orderNo) async {
    final data = await _request('POST', '/orders/$orderNo/pay/mock');
    return Order.fromJson(data as Map<String, dynamic>);
  }

  // ---------- 云打印小票(商家) ----------
  /// {enabled: 平台是否开通云打印, sn: 已绑定的打印机, auto: 自动出票}
  Future<Map<String, dynamic>> printerStatus() async =>
      await _request('GET', '/merchants/me/printer') as Map<String, dynamic>;

  Future<Map<String, dynamic>> bindPrinter(String sn, String key,
          {String remark = ''}) async =>
      await _request('POST', '/merchants/me/printer',
          body: {'sn': sn, 'key': key, 'remark': remark}) as Map<String, dynamic>;

  Future<void> unbindPrinter() => _request('DELETE', '/merchants/me/printer');

  Future<void> setPrinterAuto(bool auto) =>
      _request('PATCH', '/merchants/me/printer', body: {'auto': auto});

  Future<void> printerTest() => _request('POST', '/merchants/me/printer/test');

  // 补打在下面「多台打印机」那一节,支持只补某一台。
  // 这里原本还有一个单参数的 reprintOrder —— 多打印机那批加新方法时
  // 没删旧的,两个同名方法并存。**release 构建直接编译失败**,
  // 而 flutter analyze 在 app 目录里跑不到 packages/shared,所以一直没露头

  // ---------- 通用订单 ----------
  /// 我的订单(游标分页)。[before] 传上一页最后一单的 createdAt。
  /// 不传就是第一页;服务端 limit 上限 50。
  /// [q] 商家搜单:订单号片段/取餐码/顾客手机尾号(≥3 字符)
  Future<List<Order>> myOrders(
      {String? before, int limit = 20, String? q}) async {
    final data = await _request('GET', '/orders', query: {
      'limit': '$limit',
      if (before != null && before.isNotEmpty) 'before': before,
      if (q != null && q.isNotEmpty) 'q': q,
    });
    return (data as List)
        .map((e) => Order.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Order> getOrder(String orderNo) async {
    final data = await _request('GET', '/orders/$orderNo');
    return Order.fromJson(data as Map<String, dynamic>);
  }

  /// 订单状态时间轴(几点几分接单/取餐/送达)
  Future<List<OrderEvent>> orderEvents(String orderNo) async {
    final data = await _request('GET', '/orders/$orderNo/events');
    return (data as List)
        .map((e) => OrderEvent.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// [verifyCode]/[force] 仅骑手取餐(READY→PICKED_UP)用:
  /// 输小票单号尾号后 4 位核验防拿错单,连续输错可强制取餐(服务端留痕)
  Future<Order> transition(String orderNo, OrderStatus to,
      {String reason = '',
      String verifyCode = '',
      bool force = false,
      String photoUrl = ''}) async {
    final data = await _request('POST', '/orders/$orderNo/transition', body: {
      'to_status': to.value,
      'reason': reason,
      'verify_code': verifyCode,
      'force': force,
      if (photoUrl.isNotEmpty) 'photo_url': photoUrl,
    });
    return Order.fromJson(data as Map<String, dynamic>);
  }

  // ---------- 证照有效期与续证 ----------

  /// 我最近一次续证提交的进度(没提交过 renewal 为 null)。
  Future<Map<String, dynamic>> myLicenseRenewal() async {
    final data = await _request('GET', '/merchants/me/license-renewal');
    return data as Map<String, dynamic>;
  }

  /// 提交续证材料。
  ///
  /// 过审后资质字段一律锁死(能随手把到期日改成 2099 的话,整个到期闸门
  /// 就是摆设),换新证只能走这条复审通道 —— **核验期间照常营业**。
  Future<void> submitLicenseRenewal({
    required String licenseNo,
    required String licenseImageUrl,
    required String expiresAt,
    String businessLicenseNo = '',
    String licenseSubject = '',
  }) async {
    await _request('POST', '/merchants/me/license-renewal', body: {
      'license_no': licenseNo,
      'license_image_url': licenseImageUrl,
      'license_expires_at': expiresAt,
      'business_license_no': businessLicenseNo,
      'license_subject': licenseSubject,
    });
  }

  // ---------- 多台云打印机 ----------

  /// 本店绑定的打印机(前厅 / 后厨 / 标签)。
  Future<Map<String, dynamic>> printers() async {
    final data = await _request('GET', '/merchants/me/printers');
    return data as Map<String, dynamic>;
  }

  /// 绑一台。purpose: front 前厅小票 / kitchen 后厨备餐单 / label 标签。
  ///
  /// **后厨那张不印顾客手机号和地址** —— 后厨用不到,而备餐单会被
  /// 随手丢在操作台上。用途不只是个标签,它决定小票印什么。
  Future<Map<String, dynamic>> addPrinter({
    required String sn,
    required String key,
    String purpose = 'front',
    String name = '',
  }) async {
    final data = await _request('POST', '/merchants/me/printers', body: {
      'sn': sn, 'key': key, 'purpose': purpose, 'name': name,
    });
    return data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updatePrinter(
      int id, Map<String, dynamic> fields) async {
    final data = await _request('PATCH', '/merchants/me/printers/$id',
        body: fields);
    return data as Map<String, dynamic>;
  }

  Future<void> removePrinter(int id) async {
    await _request('DELETE', '/merchants/me/printers/$id');
  }

  /// 补打。[printerId] 只补某一台(后厨的单丢了就只补后厨那张);
  /// 不传则所有自动出票的机器各补一张。
  Future<Map<String, dynamic>> reprintOrder(String orderNo,
      {int? printerId}) async {
    final data = await _request(
        'POST', '/merchants/me/orders/$orderNo/print',
        query: printerId == null ? null : {'printer_id': '$printerId'});
    return (data as Map<String, dynamic>?) ?? {};
  }

  // ---------- 骑手:到店标记与申诉 ----------

  /// 骑手点「我到店了」。
  ///
  /// 等餐时长 = 取餐时刻 − 到店时刻,是**申诉超时时的证据** ——
  /// 在店里干等二十分钟不该算到骑手头上,而现在他没有办法证明这件事。
  /// **只记录不判罚**:不会因此扣商家分(平台不做违规积分)。
  Future<Order> markArrivedShop(String orderNo,
      {double? lat, double? lng}) async {
    final data = await _request(
        'POST', '/riders/orders/$orderNo/arrived',
        body: lat == null ? {} : {'lat': lat, 'lng': lng});
    return Order.fromJson(data as Map<String, dynamic>);
  }

  /// 提交申诉。**证据由系统自动附上**(等餐时长、实际距离、天气豁免) ——
  /// 让一个在马路上跑车的人去截图收集材料,这个通道就等于不存在。
  ///
  /// 成立只把这一单标注为「非骑手责任」,**不加分也不补钱** ——
  /// 平台没有骑手评分体系,所以没有分可加。
  Future<Map<String, dynamic>> submitRiderAppeal({
    required String orderNo,
    required String kind,
    required String reason,
    String photoUrl = '',
  }) async {
    final data = await _request('POST', '/riders/appeals', body: {
      'order_no': orderNo, 'kind': kind, 'reason': reason,
      'photo_url': photoUrl,
    });
    return data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> myRiderAppeals() async {
    final data = await _request('GET', '/riders/appeals');
    return data as Map<String, dynamic>;
  }

  // ---------- 进货查验台账(食品溯源) ----------

  /// 进货台账。[q] 按食材名反查 —— 出食安问题时问的就是
  /// "这批肉是谁供的、什么时候进的",答不上来只能自己扛。
  /// **带 q 时不受默认时间窗限制**:要追的往往就是久一点的那批。
  Future<Map<String, dynamic>> purchases({String? q, int days = 90}) async {
    final data = await _request('GET', '/merchants/me/purchases',
        query: q != null && q.isNotEmpty
            ? {'q': q}
            : {'days': '$days'});
    return data as Map<String, dynamic>;
  }

  /// 用过的供货商(去重,最近在前)。同一家录第三次还要重填,这台账就没人填了。
  Future<List<Map<String, dynamic>>> purchaseSuppliers() async {
    final data = await _request('GET', '/merchants/me/purchases/suppliers');
    return (data as List).cast<Map<String, dynamic>>();
  }

  /// 录一条进货记录。返回体里的 missing 是**还缺哪几项法定必记项** ——
  /// 不拦,只是说清楚(这本台账最大的敌人是根本没人填,不是填得不全)。
  Future<Map<String, dynamic>> addPurchase(Map<String, dynamic> fields) async {
    final data = await _request('POST', '/merchants/me/purchases',
        body: fields);
    return data as Map<String, dynamic>;
  }

  Future<void> deletePurchase(int id) async {
    await _request('DELETE', '/merchants/me/purchases/$id');
  }

  // ---------- 从业人员健康证台账 ----------

  /// 本店健康证台账,快到期的排前面。
  ///
  /// 《食品安全法》四十五条:接触直接入口食品的从业人员一年一检、持证上岗。
  /// **到期只提醒不停业** —— 证是按人的,一个员工过期停整家店不成比例
  /// (这一点和食品经营许可证不同)。
  Future<Map<String, dynamic>> healthCerts(
      {bool includeArchived = false}) async {
    final data = await _request('GET', '/merchants/me/health-certs',
        query: {'include_archived': '$includeArchived'});
    return data as Map<String, dynamic>;
  }

  /// 录一张健康证。**同名同岗视为换新证**,更新原记录而不是堆两条。
  Future<Map<String, dynamic>> saveHealthCert({
    required String name,
    required String expiresAt,
    String role = '',
    String certNo = '',
    String photoUrl = '',
    String? issuedAt,
  }) async {
    final data = await _request('POST', '/merchants/me/health-certs', body: {
      'name': name,
      'role': role,
      'cert_no': certNo,
      'photo_url': photoUrl,
      'expires_at': expiresAt,
      if (issuedAt != null) 'issued_at': issuedAt,
    });
    return data as Map<String, dynamic>;
  }

  /// 员工离职:**归档不删除** —— 监管查的是"当时在岗的人有没有证"。
  Future<void> archiveHealthCert(int id) async {
    await _request('DELETE', '/merchants/me/health-certs/$id');
  }

  // ---------- 连锁店群 ----------
  /// 我的品牌与门店列表。
  ///
  /// 单店商家也能调:brand 为 null、shops 只有一家 —— 门店选择器用同一份
  /// 数据,客户端不用为"是不是连锁"分两套逻辑。
  ///
  /// **冷启动必须先调它再调 myShop()**:连锁账号在没选门店时
  /// /merchants/me 是 404(后端不猜是哪家),顺序反了会把连锁老板
  /// 一路带进"还没开店"的入驻引导。
  Future<Map<String, dynamic>> myBrand() async {
    final data = await _request('GET', '/brands/me');
    return data as Map<String, dynamic>;
  }

  /// 把现有的店升级成品牌总部(第一家店成为品牌首店)。
  Future<Map<String, dynamic>> createBrand({
    required String name,
    required int shopId,
  }) async {
    final data = await _request('POST', '/brands/me',
        body: {'name': name, 'shop_id': shopId});
    return data as Map<String, dynamic>;
  }

  /// 新开一家品牌门店。
  ///
  /// **证照参数不是可选的** —— 食品经营许可证按门店核发,不能复用总部或
  /// 其他门店的。服务端同样硬拦(422),这里做成必填只是别让人白填一遍表。
  Future<Merchant> openBrandShop({
    required int copyFrom,
    required String name,
    required String address,
    required double lat,
    required double lng,
    required String licenseNo,
    required String licenseImageUrl,
  }) async {
    final data = await _request('POST', '/brands/me/shops', body: {
      'copy_from': copyFrom,
      'name': name,
      'address': address,
      'lat': lat,
      'lng': lng,
      'license_no': licenseNo,
      'license_image_url': licenseImageUrl,
    });
    return Merchant.fromJson(data as Map<String, dynamic>);
  }

  Future<Map<String, dynamic>> brandOverview({int days = 7}) async {
    final data = await _request('GET', '/brands/me/overview',
        query: {'days': '$days'});
    return data as Map<String, dynamic>;
  }

  // ---------- 商家端 ----------
  /// 我的店铺;还没申请过返回 null
  Future<Merchant?> myShop() async {
    try {
      final data = await _request('GET', '/merchants/me');
      return Merchant.fromJson(data as Map<String, dynamic>);
    } on ApiException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }

  /// 提交开店申请(进入待审核)
  Future<Merchant> applyShop({
    required String name,
    required String description,
    required String address,
    required double lat,
    required double lng,
    required String licenseNo,
    required String licenseImageUrl,
    String category = 'fast_food',
    String bizType = 'food',
    Map<String, dynamic>? hotel, // 酒店专属资料(biz_type=hotel 必传)
  }) async {
    final data = await _request('POST', '/merchants', body: {
      'name': name,
      'description': description,
      'address': address,
      'lat': lat,
      'lng': lng,
      'license_no': licenseNo,
      'license_image_url': licenseImageUrl,
      'category': category,
      'biz_type': bizType,
      if (hotel != null) 'hotel': hotel,
    });
    return Merchant.fromJson(data as Map<String, dynamic>);
  }

  /// 修改店铺资料;被驳回状态下修改 = 重新提交审核
  Future<Merchant> updateShop(Map<String, dynamic> fields) async {
    final data = await _request('PATCH', '/merchants/me', body: fields);
    return Merchant.fromJson(data as Map<String, dynamic>);
  }

  Future<void> setShopOpen(bool isOpen) => updateShop({'is_open': isOpen});

  /// 缺货部分退款(商家):退某个菜品指定份数
  Future<Order> refundItem(String orderNo, int dishId, int quantity) async {
    final data = await _request('POST', '/orders/$orderNo/refund-item',
        body: {'dish_id': dishId, 'quantity': quantity});
    return Order.fromJson(data as Map<String, dynamic>);
  }

  // ---------- 菜品管理(商家) ----------
  /// 自己店的全部菜品(含已下架)
  Future<List<Dish>> myDishes() async {
    final data = await _request('GET', '/merchants/me/dishes');
    return (data as List)
        .map((e) => Dish.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Dish> addDish({
    required String name,
    required String category,
    required int priceCents,
    int stock = 100,
    int? dailyStock,
    bool isAlcohol = false,
    String imageUrl = '',
    String description = '',
    List<String> badges = const [],
    List<Map<String, dynamic>> options = const [],
    List<Map<String, dynamic>> comboItems = const [],
    String serveWindow = '',
  }) async {
    final data = await _request('POST', '/merchants/me/dishes', body: {
      'name': name,
      'category': category,
      'price_cents': priceCents,
      'stock': stock,
      'daily_stock': dailyStock,
      'is_alcohol': isAlcohol,
      'image_url': imageUrl,
      'description': description,
      'badges': badges,
      'options': options,
      'combo_items': comboItems,
      'serve_window': serveWindow,
    });
    return Dish.fromJson(data as Map<String, dynamic>);
  }

  Future<Dish> updateDish(int dishId, Map<String, dynamic> fields) async {
    final data =
        await _request('PATCH', '/merchants/me/dishes/$dishId', body: fields);
    return Dish.fromJson(data as Map<String, dynamic>);
  }

  /// 临时歇业:歇业 N 小时或到今天打烊,到点自动恢复营业。
  /// 提前恢复直接 updateShop({'is_open': true})(开店动作清歇业标记)
  Future<Merchant> restShop({int? hours, bool untilClose = false}) async {
    final data = await _request('POST', '/merchants/me/rest', body: {
      'hours': hours,
      'until_close': untilClose,
    });
    return Merchant.fromJson(data as Map<String, dynamic>);
  }

  /// 一键估清(今日售罄):库存清零打标,次日 04:00 自动恢复
  Future<Dish> sellOutDish(int dishId) async {
    final data =
        await _request('POST', '/merchants/me/dishes/$dishId/sell-out');
    return Dish.fromJson(data as Map<String, dynamic>);
  }

  /// 撤销估清:恢复估清前库存,当天继续卖
  Future<Dish> cancelSellOut(int dishId) async {
    final data =
        await _request('POST', '/merchants/me/dishes/$dishId/sell-out/cancel');
    return Dish.fromJson(data as Map<String, dynamic>);
  }

  /// 上传图片(菜品图/门头照),返回相对路径,展示时用 resolveUrl 拼全
  /// 上传图片。[purpose] **必填**,决定这张图进公开桶还是私密桶(#124):
  /// 公开 dish/shop/gallery/room/splash/avatar/review;
  /// 私密 id_card/health_cert/license/delivery_proof/incident/after_sale/food_safety。
  /// 服务端不给默认值 —— 猜错的那一次就是一张身份证进了公开桶。
  Future<String> uploadImage(List<int> bytes, String filename,
      {required String purpose,
      Duration timeout = const Duration(seconds: 30)}) async {
    try {
      return await _uploadImage(bytes, filename, purpose, timeout);
    } catch (e) {
      throw _asFriendly(e);
    }
  }

  Future<String> _uploadImage(List<int> bytes, String filename, String purpose,
      Duration timeout) async {
    final request =
        http.MultipartRequest('POST', Uri.parse('$baseUrl/upload'));
    if (_token != null) request.headers['Authorization'] = 'Bearer $_token';
    request.fields['purpose'] = purpose;
    request.files
        .add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    final response =
        await http.Response.fromStream(await request.send().timeout(timeout));
    final text = utf8.decode(response.bodyBytes);
    if (response.statusCode >= 400) {
      String message = '上传失败(${response.statusCode})';
      try {
        final detail = (jsonDecode(text) as Map)['detail'];
        if (detail is String) message = detail;
      } catch (_) {}
      throw ApiException(response.statusCode, message);
    }
    return (jsonDecode(text) as Map)['url'] as String;
  }

  /// 营销效果:满减/店铺券/限时折扣各带来多少单、让利多少
  Future<Map<String, dynamic>> marketingStats({int days = 30}) async {
    final data = await _request('GET', '/merchants/me/marketing-stats',
        query: {'days': '$days'});
    return (data as Map).cast<String, dynamic>();
  }

  /// 评分概览:总分/星级分布/近 30-90 天走势/差评待回复
  Future<Map<String, dynamic>> ratingOverview() async {
    final data = await _request('GET', '/merchants/me/reviews/overview');
    return (data as Map).cast<String, dynamic>();
  }

  /// 回复话术模板(平台预置,商家改完再发)
  Future<Map<String, dynamic>> replyTemplates() async {
    final data = await _request('GET', '/merchants/me/reply-templates');
    return (data as Map).cast<String, dynamic>();
  }

  /// 平台规则(数字从服务端常量算出,后台改不了)
  Future<Map<String, dynamic>> merchantRules() async {
    final data = await _request('GET', '/merchants/me/rules');
    return (data as Map).cast<String, dynamic>();
  }

  /// 顾客分层:新客/回头客/流失客各多少人、各贡献多少
  Future<Map<String, dynamic>> merchantCustomers({int days = 30}) async {
    final data = await _request('GET', '/merchants/me/customers',
        query: {'days': '$days'});
    return (data as Map).cast<String, dynamic>();
  }

  /// 流量漏斗:曝光 → 进店 → 结算 → 下单(按人去重)
  Future<Map<String, dynamic>> merchantFunnel({int days = 7}) async {
    final data = await _request('GET', '/merchants/me/funnel',
        query: {'days': '$days'});
    return (data as Map).cast<String, dynamic>();
  }

  /// 合规档案:平台记在名下的事(食安处置/图片驳回/申诉/质量),不含积分
  Future<Map<String, dynamic>> merchantCompliance() async {
    final data = await _request('GET', '/merchants/me/compliance');
    return (data as Map).cast<String, dynamic>();
  }

  /// 批量写菜单顺序(小的在前);置顶 = 给它一个比现有最小值更小的 sort
  Future<void> reorderDishes(List<Map<String, int>> items) =>
      _request('POST', '/merchants/me/dishes/reorder', body: {'items': items});

  /// 消息中心:{announcements: [...], messages: [{id,kind,title,content,created_at}], unread}
  Future<Map<String, dynamic>> merchantMessages(
      {String? category, int? before}) async {
    final query = <String, String>{
      if (category != null) 'category': category,
      if (before != null) 'before': '$before',
    };
    final data = await _request('GET', '/merchants/me/messages',
        query: query.isEmpty ? null : query);
    return (data as Map).cast<String, dynamic>();
  }

  /// 消息已读水位记到现在
  Future<void> merchantMessagesRead() =>
      _request('POST', '/merchants/me/messages/read');

  /// 忙碌模式:开([minutes] 时长,[extraMinutes] 出餐加时)或关([off])。
  /// 到点自动失效,不需要记得来关
  Future<Merchant> setBusy(
      {int? minutes, int? extraMinutes, bool off = false}) async {
    final data = await _request('POST', '/merchants/me/busy', body: {
      if (off) 'off': true,
      if (!off && minutes != null) 'minutes': minutes,
      if (!off && extraMinutes != null) 'extra_minutes': extraMinutes,
    });
    return Merchant.fromJson(data as Map<String, dynamic>);
  }

  /// 店铺证照公示(公开,亮照经营):{items: [{kind,label,no,image_url}]}
  /// image_url 为空串 = 老库存量商家未传图,只公示证号
  Future<List<Map<String, dynamic>>> merchantLicenses(int merchantId) async {
    final data = await _request('GET', '/merchants/$merchantId/licenses');
    return ((data as Map)['items'] as List).cast<Map<String, dynamic>>();
  }

  /// 今日实时经营(下单口径)+ 昨日全天参照:
  /// {today: {orders, gmv_cents, ongoing, done, cancelled, pickup_orders}, yesterday: {...}}
  Future<Map<String, dynamic>> merchantToday() async {
    final data = await _request('GET', '/merchants/me/today');
    return (data as Map).cast<String, dynamic>();
  }

  /// 待办聚合:{pending_orders, after_sales, bad_reviews_unreplied,
  /// coupon_batches_low, flash_expiring}
  Future<Map<String, dynamic>> merchantTodos() async {
    final data = await _request('GET', '/merchants/me/todos');
    return (data as Map).cast<String, dynamic>();
  }

  /// 证照 OCR 识别:传已上传的证照 URL,返回识别出的字段。
  /// 服务端没接识别模型时 `enabled=false`,调用方**静默跳过**即可 ——
  /// OCR 只是省几下手输,不是流程的一环,不可用时不打扰商家。
  /// 返回示例:{enabled: true, ok: true, license_no: '...', name: '...'}
  Future<Map<String, dynamic>> ocrLicense(String imageUrl) async {
    final data =
        await _request('POST', '/ocr/license', body: {'image_url': imageUrl});
    return (data as Map).cast<String, dynamic>();
  }

  /// 本单退款流水(退款进度时间轴)
  Future<List<RefundRecord>> orderRefunds(String orderNo) async {
    final data = await _request('GET', '/orders/$orderNo/refunds');
    return (data as List)
        .map((e) => RefundRecord.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 公开运营总览(账目透明页/大屏共用,与公开账本同源)
  Future<Map<String, dynamic>> statsOverview() async {
    final data = await _request('GET', '/stats/overview');
    return (data as Map).cast<String, dynamic>();
  }

  // ---------- 公开账本与见证(手机节点) ----------
  Future<List<Map<String, dynamic>>> ledgerAnchors({String after = ''}) async {
    final data = await _request('GET', '/ledger/anchors',
        query: after.isEmpty ? null : {'after': after});
    return (data as List).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> ledgerDay(String day) async {
    final data = await _request('GET', '/ledger/days/$day');
    return (data as Map).cast<String, dynamic>();
  }

  Future<void> nodeHeartbeat(Map<String, dynamic> report) =>
      _request('POST', '/nodes/heartbeat', body: report);

  // ---------- 平台公告与埋点 ----------
  /// 当前生效的平台公告(audience: user/merchant/rider)
  Future<List<PlatformAnnouncement>> announcements(String audience) async {
    final data =
        await _request('GET', '/announcements', query: {'audience': audience});
    return (data as List)
        .map((e) => PlatformAnnouncement.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 批量上报埋点事件(供 Analytics 使用,业务代码不直接调)
  Future<void> trackEvents(List<Map<String, dynamic>> events) =>
      _request('POST', '/events/batch', body: {'events': events});

  /// 对账:按日汇总
  Future<List<DayStat>> financeDaily({int days = 30}) async {
    final data =
        await _request('GET', '/merchants/me/finance/daily', query: {'days': '$days'});
    return (data as List)
        .map((e) => DayStat.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 对账:某日入账明细(day 格式 yyyy-MM-dd)。
  ///
  /// 翻页要**同时传 [before] 和 [beforeId]**(上一页最后一条的
  /// createdAt 与 id)。
  ///
  /// 接口按 (created_at, id) 两列排序,只传 createdAt 会把同一秒的行
  /// 整组跳过 —— 实测演示库一天 1030 行里同秒最多 9 行,漏掉一条 -¥30
  /// 的冲账,**商家看到的明细比实际到手的钱多**。对账页漏行比慢更严重。
  Future<List<FinanceOrder>> financeOrders(String day,
      {String? before, int? beforeId, int limit = 200}) async {
    final data = await _request('GET', '/merchants/me/finance/orders', query: {
      'day': day,
      'limit': '$limit',
      if (before != null && before.isNotEmpty) 'before': before,
      if (beforeId != null) 'before_id': '$beforeId',
    });
    return (data as List)
        .map((e) => FinanceOrder.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  // ---------- 骑手端 ----------
  Future<void> setOnline(bool isOnline) =>
      _request('POST', '/riders/online', body: {'is_online': isOnline});

  Future<void> reportLocation(double lat, double lng) =>
      _request('POST', '/riders/location', body: {'lat': lat, 'lng': lng});

  Future<List<Order>> availableOrders() async {
    final data = await _request('GET', '/riders/available-orders');
    return (data as List)
        .map((e) => Order.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 抢单池 + 「被你自己的偏好挡掉了几单」。
  ///
  /// 服务端对不带 `with_meta` 的老客户端仍返回裸数组,所以这里两个方法
  /// 并存而不是改掉上面那个 —— 装着旧版 App 的骑手不会因为服务端
  /// 升级就打不开抢单页。
  Future<({List<Order> items, int filteredByPrefs})> availablePool() async {
    final data = await _request('GET',
        '/riders/available-orders?with_meta=true') as Map<String, dynamic>;
    return (
      items: ((data['items'] as List?) ?? const [])
          .map((e) => Order.fromJson(e as Map<String, dynamic>))
          .toList(),
      filteredByPrefs: (data['filtered_by_prefs'] as num?)?.toInt() ?? 0,
    );
  }

  /// 同一家店的在手单,一次全标到店 / 全标取餐。
  /// 逐单执行不整体回滚,返回体里 items 逐条给结果。
  Future<Map<String, dynamic>> batchArrived(int merchantId,
      {double? lat, double? lng}) async {
    final body = <String, dynamic>{'merchant_id': merchantId};
    if (lat != null && lng != null) {
      body['lat'] = lat;
      body['lng'] = lng;
    }
    return await _request('POST', '/riders/orders/batch-arrived', body: body)
        as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> batchPicked(int merchantId,
          {Map<String, String>? codes}) async =>
      await _request('POST', '/riders/orders/batch-picked',
          body: {'merchant_id': merchantId, 'codes': codes ?? {}})
          as Map<String, dynamic>;

  /// 骑手消息中心:公告 + 发给我的通知 + 未读数
  Future<Map<String, dynamic>> riderMessages({String? category,
      int? before}) async {
    final q = <String>[
      if (category != null) 'category=$category',
      if (before != null) 'before=$before',
    ];
    return await _request('GET',
        '/riders/me/messages${q.isEmpty ? '' : '?${q.join('&')}'}')
        as Map<String, dynamic>;
  }

  Future<void> markRiderMessagesRead() =>
      _request('POST', '/riders/me/messages/read');

  /// 骑手点「我到收货点了」。到这里到点送达之间的时长花在找门、
  /// 等门禁、等电梯、爬楼上 —— 是"场景难度"唯一可测量的部分。
  /// 幂等:重复点不刷新时间
  Future<Order> markArrivedDrop(String orderNo,
      {double? lat, double? lng}) async {
    final body = <String, dynamic>{};
    if (lat != null && lng != null) {
      body['lat'] = lat;
      body['lng'] = lng;
    }
    final data = await _request(
        'POST', '/riders/orders/$orderNo/arrived-drop', body: body);
    return Order.fromJson(data as Map<String, dynamic>);
  }

  /// 跑单热力图:过去 N 周这个时段各网格的**实际完成单量**。
  /// 是历史不是预测 —— 样本不足的格子带 enough=false,必须显示成
  /// "数据不够"而不是"冷区"
  Future<Map<String, dynamic>> riderHeatmap(
          {int? weekday, int? hour, int weeks = 4}) async {
    final q = <String>[
      if (weekday != null) 'weekday=$weekday',
      if (hour != null) 'hour=$hour',
      'weeks=$weeks',
    ];
    return await _request('GET', '/riders/heatmap?${q.join('&')}')
        as Map<String, dynamic>;
  }

  /// 骑手周报:逐日单量/时长/收入 + 收入构成。只统计不考核
  Future<Map<String, dynamic>> riderWeeklyReport({int weekOffset = 0}) async =>
      await _request('GET',
              '/riders/me/weekly-report?week_offset=$weekOffset')
          as Map<String, dynamic>;

  /// 给平台提意见(不是针对某一单 —— 那个走申诉)
  Future<Map<String, dynamic>> submitRiderFeedback(
          {required String kind, required String content}) async =>
      await _request('POST', '/riders/feedback',
          body: {'kind': kind, 'content': content}) as Map<String, dynamic>;

  Future<Map<String, dynamic>> myRiderFeedback() async =>
      await _request('GET', '/riders/me/feedback') as Map<String, dynamic>;

  Future<Order> grabOrder(String orderNo) async {
    final data = await _request('POST', '/riders/grab/$orderNo');
    return Order.fromJson(data as Map<String, dynamic>);
  }

  /// 转单:已抢未取餐的单退回抢单池。
  /// reason: vehicle_broken / unwell / route_conflict / other
  /// 返回 {today_count, free_times}(每日免责次数,超出仍可转但计入考核参考)
  Future<Map<String, dynamic>> transferOrder(String orderNo, String reason) async {
    final data = await _request('POST', '/riders/transfer/$orderNo',
        body: {'reason': reason});
    return data as Map<String, dynamic>;
  }

  /// 骑手偏好:接单半径(km,null=不限);返回服务端存的当前值
  Future<int?> setGrabRadius(int? km) async {
    final data = await _request('PATCH', '/riders/me/preferences',
        body: {'grab_radius_km': km});
    return (data as Map)['grab_radius_km'] as int?;
  }

  /// 全部接单偏好(半径 / 单价下限 / 只看顺路 / 避开酒类)。
  /// 设置页进来先读一次 —— 直接显示默认值会把他之前设的盖掉。
  Future<Map<String, dynamic>> riderPreferences() async =>
      await _request('GET', '/riders/me/preferences') as Map<String, dynamic>;

  /// 只改传进来的那几项(服务端按 key 是否存在判断,不是按值)
  Future<Map<String, dynamic>> updateRiderPreferences(
          Map<String, dynamic> patch) async =>
      await _request('PATCH', '/riders/me/preferences', body: patch)
          as Map<String, dynamic>;

  /// 我的数据:今日/本周在线时长与单量收入(只统计不考核)
  Future<Map<String, dynamic>> riderWorklog() async =>
      await _request('GET', '/riders/me/worklog') as Map<String, dynamic>;

  // ---------- 骑手上岗:培训考试 + 装备申领 ----------
  Future<Map<String, dynamic>> riderExamStatus() async =>
      await _request('GET', '/riders/exam/status') as Map<String, dynamic>;

  Future<List<dynamic>> riderExamQuestions() async =>
      await _request('GET', '/riders/exam/questions') as List<dynamic>;

  Future<Map<String, dynamic>> riderExamSubmit(
          Map<String, int> answers) async =>
      await _request('POST', '/riders/exam/submit',
          body: {'answers': answers}) as Map<String, dynamic>;

  Future<List<dynamic>> riderGear() async =>
      await _request('GET', '/riders/gear') as List<dynamic>;

  Future<void> requestRiderGear(String item) =>
      _request('POST', '/riders/gear', body: {'item': item});

  /// 事故上报:人先安全,照片可后补;返回在途单处理结果与今日保障状态
  Future<Map<String, dynamic>> reportAccident({
    required String severity,
    String description = '',
    double? lat,
    double? lng,
  }) async =>
      await _request('POST', '/riders/accidents', body: {
        'severity': severity,
        'description': description,
        if (lat != null) 'lat': lat,
        if (lng != null) 'lng': lng,
      }) as Map<String, dynamic>;

  /// 一键紧急求助(SOS):返回撤销窗口秒数与在途单数
  Future<Map<String, dynamic>> riderSos({double? lat, double? lng}) async =>
      await _request('POST', '/riders/sos', body: {
        if (lat != null) 'lat': lat,
        if (lng != null) 'lng': lng,
      }) as Map<String, dynamic>;

  Future<void> cancelSos(int sosId) async =>
      await _request('POST', '/riders/sos/$sosId/cancel');

  Future<List<dynamic>> emergencyContacts() async =>
      await _request('GET', '/riders/me/emergency-contacts') as List<dynamic>;

  Future<void> setEmergencyContacts(
          List<Map<String, String>> contacts) async =>
      await _request('POST', '/riders/me/emergency-contacts',
          body: {'contacts': contacts});

  Future<List<dynamic>> riderInsurance() async =>
      await _request('GET', '/riders/insurance') as List<dynamic>;

  // ---------- 骑手实名认证 ----------
  Future<RiderProfile> riderProfile() async {
    final data = await _request('GET', '/riders/profile');
    return RiderProfile.fromJson(data as Map<String, dynamic>);
  }

  /// 提交实名认证:**只要姓名 + 身份证号**。
  ///
  /// 核验通过当场生效,不用等人工审。健康证选填 ——
  /// 国家层面不要求送餐员持健康证,只有地方另有要求的城市才传。
  Future<RiderProfile> submitRiderProfile({
    required String realName,
    required String idCardNo,
    String healthCertPhotoUrl = '',
  }) async {
    final data = await _request('POST', '/riders/profile', body: {
      'real_name': realName,
      'id_card_no': idCardNo,
      'health_cert_photo_url': healthCertPhotoUrl,
    });
    return RiderProfile.fromJson(data as Map<String, dynamic>);
  }

  /// 食品安全培训内容(#167)。三分钟看完 + 几道确认题。
  ///
  /// 这是法定动作:总局令第 123 号第二十九条要求受托方对配送人员
  /// 进行食安培训并留存记录 —— 不是平台给骑手加的规矩。
  Future<Map<String, dynamic>> riderTraining() async =>
      await _request('GET', '/riders/training') as Map<String, dynamic>;


  // uploadImage 定义在下方(商家/骑手共用)

  // ---------- 骑手钱包 ----------
  Future<Wallet> wallet() async {
    final data = await _request('GET', '/riders/wallet');
    return Wallet.fromJson(data as Map<String, dynamic>);
  }

  Future<List<Earning>> earnings() async {
    final data = await _request('GET', '/riders/earnings');
    return (data as List)
        .map((e) => Earning.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<Withdrawal>> withdrawals() async {
    final data = await _request('GET', '/riders/withdrawals');
    return (data as List)
        .map((e) => Withdrawal.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Withdrawal> requestWithdrawal(int amountCents) async {
    final data = await _request('POST', '/riders/withdrawals',
        body: {'amount_cents': amountCents});
    return Withdrawal.fromJson(data as Map<String, dynamic>);
  }

  // ---------- 商家钱包(语义与骑手钱包一致,T+1 打款) ----------
  Future<Wallet> merchantWallet() async {
    final data = await _request('GET', '/merchants/me/wallet');
    return Wallet.fromJson(data as Map<String, dynamic>);
  }

  Future<List<Withdrawal>> merchantWithdrawals() async {
    final data = await _request('GET', '/merchants/me/withdrawals');
    return (data as List)
        .map((e) => Withdrawal.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 阶梯佣金:当前费率/档位表/上月与当月完成单量/距下一档
  Future<Map<String, dynamic>> merchantCommissionTier() async =>
      await _request('GET', '/merchants/me/commission-tier')
          as Map<String, dynamic>;

  Future<Withdrawal> requestMerchantWithdrawal(int amountCents) async {
    final data = await _request('POST', '/merchants/me/withdrawals',
        body: {'amount_cents': amountCents});
    return Withdrawal.fromJson(data as Map<String, dynamic>);
  }

  // ---------- 配送异常(骑手) ----------
  /// kind: cannot_contact / wrong_address / food_damaged / other
  Future<void> reportDeliveryIssue(String orderNo, String kind,
          {String note = '', String photoUrl = ''}) =>
      _request('POST', '/riders/issues', body: {
        'order_no': orderNo,
        'kind': kind,
        'note': note,
        'photo_url': photoUrl,
      });

  // ---------- 食品安全投诉(红线通道,不经商家直达平台) ----------
  /// kind: foreign_object 异物 / spoiled 变质 / sick 食用后不适
  Future<void> reportFoodSafety(String orderNo, String kind,
          String description, List<String> images,
          {List<String> medicalUrls = const []}) =>
      _request('POST', '/food-safety', body: {
        'order_no': orderNo,
        'kind': kind,
        'description': description,
        'images': images,
        'medical_urls': medicalUrls,
      });

  // ---------- 收款账户(骑手/商家提现打款目标) ----------
  Future<PayoutAccount> payoutAccount() async {
    final data = await _request('GET', '/payout-account');
    return PayoutAccount.fromJson(data as Map<String, dynamic>);
  }

  Future<PayoutAccount> savePayoutAccount({
    required String kind,
    required String holderName,
    required String accountNo,
    String bankName = '',
  }) async {
    final data = await _request('PUT', '/payout-account', body: {
      'kind': kind,
      'holder_name': holderName,
      'account_no': accountNo,
      'bank_name': bankName,
    });
    return PayoutAccount.fromJson(data as Map<String, dynamic>);
  }

  // ---------- 判责申诉(骑手/商家) ----------
  Future<List<Map<String, dynamic>>> riderIssues() async =>
      ((await _request('GET', '/riders/issues')) as List)
          .cast<Map<String, dynamic>>();

  Future<List<Map<String, dynamic>>> myAppeals() async =>
      ((await _request('GET', '/appeals/mine')) as List)
          .cast<Map<String, dynamic>>();

  /// targetType: after_sale / delivery_issue / review
  Future<void> submitAppeal({
    required String targetType,
    required int targetId,
    required String reason,
    List<String> images = const [],
  }) =>
      _request('POST', '/appeals', body: {
        'target_type': targetType,
        'target_id': targetId,
        'reason': reason,
        'images': images,
      });

  // ---------- 改地址(骑手取餐前,每单一次) ----------
  Future<Order> changeAddress(String orderNo, Address address) async {
    final data =
        await _request('POST', '/orders/$orderNo/change-address', body: {
      'address': address.fullAddress,
      'lat': address.lat,
      'lng': address.lng,
      'contact_name': address.contactName,
      'contact_phone': address.contactPhone,
    });
    return Order.fromJson(data as Map<String, dynamic>);
  }

  /// 加急小费:无人接单时追加小费(分),更快有人接。100% 归骑手
  Future<Order> boostTip(String orderNo, int addCents) async {
    final data = await _request('POST', '/orders/$orderNo/boost-tip',
        body: {'add_cents': addCents});
    return Order.fromJson(data as Map<String, dynamic>);
  }

  // ---------- 催单 ----------
  /// 返回 {target: merchant/rider, times_used, times_left}
  Future<Map<String, dynamic>> urgeOrder(String orderNo) async =>
      await _request('POST', '/orders/$orderNo/urge') as Map<String, dynamic>;

  Future<void> urgeReply(String orderNo, String text) =>
      _request('POST', '/orders/$orderNo/urge-reply', body: {'text': text});

  // ---------- 经营质量(商家) ----------
  /// {completed_30d, ready_late_30d, ready_late_rate, rejects_30d, promise_ready_minutes}
  Future<Map<String, dynamic>> merchantQuality() async =>
      await _request('GET', '/merchants/me/quality') as Map<String, dynamic>;

  // ---------- 发票(商家) ----------
  Future<Map<String, dynamic>> invoiceSummary(String period) async =>
      await _request('GET', '/invoices/summary',
          query: {'period': period}) as Map<String, dynamic>;

  Future<List<Map<String, dynamic>>> myInvoices() async =>
      ((await _request('GET', '/invoices/mine')) as List)
          .cast<Map<String, dynamic>>();

  Future<void> applyInvoice({
    required String period,
    required String title,
    required String taxNo,
    required String email,
  }) =>
      _request('POST', '/invoices', body: {
        'period': period,
        'title': title,
        'tax_no': taxNo,
        'email': email,
      });

  // ---------- 客服工单 ----------
  /// 客服 FAQ 自助分流:[{q, a, action}]
  Future<List<Map<String, dynamic>>> supportFaq() async {
    final data = await _request('GET', '/support/faq');
    return ((data as Map)['faq'] as List).cast<Map<String, dynamic>>();
  }

  /// 自助退款前置判断:{eligible, reason, refund_cents?, suggest_ticket?, ticket_context?}
  Future<Map<String, dynamic>> selfRefundCheck(String orderNo) async {
    final data = await _request('GET', '/orders/$orderNo/self-refund/check');
    return data as Map<String, dynamic>;
  }

  /// 自助退款:规则明确场景即时退,不建工单
  Future<Order> selfRefund(String orderNo) async {
    final data = await _request('POST', '/orders/$orderNo/self-refund');
    return Order.fromJson(data as Map<String, dynamic>);
  }

  Future<Ticket> submitTicket(String content, {String contact = ''}) async {
    final data = await _request('POST', '/tickets',
        body: {'content': content, 'contact': contact});
    return Ticket.fromJson(data as Map<String, dynamic>);
  }

  Future<List<Ticket>> myTickets() async {
    final data = await _request('GET', '/tickets/mine');
    return (data as List)
        .map((e) => Ticket.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  // ---------- 住宿(酒店垂类) ----------

  /// 商家:我的房型列表
  Future<List<RoomType>> stayRoomTypes() async {
    final data = await _request('GET', '/stays/me/room-types');
    return (data as List)
        .map((e) => RoomType.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 商家:新建房型
  Future<RoomType> createRoomType(Map<String, dynamic> fields) async {
    final data =
        await _request('POST', '/stays/me/room-types', body: fields);
    return RoomType.fromJson(data as Map<String, dynamic>);
  }

  /// 商家:编辑房型(下架传 is_on_sale=false,不删)
  Future<RoomType> updateRoomType(int id, Map<String, dynamic> fields) async {
    final data =
        await _request('PATCH', '/stays/me/room-types/$id', body: fields);
    return RoomType.fromJson(data as Map<String, dynamic>);
  }

  /// 商家:日历批量设置(日期区间 × 多房型,统一改价/改总量/开关房)
  Future<void> setStayCalendar({
    required List<int> roomTypeIds,
    required String fromDate,
    required String toDate,
    int? priceCents,
    int? totalQty,
    bool? closed,
  }) async {
    await _request('PUT', '/stays/me/calendar', body: {
      'room_type_ids': roomTypeIds,
      'from_date': fromDate,
      'to_date': toDate,
      if (priceCents != null) 'price_cents': priceCents,
      if (totalQty != null) 'total_qty': totalQty,
      if (closed != null) 'closed': closed,
    });
  }

  /// 商家:日历网格(每房型一行,缺的日期表示「未设价」)
  Future<List<RoomCalendarRow>> stayCalendar(
      {String? fromDate, int days = 14}) async {
    final query = fromDate == null
        ? '?days=$days'
        : '?from_date=$fromDate&days=$days';
    final data = await _request('GET', '/stays/me/calendar$query');
    return (data as List)
        .map((e) => RoomCalendarRow.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 商家:住宿订单列表(all/pending/arriving/inhouse/leaving)
  Future<List<StayOrder>> stayMerchantOrders({String state = 'all'}) async {
    final data = await _request('GET', '/stays/me/orders?state=$state');
    return (data as List)
        .map((e) => StayOrder.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 商家:确认订单
  Future<StayOrder> stayConfirm(String orderNo) async {
    final data =
        await _request('POST', '/stays/me/orders/$orderNo/confirm');
    return StayOrder.fromJson(data as Map<String, dynamic>);
  }

  /// 商家:拒单(原因会展示给用户,全额退款)
  Future<StayOrder> stayReject(String orderNo, String reason) async {
    final data = await _request('POST', '/stays/me/orders/$orderNo/reject',
        body: {'reason': reason});
    return StayOrder.fromJson(data as Map<String, dynamic>);
  }

  /// 商家:办理入住(核销)
  Future<StayOrder> stayCheckin(String orderNo) async {
    final data =
        await _request('POST', '/stays/me/orders/$orderNo/checkin');
    return StayOrder.fromJson(data as Map<String, dynamic>);
  }

  /// 商家:办理离店(结算触发点,佣金 5% 在此产生)
  Future<StayOrder> stayCheckout(String orderNo) async {
    final data =
        await _request('POST', '/stays/me/orders/$orderNo/checkout');
    return StayOrder.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:酒店列表(按入住区间报价)
  Future<List<HotelCard>> hotels({
    double? lat,
    double? lng,
    String? checkin,
    String? checkout,
    String q = '',
    String sort = 'comprehensive',
    String? tier,
    int? minPriceCents,
    int? maxPriceCents,
  }) async {
    final params = <String, String>{
      if (lat != null) 'lat': '$lat',
      if (lng != null) 'lng': '$lng',
      if (checkin != null) 'checkin': checkin,
      if (checkout != null) 'checkout': checkout,
      if (q.isNotEmpty) 'q': q,
      'sort': sort,
      if (tier != null) 'tier': tier,
      if (minPriceCents != null) 'min_price_cents': '$minPriceCents',
      if (maxPriceCents != null) 'max_price_cents': '$maxPriceCents',
    };
    final query = params.entries
        .map((e) => '${e.key}=${Uri.encodeQueryComponent(e.value)}')
        .join('&');
    final data = await _request('GET', '/stays/hotels?$query');
    return (data as List)
        .map((e) => HotelCard.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 用户:酒店详情 + 房型报价(改日期即重新报价)
  Future<HotelDetail> hotelDetail(int id,
      {String? checkin, String? checkout}) async {
    final params = [
      if (checkin != null) 'checkin=$checkin',
      if (checkout != null) 'checkout=$checkout',
    ].join('&');
    final data = await _request(
        'GET', '/stays/hotels/$id${params.isEmpty ? '' : '?$params'}');
    return HotelDetail.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:住宿下单(锁定库存,15 分钟内支付)
  Future<StayOrder> createStayOrder({
    required int roomTypeId,
    required String checkinDate,
    required String checkoutDate,
    required int roomsQty,
    required String guestName,
    required String guestPhone,
    String arrivalNote = '',
  }) async {
    final data = await _request('POST', '/stays/orders', body: {
      'room_type_id': roomTypeId,
      'checkin_date': checkinDate,
      'checkout_date': checkoutDate,
      'rooms_qty': roomsQty,
      'guest_name': guestName,
      'guest_phone': guestPhone,
      'arrival_note': arrivalNote,
    });
    return StayOrder.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:模拟支付(微信支付联调时替换,与外卖/团购同语义)
  Future<StayOrder> payStayMock(String orderNo) async {
    final data = await _request('POST', '/stays/orders/$orderNo/pay/mock');
    return StayOrder.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:我的住宿订单
  Future<List<StayOrder>> myStayOrders() async {
    final data = await _request('GET', '/stays/orders/mine');
    return (data as List)
        .map((e) => StayOrder.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 用户:住宿订单详情
  Future<StayOrder> stayOrderDetail(String orderNo) async {
    final data = await _request('GET', '/stays/orders/$orderNo');
    return StayOrder.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:取消试算(无副作用,确认弹层展示预计退款)
  Future<StayCancelPreview> stayCancelPreview(String orderNo) async {
    final data =
        await _request('GET', '/stays/orders/$orderNo/cancel-preview');
    return StayCancelPreview.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:取消订单(按取消政策退款)
  Future<StayOrder> cancelStayOrder(String orderNo) async {
    final data = await _request('POST', '/stays/orders/$orderNo/cancel');
    return StayOrder.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:提交住宿点评(离店后 15 天内,一单一评)
  Future<StayReview> createStayReview(String orderNo,
      {required int rating,
      String comment = '',
      List<String> tags = const [],
      List<String> imageUrls = const [],
      bool isAnonymous = false}) async {
    final data = await _request('POST', '/stays/orders/$orderNo/review', body: {
      'rating': rating,
      'comment': comment,
      'tags': tags,
      'image_urls': imageUrls,
      'is_anonymous': isAnonymous,
    });
    return StayReview.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:我的这单点评(没有则 404)
  Future<StayReview> myStayReview(String orderNo) async {
    final data = await _request('GET', '/stays/orders/$orderNo/review');
    return StayReview.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:追评(首评后 7 天内一次)
  Future<StayReview> appendStayReview(int reviewId, String content) async {
    final data = await _request('POST', '/stays/reviews/$reviewId/append',
        body: {'content': content});
    return StayReview.fromJson(data as Map<String, dynamic>);
  }

  /// 公开:酒店点评列表
  Future<List<StayReview>> hotelReviews(int hotelId) async {
    final data = await _request('GET', '/stays/hotels/$hotelId/reviews');
    return (data as List)
        .map((e) => StayReview.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 商家:本店住宿点评
  Future<List<StayReview>> merchantStayReviews() async {
    final data = await _request('GET', '/stays/me/reviews');
    return (data as List)
        .map((e) => StayReview.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 商家:回复点评(首评未回复则回复首评,否则回复追评/修改)
  Future<StayReview> replyStayReview(int reviewId, String reply) async {
    final data = await _request('POST', '/stays/me/reviews/$reviewId/reply',
        body: {'reply': reply});
    return StayReview.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:发起住宿售后(no_room 到店无房 / nego_refund 协商退)
  Future<StayAfterSale> createStayAftersale(String orderNo,
      {required String kind, String note = ''}) async {
    final data = await _request('POST', '/stays/orders/$orderNo/aftersale',
        body: {'kind': kind, 'note': note});
    return StayAfterSale.fromJson(data as Map<String, dynamic>);
  }

  /// 用户:这单最近一次售后(没有则 404)
  Future<StayAfterSale> myStayAftersale(String orderNo) async {
    final data = await _request('GET', '/stays/orders/$orderNo/aftersale');
    return StayAfterSale.fromJson(data as Map<String, dynamic>);
  }

  /// 商家:本店售后列表
  Future<List<StayAfterSale>> merchantStayAftersales() async {
    final data = await _request('GET', '/stays/me/aftersales');
    return (data as List)
        .map((e) => StayAfterSale.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 商家:响应售后(协商退同意时必须带 refundCents)
  Future<StayAfterSale> respondStayAftersale(int id,
      {required bool accept, String note = '', int? refundCents}) async {
    final data = await _request('POST', '/stays/me/aftersales/$id/respond',
        body: {
          'accept': accept,
          'note': note,
          if (refundCents != null) 'refund_cents': refundCents,
        });
    return StayAfterSale.fromJson(data as Map<String, dynamic>);
  }
}
