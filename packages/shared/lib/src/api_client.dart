import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'models.dart';

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);

  final int statusCode;
  final String message;

  @override
  String toString() => message;
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

  bool get isLoggedIn => _token != null;

  /// WebSocket 地址拼接用(听单通道要带 token)
  String? get token => _token;
  String get wsBaseUrl =>
      baseUrl.replaceFirst('https://', 'wss://').replaceFirst('http://', 'ws://');

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_token != null) 'Authorization': 'Bearer $_token',
      };

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
    } catch (_) {
      // 静默:网络抖动或 token 已失效都不打断当前操作
    } finally {
      _refreshing = false;
    }
  }

  Future<dynamic> _request(String method, String path,
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
      throw ApiException(response.statusCode, message);
    }
    return text.isEmpty ? null : jsonDecode(text);
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
  }

  Future<void> register(
      String phone, String password, String name, String role) async {
    final data = await _request('POST', '/auth/register',
        body: {'phone': phone, 'password': password, 'name': name, 'role': role});
    _token = data['token'] as String;
    _tokenIssuedAt = DateTime.now();
    userId = data['user_id'] as int;
    userName = data['name'] as String;
  }

  /// 发验证码。短信服务未配置时返回开发模式验证码(devCode),已配置返回 null
  Future<String?> sendSmsCode(String phone) async {
    final data = await _request('POST', '/auth/sms-code', body: {'phone': phone});
    return (data as Map)['dev_code'] as String?;
  }

  /// 验证码登录,新手机号自动注册为用户
  Future<void> smsLogin(String phone, String code) async {
    final data = await _request('POST', '/auth/sms-login', body: {
      'phone': phone,
      'code': code,
      'device_id': await _deviceId(),
    });
    _token = data['token'] as String;
    _tokenIssuedAt = DateTime.now();
    userId = data['user_id'] as int;
    userName = data['name'] as String;
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

  Future<void> setFavorite(int merchantId, bool favorited) => _request(
      favorited ? 'POST' : 'DELETE', '/favorites/$merchantId');

  // ---------- 用户端 ----------
  /// sort: distance(综合) / rating(评分优先) / sales(月售优先)
  Future<List<Merchant>> merchants(
      {double? lat, double? lng, String sort = 'distance',
      String? category}) async {
    final data = await _request('GET', '/merchants', query: {
      if (lat != null) 'lat': '$lat',
      if (lng != null) 'lng': '$lng',
      'sort': sort,
      if (category != null && category.isNotEmpty) 'category': category,
    });
    return (data as List)
        .map((e) => Merchant.fromJson(e as Map<String, dynamic>))
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
  }) async {
    final data = await _request('POST', '/orders/$orderNo/review', body: {
      'merchant_rating': merchantRating,
      if (riderRating != null) 'rider_rating': riderRating,
      'comment': comment,
      'image_urls': imageUrls,
      'tags': tags,
    });
    return Review.fromJson(data as Map<String, dynamic>);
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

  /// 商家看自己店的评价
  Future<List<Review>> myReviews() async {
    final data = await _request('GET', '/merchants/me/reviews');
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
    });
    return Address.fromJson(data as Map<String, dynamic>);
  }

  Future<Address> updateAddress(int id, Map<String, dynamic> fields) async {
    final data = await _request('PATCH', '/addresses/$id', body: fields);
    return Address.fromJson(data as Map<String, dynamic>);
  }

  Future<void> deleteAddress(int id) => _request('DELETE', '/addresses/$id');

  /// POI 输入提示(服务端代理高德,Key 不下发)
  Future<List<PoiTip>> geoTips(String keywords, {String city = '成都'}) async {
    final data = await _request('GET', '/geo/tips',
        query: {'keywords': keywords, 'city': city});
    return (data as List)
        .map((e) => PoiTip.fromJson(e as Map<String, dynamic>))
        .toList();
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

  /// 云打印补打某一单的小票
  Future<void> reprintOrder(String orderNo) =>
      _request('POST', '/merchants/me/orders/$orderNo/print');

  // ---------- 通用订单 ----------
  Future<List<Order>> myOrders() async {
    final data = await _request('GET', '/orders');
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
    List<Map<String, dynamic>> options = const [],
  }) async {
    final data = await _request('POST', '/merchants/me/dishes', body: {
      'name': name,
      'category': category,
      'price_cents': priceCents,
      'stock': stock,
      'daily_stock': dailyStock,
      'is_alcohol': isAlcohol,
      'image_url': imageUrl,
      'options': options,
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
  Future<String> uploadImage(List<int> bytes, String filename) async {
    final request =
        http.MultipartRequest('POST', Uri.parse('$baseUrl/upload'));
    if (_token != null) request.headers['Authorization'] = 'Bearer $_token';
    request.files
        .add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    final response = await http.Response.fromStream(
        await request.send().timeout(const Duration(seconds: 30)));
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

  /// 对账:某日入账明细(day 格式 yyyy-MM-dd)
  Future<List<FinanceOrder>> financeOrders(String day) async {
    final data =
        await _request('GET', '/merchants/me/finance/orders', query: {'day': day});
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

  Future<RiderProfile> submitRiderProfile({
    required String realName,
    required String idCardNo,
    required String idCardPhotoUrl,
    required String healthCertPhotoUrl,
  }) async {
    final data = await _request('POST', '/riders/profile', body: {
      'real_name': realName,
      'id_card_no': idCardNo,
      'id_card_photo_url': idCardPhotoUrl,
      'health_cert_photo_url': healthCertPhotoUrl,
    });
    return RiderProfile.fromJson(data as Map<String, dynamic>);
  }

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
}
