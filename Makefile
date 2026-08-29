# Super-Z 常用命令
.PHONY: up down api seed logs

# 起数据库和 Redis(本地开发后端时用)
up:
	docker compose up -d db redis

# 全套容器(含 API)
all:
	docker compose up -d --build

down:
	docker compose down

# 本地跑后端(热重载)
api:
	cd server && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 灌演示数据
seed:
	cd server && python -m scripts.seed

# Dart 静态检查。**必须带上 packages/shared** ——
# 在 app 目录里跑 flutter analyze 不会检查 path 依赖的 shared 包,
# 而客户端大部分代码就在那儿。曾因此漏掉一个重复定义的方法,
# 直到 release 构建才炸出来(analyze 全绿、e2e 全绿,APK 打不出来)。
#
# 另外扫一遍 Dart 字符串里的 \$:'\$id' 在 Dart 里是字面量 $id 不是插值,
# 请求会带着字面的 $orderNo 发出去。这个 analyze 不报(语法合法)、
# e2e 也照不到(测的是服务端),只能靠扫。
analyze:
# CI 里那几个**独立脚本检查**也在这里跑。
#
# 它们本来只在 CI 的「三端静态检查」job 里,而本地一直拿 `make analyze`
# 当"三端都验过了"的依据 —— 于是「字号不再发散」这条在本地一次都没跑过,
# 22 处硬编码字号一路走到 CI 才红。
#
# 这是同一类坑的第三次:analyze 不跑 Dart 单测(已补)、
# CI 不查 TypeScript(已补)、现在是本地不跑 CI 的脚本检查。
# 判据都一样:**本地绿和 CI 绿必须是同一件事**,
# 差一项,"本地全绿"就只是半句话。
#
# 放在最前面:纯 Python/shell、几秒钟,错了就该立刻红,
# 没必要先等几分钟的 flutter pub get。
	@python3 scripts/gen_tokens.py --check && echo "== 设计令牌一致 ✓"
	@python3 scripts/check_channel_tones.py && echo "== 频道色可分辨 ✓"
	@bash scripts/check_fontsize_drift.sh
	@python3 scripts/check_macos_entitlements.py && echo "== macOS 权限声明 ✓"
	@bash scripts/check_wide_layout.sh
# 先 pub get 再 analyze。只写 --no-pub 的话,包解析一过期
# (在别的 app 里跑过 flutter test 就会)analyze 会喷出几千条
# "package:flutter/material.dart 不存在" —— 全是假的。
# 一次这种噪音就够让人以后不再看 analyze 的输出了
	@for d in packages/shared apps/user_app apps/merchant_app apps/rider_app; do \
	  echo "== $$d =="; \
	  (cd $$d && flutter pub get >/dev/null && flutter analyze --no-pub) \
	    || exit 1; \
	done
# **Dart 单测也在这儿跑。**
#
# CI 的「三端静态检查」里有独立的一步 `dart 单测`,而本地 make analyze
# 原来只跑 analyze —— 于是「本地全绿」和「CI 通过」之间一直差着 541 条
# 测试。实际撞过一次:改了商家端订单卡的「⋯」菜单,analyze 干净、
# 全套 e2e 干净、推上去被 CI 里的 order_tab_test 顶回来。
#
# analyze 只看类型,测试才看行为。少这一层,本地的绿是假的。
	@for d in packages/shared apps/user_app apps/merchant_app apps/rider_app; do \
	  if [ -n "$$(find $$d/test -name '*_test.dart' 2>/dev/null)" ]; then \
	    echo "== $$d 单测 =="; \
	    (cd $$d && flutter test) || exit 1; \
	  fi; \
	done
	@echo "== 扫 Dart 字符串里的转义美元符 =="
# 模式必须是「字面反斜杠 + 字面美元」= BRE 的 \\\$。
# 原来写的是 '\\$$'(传给 shell 是 \\$),BRE 里 $ 在模式末尾是**行尾锚点**,
# 于是它只找得到"行尾的反斜杠",行中间的 '\$e' 一个都扫不出来 ——
# 守卫写错的下场比没有守卫更糟:它一直返回绿灯,让人以为这类问题已经绝迹。
# 后来 rider_app 跑腿那段又混进三个,就是这么进来的。
	@! grep -rn '\\\$$' --include="*.dart" packages/ apps/ \
	  || { echo "✗ 上面这些 '\\$$x' 是字面量,不是插值"; exit 1; }
	@echo "  没有转义美元符 ✓"
	@cd merchant-web && npx tsc --noEmit && echo "== merchant-web tsc ✓"
	@cd admin-web && npx tsc --noEmit && echo "== admin-web tsc ✓"

# 单元测试:纯函数,不起服务不连库,秒级跑完(慢了就没人跑)
unit:
	cd server && python -m pytest tests/unit -q
# MCP 服务的协议层与「没有任何能付钱的工具」那几条。
# 它不在 server/ 下,单独跑一次 —— 少这一行,「助手花不掉你的钱」
# 就只有服务端一半有守卫。
	python -m pytest mcp-server -q
	@echo "—— 再按生产环境跑一遍(CI 的单测 job 没有 .env,APP_ENV 走默认的 prod)——"
	cd server && APP_ENV=prod python -m pytest tests/unit -q

# 端到端测试(需要 API 已在运行,默认 http://127.0.0.1:8010,可用 SUPERZ_API 覆盖)
#
# 本地跑全量的三个前置条件(踩出来的,少一个都跑不完):
#   1. 服务端用 AUTO_FLOW_ENABLED=false 启动 —— 后台清扫会和用例自己调的
#      sweep_once 抢同一批订单,表现为 e2e_auto_flow 时好时坏;
#   2. 全量要注册几十个号,会撞「同 IP 每日 20 条验证码」的生产限流。
#      本地循环清 sms:day:ip:*,**绝不能清 sms:day:p:*** ——
#      e2e_auth_sms 正是靠手机号维度的计数触发滑块;
#   3. 演示库的菜会被历次跑动抽干,跑前把低库存补回去。
test:
	cd server && python -m tests.e2e_orders && python -m tests.e2e_onboarding \
	  && python -m tests.e2e_addresses && python -m tests.e2e_auto_flow \
	  && python -m tests.e2e_reviews && python -m tests.e2e_ws_notify \
	  && python -m tests.e2e_wallet && python -m tests.e2e_finance \
	  && python -m tests.e2e_shop_page && python -m tests.e2e_pricing_hours \
	  && python -m tests.e2e_external_stubs && python -m tests.e2e_rider_verify \
	  && python -m tests.e2e_refund && python -m tests.e2e_after_sale \
	  && python -m tests.e2e_profile_fav && python -m tests.e2e_dashboard \
	  && python -m tests.e2e_support_audit && python -m tests.e2e_reversal_audit \
	  && python -m tests.e2e_account_delete && python -m tests.e2e_operations \
	  && python -m tests.e2e_dish_options && python -m tests.e2e_vouchers \
	  && python -m tests.e2e_p0_commercial && python -m tests.e2e_p1_commercial \
	  && python -m tests.e2e_p2_platform && python -m tests.e2e_p3_touch \
	  && python -m tests.e2e_p4_witness && python -m tests.e2e_screen \
	  && python -m tests.e2e_transparency && python -m tests.e2e_splash \
	  && python -m tests.e2e_category \
	  && python -m tests.e2e_auth_sms && python -m tests.e2e_multi_role \
	  && python -m tests.e2e_stays_base && python -m tests.e2e_stays_inventory \
	  && python -m tests.e2e_stays_search && python -m tests.e2e_stays_order \
	  && python -m tests.e2e_stays_cancel && python -m tests.e2e_stays_autoflow \
	  && python -m tests.e2e_stays_settle && python -m tests.e2e_stays_witness \
	  && python -m tests.e2e_stays_review && python -m tests.e2e_stays_aftersale \
	  && python -m tests.e2e_orders_paging && python -m tests.e2e_referral_funding \
	  && python -m tests.e2e_favorites_paging \
	  && python -m tests.e2e_cancel_split \
	  && python -m tests.e2e_cancel_appeal \
	  && python -m tests.e2e_review_hidden_appeal \
	  && python -m tests.e2e_user_appeal_channels \
	  && python -m tests.e2e_early_ready \
	  && python -m tests.e2e_injection_probe \
	  && python -m tests.e2e_ws_order_auth \
	  && python -m tests.e2e_queue \
	  && python -m tests.e2e_queue_appeal \
	  && python -m tests.e2e_order_flag \
	  && python -m tests.e2e_agent_token \
	  && python -m tests.e2e_api_console \
	  && python -m tests.e2e_channels_flag \
	  && python -m tests.e2e_merchant_promo && python -m tests.e2e_home_filters \
	  && python -m tests.e2e_rider_new_order_push \
	  && python -m tests.e2e_remote_copy \
	  && python -m tests.e2e_upload_privacy \
	  && python -m tests.e2e_readiness \
	  && python -m tests.e2e_address_privacy && python -m tests.e2e_admin_stays \
	  && python -m tests.e2e_admin_worklog && python -m tests.e2e_admin_audit \
	  && python -m tests.e2e_alcohol \
	  && python -m tests.e2e_appeal && python -m tests.e2e_append_order \
	  && python -m tests.e2e_boost_tip && python -m tests.e2e_business_hours2 \
	  && python -m tests.e2e_cancel_rules && python -m tests.e2e_cart_reorder \
	  && python -m tests.e2e_change_address && python -m tests.e2e_chat \
	  && python -m tests.e2e_coupon_ops && python -m tests.e2e_favorite_coupon \
	  && python -m tests.e2e_chain_stores \
	  && python -m tests.e2e_license_expiry \
	  && python -m tests.e2e_printers \
	  && python -m tests.e2e_merchant_ops \
	  && python -m tests.e2e_rider_appeal \
	  && python -m tests.e2e_fee_transparency \
	  && python -m tests.e2e_rider_prefs \
	  && python -m tests.e2e_weather_review \
	  && python -m tests.e2e_rider_stats \
	  && python -m tests.e2e_rider_growth \
	  && python -m tests.e2e_drop_time \
	  && python -m tests.e2e_wait_comp_audit \
	  && python -m tests.e2e_errand_send \
	  && python -m tests.e2e_errand_buy \
	  && python -m tests.e2e_errand_no_rider \
	  && python -m tests.e2e_errand_aftersale \
	  && python -m tests.e2e_daily_stock \
	  && python -m tests.e2e_delivery_issue && python -m tests.e2e_delivery_track \
	  && python -m tests.e2e_deposit && python -m tests.e2e_eta_dynamic \
	  && python -m tests.e2e_food_safety && python -m tests.e2e_gift \
	  && python -m tests.e2e_grab_radius && python -m tests.e2e_group_cart \
	  && python -m tests.e2e_holiday && python -m tests.e2e_identity \
	  && python -m tests.e2e_invoice && python -m tests.e2e_marketing \
	  && python -m tests.e2e_merchant_analytics && python -m tests.e2e_merchant_staff \
	  && python -m tests.e2e_merchant_insight \
	  && python -m tests.e2e_kitchen_cam \
	  && python -m tests.e2e_merchant_statement && python -m tests.e2e_merchant_wallet \
	  && python -m tests.e2e_moderation && python -m tests.e2e_multi_city \
	  && python -m tests.e2e_multi_order && python -m tests.e2e_no_rider \
	  && python -m tests.e2e_payout_account && python -m tests.e2e_pickup \
	  && python -m tests.e2e_pickup_handover && python -m tests.e2e_printer \
	  && python -m tests.e2e_privacy_phone && python -m tests.e2e_profit_sharing \
	  && python -m tests.e2e_ready_timeout && python -m tests.e2e_reassign \
	  && python -m tests.e2e_referral && python -m tests.e2e_review_append \
	  && python -m tests.e2e_rider_accident && python -m tests.e2e_rider_insurance \
	  && python -m tests.e2e_rider_onboarding && python -m tests.e2e_rider_sos \
	  && python -m tests.e2e_rider_transfer && python -m tests.e2e_rider_worklog \
	  && python -m tests.e2e_risk && python -m tests.e2e_risk_action \
	  && python -m tests.e2e_search && python -m tests.e2e_self_delivery \
	  && python -m tests.e2e_self_service && python -m tests.e2e_shop_coupon \
	  && python -m tests.e2e_stays_profile && python -m tests.e2e_stocking \
	  && python -m tests.e2e_tax_export && python -m tests.e2e_tier_commission \
	  && python -m tests.e2e_tip && python -m tests.e2e_transfer_discipline \
	  && python -m tests.e2e_urge && python -m tests.e2e_weather_shutdown \
	  && python -m tests.e2e_withdrawal_failed \
	  && python -m tests.e2e_mini_apps \
	  && python -m tests.e2e_audit_coverage && python -m tests.e2e_authz_regression \
	  && python -m tests.e2e_coupon_release \
	  && python -m tests.e2e_errand_receipt_replay \
	  && python -m tests.e2e_refund_bounds && python -m tests.e2e_refund_order \
	  && python -m tests.e2e_refund_channels \
	  && python -m tests.e2e_soldout_gate \
	  && python -m tests.e2e_stays_noshow_release

# 需要特殊环境或已知不稳定的用例,**故意不放进 make test**:
#   e2e_privacy_phone_strict —— 要对着 PRIVACY_PHONE_STRICT=true 启动的实例跑
#     (用例自己的 docstring 就写了这个前置条件);
#   e2e_eta_compensation —— 在长期共享的开发库上依赖"这一单发了几张券"的
#     精确判定,而库里同时存在别的超时单;干净库(CI)上正常。留红在主回归里
#     会让所有人习惯"红了也没关系",所以单列出来。
test-special:
	cd server && PRIVACY_PHONE_STRICT=true python -m tests.e2e_privacy_phone_strict
	@echo "提示:上面这条需要服务端也以 PRIVACY_PHONE_STRICT=true 启动"
	cd server && python -m tests.e2e_eta_compensation || \
	  echo "(eta_compensation 在脏库上易失败,见 Makefile 注释)"

logs:
	docker compose logs -f api
