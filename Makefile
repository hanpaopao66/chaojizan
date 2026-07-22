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

# 端到端测试(需要 API 已在运行,默认 http://127.0.0.1:8010,可用 SUPERZ_API 覆盖)
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
	  && python -m tests.e2e_category

logs:
	docker compose logs -f api
