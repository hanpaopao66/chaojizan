#!/usr/bin/env bash
# 服务健康监控 + 手机告警(M2 保命线)。
#
# 探测 /health(它会真实检查数据库和 Redis),连续 FAIL_THRESHOLD 次失败
# 就向钉钉/企业微信群机器人 webhook 发告警;恢复时发解除通知。
# 磁盘使用率超过 DISK_LIMIT 也告警。
#
# 部署机 crontab(每分钟):
#   * * * * * WEBHOOK_URL='https://oapi.dingtalk.com/robot/send?access_token=xxx' \
#     /home/dddd/super-z/deploy/healthcheck-alert.sh >> /home/dddd/super-z/backups/health.log 2>&1
#
# 建议同时在阿里云服务器上也挂一份(HEALTH_URL 指公网域名),
# 这样内网整条链路(断电/断网/隧道挂)都能被外部视角发现。
set -uo pipefail

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8010/health}"
WEBHOOK_URL="${WEBHOOK_URL:-}"
FAIL_THRESHOLD="${FAIL_THRESHOLD:-3}"       # 连续失败 N 次才告警,避免抖动误报
DISK_LIMIT="${DISK_LIMIT:-85}"              # 磁盘使用率告警线(%)
STATE_DIR="${STATE_DIR:-/tmp/superz-health}"

mkdir -p "$STATE_DIR"
FAIL_FILE="$STATE_DIR/fails"
ALERTED_FILE="$STATE_DIR/alerted"

send_alert() {
  local text="$1"
  echo "$(date '+%F %T') $text"
  [ -z "$WEBHOOK_URL" ] && { echo "(未配置 WEBHOOK_URL,告警只写日志)"; return; }
  # 转义反斜杠和引号,告警详情里的 JSON 片段不能把消息体本身弄坏
  local escaped
  escaped=$(printf '%s' "$text" | sed 's/\\/\\\\/g; s/"/\\"/g')
  # 钉钉和企业微信群机器人的 text 消息格式相同
  curl -sS -m 10 -H 'Content-Type: application/json' \
    -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"[Super-Z] $escaped\"}}" \
    "$WEBHOOK_URL" >/dev/null || echo "(webhook 发送失败)"
}

# ---- 磁盘检查(与 API 探活相互独立) ----
DISK_USE=$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')
if [ "$DISK_USE" -ge "$DISK_LIMIT" ] && [ ! -f "$STATE_DIR/disk_alerted" ]; then
  send_alert "磁盘告警:根分区已用 ${DISK_USE}%(阈值 ${DISK_LIMIT}%)"
  touch "$STATE_DIR/disk_alerted"
elif [ "$DISK_USE" -lt "$DISK_LIMIT" ]; then
  rm -f "$STATE_DIR/disk_alerted"
fi

# ---- API/数据库/Redis 探活 ----
BODY=$(curl -sS -m 10 "$HEALTH_URL" 2>&1)
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$HEALTH_URL" 2>/dev/null || echo 000)

if [ "$CODE" = "200" ]; then
  if [ -f "$ALERTED_FILE" ]; then
    send_alert "服务已恢复:/health 返回 200"
    rm -f "$ALERTED_FILE"
  fi
  rm -f "$FAIL_FILE"
  exit 0
fi

FAILS=$(( $(cat "$FAIL_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$FAILS" > "$FAIL_FILE"
echo "$(date '+%F %T') 探活失败 $FAILS/$FAIL_THRESHOLD (HTTP $CODE) $BODY"

if [ "$FAILS" -ge "$FAIL_THRESHOLD" ] && [ ! -f "$ALERTED_FILE" ]; then
  send_alert "服务告警:/health 连续 $FAILS 次失败(HTTP $CODE)。详情:$BODY"
  touch "$ALERTED_FILE"
fi
