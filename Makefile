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
	@python3 scripts/check_dialog_controller_dispose.py && echo "== 弹层里的输入框控制器跟着弹层销毁 ✓"
	@python3 scripts/check_refresh_pullable.py && echo "== 列表空着、不满一屏也拉得动下拉刷新 ✓"
	@python3 scripts/check_setstate_future.py && echo "== 没有把 Future 交给 setState ✓"
	@python3 scripts/check_sticky_error.py && echo "== 出错页拉成功了能回来 ✓"
	@python3 scripts/check_location_manager.py && echo "== 安卓取位置走系统 LocationManager,不走 Google 融合定位 ✓"
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
	@cd developer-web && npx tsc --noEmit && echo "== developer-web tsc ✓"
# 小程序:SDK(假宿主)、官方小程序的纯函数、文档参考页与 SDK 导出一致(DEV-PROMPTS-39 #338)
	@cd packages/miniapp-sdk && npm test >/dev/null && echo "== miniapp-sdk 测试 ✓"
	@cd miniapps && npx tsc -p . && node scripts/test.mjs >/dev/null && echo "== 官方小程序 tsc + 测试 ✓"
	@node scripts/check_sdk_docs.mjs

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
# 全量 e2e:清单在 server/tests/e2e_suites.txt(新写的 e2e 要加进去,单测会拦漏加的)。
# 跑完再汇总,不在第一个失败处停。CI 把它分成 4 组并行跑:python -m tests.run_e2e --shard k/4
test:
	cd server && python -m tests.run_e2e

# 需要特殊环境或已知不稳定的用例,**故意不放进 make test**:
#   e2e_privacy_phone_strict —— 要对着 PRIVACY_PHONE_STRICT=true 启动的实例跑
#     (用例自己的 docstring 就写了这个前置条件)。
# 原来这里还有 e2e_eta_compensation(按总数数券,脏库上假红);2026-09-14 超时改成
# 只致歉不发券,它改写成按单号断言的 e2e_eta_apology,进了全量清单。
test-special:
	cd server && PRIVACY_PHONE_STRICT=true python -m tests.e2e_privacy_phone_strict
	@echo "提示:上面这条需要服务端也以 PRIVACY_PHONE_STRICT=true 启动"

logs:
	docker compose logs -f api
