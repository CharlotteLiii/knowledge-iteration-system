#!/bin/bash
# 知识蒸馏自动化安装脚本（macOS LaunchAgents）
# 读取 .knowledge-iteration-system.json 的 automation 配置动态生成 plist：
#   - dailyIntervalDays: 1/2/3/4（0 / 空 表示不安装自动化）
#   - dailyRunAtHour: 每天/每 N 天在几点跑
#   - dailyScanDays: 每次扫描最近多少天
# 用法：
#   bash scripts/install_automation.sh --dry-run
#   bash scripts/install_automation.sh
#   bash scripts/install_automation.sh --interval 3
#   bash scripts/install_automation.sh --uninstall
set -euo pipefail

DRY_RUN=0
UNINSTALL=0
OVERRIDE_INTERVAL=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --interval)
      shift || true; OVERRIDE_INTERVAL="${1:-}" ;;
    --interval=*)
      OVERRIDE_INTERVAL="${arg#*=}" ;;
    *) echo "未知参数: $arg"; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_NAME="com.knowledge-iteration.distiller.plist"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"
LABEL="com.knowledge-iteration.distiller"

# 兼容老命名（Phase 2 前）：如果检测到旧 LaunchAgent，install 时自动迁移，uninstall 时一并清除。
LEGACY_LABEL="com.karpathy.knowledge.distiller"
LEGACY_PLIST_DST="$HOME/Library/LaunchAgents/${LEGACY_LABEL}.plist"

PYTHON_BIN=""
# 优先挑 3.10+（run_all.py 用了 PEP 604 `list[str] | None` 联合类型语法）。
# LaunchAgent 环境 PATH 不含 Homebrew / Framework，`/usr/bin/env python3` 会退回系统
# /usr/bin/python3（macOS 自带 3.9），触发 TypeError。所以这里必须写绝对路径。
pick_python() {
  local candidate="$1"
  [ -z "$candidate" ] && return 1
  "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1 || return 1
  # 解析出真实绝对路径（避免 shim / symlink 在 launchd 里失效）
  local resolved
  resolved="$("$candidate" -c 'import sys; print(sys.executable)' 2>/dev/null || true)"
  [ -z "$resolved" ] && resolved="$candidate"
  PYTHON_BIN="$resolved"
  return 0
}

for cand in \
  "$(command -v python3 || true)" \
  "$(command -v python3.13 || true)" \
  "$(command -v python3.12 || true)" \
  "$(command -v python3.11 || true)" \
  "$(command -v python3.10 || true)" \
  "/opt/homebrew/bin/python3" \
  "/usr/local/bin/python3" \
  "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" \
  "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" \
  "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" \
  "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3" \
  "$(command -v python || true)"; do
  if pick_python "$cand"; then
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "❌ 未找到 Python 3.10+，请先安装（run_all.py 依赖 PEP 604 联合类型语法）。"
  exit 1
fi

echo "🔬 知识蒸馏自动化安装脚本（macOS）"
echo "================================"
echo "Vault:   $VAULT"
echo "Python:  $PYTHON_BIN"
echo "Plist:   $PLIST_DST"
echo ""

if [ "$UNINSTALL" -eq 1 ]; then
  echo "将卸载 LaunchAgent: $LABEL"
  if [ -f "$LEGACY_PLIST_DST" ]; then
    echo "同时会清理旧命名版本：$LEGACY_LABEL"
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[Dry Run] launchctl bootout gui/$(id -u) $PLIST_DST"
    echo "[Dry Run] rm -f $PLIST_DST"
    if [ -f "$LEGACY_PLIST_DST" ]; then
      echo "[Dry Run] launchctl bootout gui/$(id -u) $LEGACY_PLIST_DST"
      echo "[Dry Run] rm -f $LEGACY_PLIST_DST"
    fi
    exit 0
  fi
  launchctl bootout "gui/$(id -u)" "$PLIST_DST" >/dev/null 2>&1 || true
  rm -f "$PLIST_DST"
  if [ -f "$LEGACY_PLIST_DST" ]; then
    launchctl bootout "gui/$(id -u)" "$LEGACY_PLIST_DST" >/dev/null 2>&1 || true
    rm -f "$LEGACY_PLIST_DST"
  fi
  echo "✅ 已卸载"
  exit 0
fi

# 读取 automation 配置
read_settings() {
  cd "$VAULT" && "$PYTHON_BIN" - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts").resolve()))
from kis_config import automation_interval_days, automation_scan_days, automation_run_hour
interval = automation_interval_days()
override = "${OVERRIDE_INTERVAL}"
if override:
    if override.lower() in {"none", "off", "manual", "0"}:
        interval = None
    else:
        try:
            interval = int(override)
        except ValueError:
            print("ERR", "interval-invalid")
            sys.exit(3)
print(interval if interval is not None else "NONE", automation_scan_days(), automation_run_hour())
PY
}

SETTINGS="$(read_settings)"
INTERVAL="$(echo "$SETTINGS" | awk '{print $1}')"
SCAN_DAYS="$(echo "$SETTINGS" | awk '{print $2}')"
RUN_HOUR="$(echo "$SETTINGS" | awk '{print $3}')"

if [ "$INTERVAL" = "NONE" ]; then
  echo "⚠️ 当前配置为“不开启自动化”。"
  echo "   先运行：python3 scripts/setup_preflight.py --set-daily-interval N (N 为 1/2/3/4)"
  echo "   或临时安装：bash scripts/install_automation.sh --interval N"
  exit 0
fi

INTERVAL_SECONDS=$(( INTERVAL * 86400 ))
echo "配置：每 ${INTERVAL} 天在 ${RUN_HOUR}:00 自动运行，扫描最近 ${SCAN_DAYS} 天。"
echo ""

generate_plist() {
  cat >"$1" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${VAULT}/scripts/run_all.py</string>
        <string>--only</string>
        <string>daily</string>
        <string>--days</string>
        <string>${SCAN_DAYS}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${VAULT}</string>
    <key>StartInterval</key>
    <integer>${INTERVAL_SECONDS}</integer>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${RUN_HOUR}</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${VAULT}/scripts/distill.log</string>
    <key>StandardErrorPath</key>
    <string>${VAULT}/scripts/distill.error.log</string>
</dict>
</plist>
PL
}

if [ "$DRY_RUN" -eq 1 ]; then
  echo "=== [Dry Run] 预览 ==="
  echo "将生成: $PLIST_SRC"
  echo "复制到: $PLIST_DST"
  echo "加载:   launchctl bootstrap gui/$(id -u) $PLIST_DST"
  echo ""
  echo "----- 预览 plist 内容 -----"
  TMP_PLIST="$(mktemp)"
  generate_plist "$TMP_PLIST"
  cat "$TMP_PLIST"
  rm -f "$TMP_PLIST"
  echo "----- 预览结束 -----"
  echo ""
  echo "实际安装请去掉 --dry-run。"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents"

# 迁移：如果旧命名版本存在，先 bootout 并删除旧 plist，避免新旧同时运行。
if [ -f "$LEGACY_PLIST_DST" ]; then
  echo "🔄 检测到旧命名 LaunchAgent（$LEGACY_LABEL），将自动迁移到新命名空间。"
  launchctl bootout "gui/$(id -u)" "$LEGACY_PLIST_DST" >/dev/null 2>&1 || true
  rm -f "$LEGACY_PLIST_DST"
  echo "✅ 旧 LaunchAgent 已清理"
  echo ""
fi

echo "步骤 1/3: 生成并写入 plist..."
generate_plist "$PLIST_SRC"
cp "$PLIST_SRC" "$PLIST_DST"
echo "✅ plist 已就绪"

echo ""
echo "步骤 2/3: 加载定时任务..."
launchctl bootout "gui/$(id -u)" "$PLIST_DST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
echo "✅ 定时任务加载成功"

echo ""
echo "步骤 3/3: 验证安装状态..."
launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
RESULT=$(launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | head -5 || true)
if [ -n "$RESULT" ]; then
  echo "✅ 自动化任务已成功安装！"
  echo ""
  echo "任务信息："
  echo "$RESULT"
  echo ""
  echo "📅 运行频率：每 ${INTERVAL} 天 ${RUN_HOUR}:00"
  echo "🔎 扫描范围：每次扫描最近 ${SCAN_DAYS} 天"
  echo "📂 报告位置：第二层：蒸馏层 (Distilled)/每日蒸馏/"
else
  echo "⚠️ 未读取到任务状态，请手动检查 launchctl print gui/$(id -u)/$LABEL"
fi

echo ""
echo "常用命令："
echo "  立即运行一次：launchctl kickstart -k gui/$(id -u)/$LABEL"
echo "  查看日志：cat \"$VAULT/scripts/distill.log\""
echo "  卸载任务：bash scripts/install_automation.sh --uninstall"
