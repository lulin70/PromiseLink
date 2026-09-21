#!/usr/bin/env bash
# 干净环境 · release 桌面包 · 真实用户链路 e2e（§9.7 第 5 条 / P0-2）
#
# 为什么需要它：既有 e2e 全部在源码树上跑（`.venv` + 仓库内 `.env`），
# 无法覆盖"用户从官网下载 dmg → 双击 → 配对 → 重启"这条唯一交付路径。
# 2026-09-19 的"每次启动都要重新配对"与 2026-09-20 的"桌面包 WSS 永不启动"
# 两个 P0 都属于这条路径，源码树 e2e 不可能发现。
#
# 做法：把 HOME 指到一个全新空目录再启动包内二进制，从而
#   - `~/.promiselink/.env` / `~/.promiselink/data` 都是干净的（等价于新机器）
#   - 不需要动本机真实 `~/.promiselink/`，不污染开发者环境
#
# 覆盖：启动 → 取配对码（网关可达）→ 激活写 .env → WSS 起连 → 终态对用户可见
#       （② /pair/status 报 rejected + 归因）→ 杀进程（⑦ 优雅停机 < 5s）→
#       重启后许可证仍在（不再要求重新配对）→ 无效证书不会造成重试风暴
#       → ⑥ 文件日志已落盘且不含许可证明文
#
# 断言数：19（若包早于 L-1/L-14，⑤ 与 ② 会显式标注"该包无此能力"并跳过 3 条 → 16）
# 注：⑥ 的两条是**硬断言**。它验证的是"窗口化（console=False）之后日志仍然拿得到"，
#     早于 ⑥ 的包（console=True，无文件日志）必然为红 —— 属预期，那些包不满足 ⑥
#     之后的发布条件，不应再作为发布候选重跑本脚本。
#
# 不覆盖（必须人工，脚本会显式标注）：小程序真人扫码那一步。脚本走的是扫码
# 完成后桌面轮询任务所调用的同一个 `POST /api/v1/pair/activate`。
#
# 关于断言取数：包的 `/api/v1/health` 是**未认证短响应**（只有 status/version），
# 带 components 的 `/api/v1/health/full` 需要认证，故本脚本一律以**包的启动
# 日志**为事实来源 —— 这也是用户在"复制诊断信息"时真正拿得到的东西。
#
# 用法：scripts/e2e/e2e_release_package_clean_env.sh <PromiseLink.app 路径> [工作目录]
# 退出码：0 = 全部断言通过；非 0 = 有断言失败（失败明细见输出）

set -uo pipefail

APP_PATH="${1:-}"
WORKDIR="${2:-/tmp/pl_release_package_e2e}"
PORT=8000
BASE="http://127.0.0.1:${PORT}"
# 刻意使用无效许可证：既验证"激活即写盘"，也顺带观察 WSS 对无效证书的反应。
# 已含 L-1/L-14 修复的包应止步于 relay_wss_auth_terminal；旧包会持续重试。
E2E_LICENSE_KEY="PL-PRO-E2E0-0000-0001"

PASS=0
FAIL=0
STOP_ELAPSED=0
ok()   { echo "  ✅ $1"; PASS=$((PASS + 1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }
step() { echo; echo "── $1"; }

if [[ -z "$APP_PATH" || ! -x "$APP_PATH/Contents/MacOS/PromiseLink" ]]; then
  echo "用法: $0 <PromiseLink.app 路径> [工作目录]" >&2
  echo "错误: 找不到可执行文件 $APP_PATH/Contents/MacOS/PromiseLink" >&2
  exit 2
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "错误: 端口 $PORT 已被占用，请先停掉本机其他 PromiseLink 实例" >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2
  exit 2
fi

rm -rf "$WORKDIR"
mkdir -p "$WORKDIR/home"

APP_HOME="$WORKDIR/home"
BIN="$APP_PATH/Contents/MacOS/PromiseLink"
LOG_FIRST="$WORKDIR/run_first.log"
LOG_SECOND="$WORKDIR/run_second.log"

echo "包路径   : $APP_PATH"
echo "干净 HOME: $APP_HOME"
echo "版本(Info.plist 自报): $(plutil -extract CFBundleShortVersionString raw "$APP_PATH/Contents/Info.plist" 2>/dev/null || echo n/a)"

launch() {
  HOME="$APP_HOME" nohup "$BIN" > "$1" 2>&1 < /dev/null &
  echo $!
}

wait_for_health() {
  for _ in $(seq 1 40); do
    if curl -s -m 3 "$BASE/api/v1/health" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

port_free() { ! lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; }
app_pids() { pgrep -f "$BIN" 2>/dev/null; }

# 为什么不能只看 PID、也不能只看端口：
#  - PyInstaller onefile 的 bootloader 收到信号就先退出，真正服务的子进程还在跑；
#  - uvicorn 在停机一开始就先关掉监听 socket，端口随即释放，但 lifespan 停机
#    （等"事件维护"等后台任务收尾）还要继续跑十几秒。
# 两者都会让"已退出"的判断偏早：断言日志时假红，立刻重启时假绿。
# 因此以"包内二进制的进程全部消失"为判据，并记录耗时（耗时本身就是用户体验指标）。
stop_pid() {
  local t0=$SECONDS
  kill "$1" 2>/dev/null
  for _ in $(seq 1 90); do
    [[ -z "$(app_pids)" ]] && { STOP_ELAPSED=$((SECONDS - t0)); return 0; }
    sleep 1
  done
  pkill -9 -f "$BIN" 2>/dev/null
  sleep 2
  STOP_ELAPSED=$((SECONDS - t0))
  [[ -z "$(app_pids)" ]]
}

# ════════════════════════════════════════════════════════════════
step "1/8 首次启动（空 HOME，等价新机器）"
PID1=$(launch "$LOG_FIRST")
if wait_for_health; then
  ok "本地服务在 ${PORT} 就绪（首次启动无需任何配置）"
else
  bad "40s 内 /api/v1/health 无响应；日志尾部："
  tail -20 "$LOG_FIRST"
  kill "$PID1" 2>/dev/null
  exit 1
fi

# ⑥（2026-09-21）：包已改 console=False（窗口化），不再有终端窗口 —— 文件日志
# 是用户/售后唯一还能拿到的证据。这里断言的是"窗口化之后日志没有丢"。
APP_LOG="$APP_HOME/.promiselink/logs/promiselink.log"
if [[ -f "$APP_LOG" ]] && grep -q "promiselink_starting" "$APP_LOG"; then
  ok "⑥ 文件日志已落盘且含启动行：${APP_LOG#*/}"
else
  bad "⑥ 未生成文件日志或其中无启动行（窗口化后终端没了，日志不能再丢）"
fi
VERSION=$(curl -s -m 5 "$BASE/api/v1/health" | python3 -c "import json,sys;print(json.load(sys.stdin).get('version',''))" 2>/dev/null)
if [[ -n "$VERSION" ]]; then
  ok "应用内自报版本 = ${VERSION}（应与发布的 tag 一致）"
else
  bad "无法从 /api/v1/health 取到 version"
fi

step "2/8 启动时不应去连网关（未配对）"
if grep -q "relay_wss_start_scheduled" "$LOG_FIRST"; then
  bad "未配对就尝试启动 WSS（日志含 relay_wss_start_scheduled）"
else
  ok "未配对时不启动 WSS（符合预期）"
fi

step "3/8 取配对码（证明网关可达）"
INIT=$(curl -s -m 20 -X POST "$BASE/api/v1/pair/init")
CODE=$(echo "$INIT" | python3 -c "import json,sys;print(json.load(sys.stdin).get('device_pair_code',''))" 2>/dev/null)
if [[ -n "$CODE" ]]; then
  ok "拿到配对码（长度 ${#CODE}，不落盘明文）"
else
  bad "未拿到配对码：$(echo "$INIT" | head -c 400)"
fi
echo "  ⚠️  人工步骤（脚本不覆盖）：用小程序扫描该码完成配对。"
echo "      下列 4/8 步走的是扫码完成后桌面轮询任务调用的同一个接口。"

step "4/8 激活并落盘 .env"
ACT=$(curl -s -m 30 -X POST "$BASE/api/v1/pair/activate" \
      -H 'Content-Type: application/json' \
      -d "{\"license_key\":\"$E2E_LICENSE_KEY\"}")
if echo "$ACT" | grep -q '"success":true'; then
  ok "POST /pair/activate 返回 success"
else
  bad "激活失败：$(echo "$ACT" | head -c 400)"
fi

ENV_FILE="$APP_HOME/.promiselink/.env"
if [[ -f "$ENV_FILE" ]] && grep -q "^PRO_LICENSE_KEY=$E2E_LICENSE_KEY$" "$ENV_FILE"; then
  ok ".env 落在干净 HOME 内且含 PRO_LICENSE_KEY"
else
  bad "未在 $ENV_FILE 找到 PRO_LICENSE_KEY（含 2026-09-19「写到临时目录」回归风险）"
fi
if grep -q "^RELAY_GATEWAY_URL=" "$ENV_FILE" 2>/dev/null; then
  ok ".env 含 RELAY_GATEWAY_URL（2026-09-20「WSS 永不启动」回归点）"
else
  bad ".env 缺 RELAY_GATEWAY_URL"
fi

# ⑥（2026-09-21）：文件日志是会被用户"复制诊断信息"发给支持的那份东西，
# 许可证必须沿用 L-2 的掩码口径（前 10 位 + ****），不得落明文。
if [[ -f "$APP_LOG" ]]; then
  if grep -q "$E2E_LICENSE_KEY" "$APP_LOG"; then
    bad "⑥ 文件日志落了许可证明文（应从 pair 激活起就掩码）"
  else
    ok "⑥ 文件日志未落许可证明文（沿用 L-2 掩码口径）"
  fi
else
  bad "⑥ 文件日志不存在，脱敏无从验证"
fi

step "5/8 激活后 WSS 应真正起连，且无效证书不得造成重试风暴"
sleep 25
if grep -qE "pair_activate_wss_started|relay_wss_start_scheduled" "$LOG_FIRST"; then
  ok "激活后 WSS 已调度起连"
else
  bad "激活后日志无 WSS 起连记录（WSS 未起连）"
fi
if grep -q "relay_wss_auth_terminal" "$LOG_FIRST"; then
  TERM_LINE=$(grep -m1 "relay_wss_auth_terminal" "$LOG_FIRST")
  ok "无效证书被判定为终态、停止重连（L-1/L-14 修复已进包）：${TERM_LINE#*] }"
else
  RETRIES=$(grep -cE "relay_wss_session_ended|relay_wss_auth_failed_retrying" "$LOG_FIRST")
  if [[ "$RETRIES" -gt 6 ]]; then
    bad "无终态且 25s 内已重试 ${RETRIES} 次 —— 重试风暴（该包早于 L-1/L-14 修复）"
  else
    echo "  ⚠️  日志无 relay_wss_auth_terminal（本包早于 L-1/L-14 修复，预期：v1.1.1）；"
    echo "      25s 内重试 ${RETRIES} 次。注意该包对无效证书会一直重试，勿长期挂机。"
  fi
fi

# ②（2026-09-21）：终态必须对用户可见 —— 配对页轮询的就是这个端点。
# 旧行为：网关只回 pending/matched，本地中继终态不进这个接口 → 配对页永远停在
# 「正在激活...」，凭据被拒也照旧。此断言即"页面能不能告诉用户为什么配不上"。
STATUS_JSON=$(curl -s -m 10 "$BASE/api/v1/pair/status?code=$CODE")
STATUS=$(echo "$STATUS_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
KIND=$(echo "$STATUS_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin).get('rejected_kind',''))" 2>/dev/null)
if grep -q "relay_wss_auth_terminal" "$LOG_FIRST"; then
  if [[ "$STATUS" == "rejected" && -n "$KIND" ]]; then
    ok "/pair/status 报出用户可见终态：status=rejected, rejected_kind=${KIND}（②）"
  else
    bad "/pair/status 未暴露终态：status='${STATUS}' rejected_kind='${KIND}'（期望 rejected + 非空归因）"
  fi
  if echo "$STATUS_JSON" | grep -q "PL-PRO"; then
    bad "/pair/status 回显了许可证明文"
  else
    ok "/pair/status 未回显许可证明文（沿用 L-2 掩码口径）"
  fi
else
  echo "  ⚠️  该包无中继终态能力（早于 L-1/L-14），跳过 ② 断言"
fi

step "6/8 结束进程（模拟用户退出程序）"
if stop_pid "$PID1"; then
  # ⑦（2026-09-21）：用户可见契约是「点退出后很快真的退出」。
  # 旧代码在停机里 `asyncio.wait(_pending_tasks, timeout=30.0)`，而被等的
  # 唯一任务设计上永不结束 → 每次都等满 30s（实机实测 31~32s）。修好后实测 1s。
  if [[ "$STOP_ELAPSED" -lt 5 ]]; then
    ok "进程已退出，优雅停机耗时 ${STOP_ELAPSED}s（⑦：< 5s）"
  else
    bad "优雅停机耗时 ${STOP_ELAPSED}s —— 用户点退出要干等这么久（⑦ 回归）"
  fi
else
  bad "90s 内进程未退出，后续重启验证不可信"
  exit 1
fi
if grep -q "relay_wss_stopped" "$LOG_FIRST"; then
  ok "WSS 随进程优雅停止"
else
  bad "日志无 relay_wss_stopped（停机未优雅收尾）"
fi

step "7/8 重启（同一 HOME，模拟用户再次双击打开）"
PID2=$(launch "$LOG_SECOND")
if wait_for_health; then
  ok "重启后本地服务就绪"
else
  bad "重启后 40s 内无响应；日志尾部："; tail -20 "$LOG_SECOND"
  kill "$PID2" 2>/dev/null; exit 1
fi
if grep -q "relay_wss_start_scheduled" "$LOG_SECOND"; then
  ok "重启后无需再配对即自动起连 WSS（许可证从 .env 读出）"
else
  bad "重启后未起连 WSS —— 「每次启动都要重新配对」回归"
fi

step "8/8 重启后许可证仍在（本用例的核心断言）"
if grep -q "^PRO_LICENSE_KEY=$E2E_LICENSE_KEY$" "$ENV_FILE" 2>/dev/null; then
  ok ".env 中 PRO_LICENSE_KEY 跨重启保持"
else
  bad ".env 中 PRO_LICENSE_KEY 跨重启丢失"
fi
if grep -q "pair_activate" "$LOG_SECOND"; then
  bad "重启后又发起了一次配对激活（不应发生）"
else
  ok "重启未触发二次配对激活"
fi

stop_pid "$PID2" >/dev/null

echo
echo "════════════════════════════════════════"
echo "结果: ${PASS} passed, ${FAIL} failed"
echo "证据: $LOG_FIRST"
echo "      $LOG_SECOND"
echo "      $ENV_FILE"
echo "════════════════════════════════════════"
[[ "$FAIL" -eq 0 ]]