#!/bin/bash
# Linux 定时任务安装脚本（cron）
# 从 .knowledge-iteration-system.json 的 automation 配置读取：
#   - dailyIntervalDays: 1/2/3/4 或 空/0 表示不安装
#   - dailyRunAtHour: 每天在几点跑
#   - dailyScanDays: 每次扫描最近多少天
# 用法：
#   bash scripts/install_automation_linux.sh --dry-run
#   bash scripts/install_automation_linux.sh
#   bash scripts/install_automation_linux.sh --interval 3
#   bash scripts/install_automation_linux.sh --uninstall
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
RUNNER="$SCRIPT_DIR/run_all.py"
BEGIN_MARK="# BEGIN knowledge-iteration-system"
END_MARK="# END knowledge-iteration-system"

PYTHON_BIN=""
# cron 环境的 PATH 很小，`python3` 可能指向旧版本。
# run_all.py 需 3.10+（PEP 604 联合类型），仅 3.9 下缓解靠 __future__ 不够：
# 其他子脚本也用了 3.10+ 语法。所以探测并写绝对路径。
pick_python() {
  local candidate="$1"
  [ -z "$candidate" ] && return 1
  "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1 || return 1
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
  "/usr/local/bin/python3" \
  "/usr/bin/python3" \
  "$(command -v python || true)"; do
  if pick_python "$cand"; then
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "❌ 未找到 Python 3.10+，请先安装（run_all.py 依赖 PEP 604 联合类型语法）。"
  exit 1
fi

echo "🔬 知识蒸馏自动化安装脚本（Linux cron）"
echo "================================"
echo "Vault:  $VAULT"
echo "Python: $PYTHON_BIN"
echo "Runner: $RUNNER"
echo ""

if [ "$UNINSTALL" -eq 1 ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[Dry Run] 将从 crontab 删除 $BEGIN_MARK 到 $END_MARK 之间的内容。"
    exit 0
  fi
  (crontab -l 2>/dev/null | sed "/$BEGIN_MARK/,/$END_MARK/d") | crontab -
  echo "✅ 已卸载 cron 任务。"
  exit 0
fi

# 读取 automation 配置
SETTINGS="$(cd "$VAULT" && "$PYTHON_BIN" - <<PY
import sys
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
            print("ERR interval-invalid")
            sys.exit(3)
print(interval if interval is not None else "NONE", automation_scan_days(), automation_run_hour())
PY
)"

INTERVAL="$(echo "$SETTINGS" | awk '{print $1}')"
SCAN_DAYS="$(echo "$SETTINGS" | awk '{print $2}')"
RUN_HOUR="$(echo "$SETTINGS" | awk '{print $3}')"

if [ "$INTERVAL" = "NONE" ]; then
  echo "⚠️ 当前配置为“不开启自动化”。"
  echo "   先运行：python3 scripts/setup_preflight.py --set-daily-interval N (N 为 1/2/3/4)"
  echo "   或临时安装：bash scripts/install_automation_linux.sh --interval N"
  exit 0
fi

# cron 语法：
# - 每天:            0 H * * *
# - 每 N 天 (N>1): 0 H */N * *   (注意 */N 不严格等于“每 N 天”，但在多数环境下够用)
if [ "$INTERVAL" = "1" ]; then
  CRON_EXPR="0 ${RUN_HOUR} * * *"
else
  CRON_EXPR="0 ${RUN_HOUR} */${INTERVAL} * *"
fi

CRON_LINE="${CRON_EXPR} cd '$VAULT' && '$PYTHON_BIN' '$RUNNER' --only daily --days ${SCAN_DAYS} >> '$VAULT/scripts/distill.log' 2>> '$VAULT/scripts/distill.error.log'"

echo "配置：每 ${INTERVAL} 天在 ${RUN_HOUR}:00 自动运行，扫描最近 ${SCAN_DAYS} 天。"
echo ""

if [ "$DRY_RUN" -eq 1 ]; then
  echo "=== [Dry Run] 预览 ==="
  echo "$BEGIN_MARK"
  echo "$CRON_LINE"
  echo "$END_MARK"
  echo ""
  echo "实际安装请去掉 --dry-run。"
  exit 0
fi

TMP_FILE="$(mktemp)"
(crontab -l 2>/dev/null | sed "/$BEGIN_MARK/,/$END_MARK/d"; echo "$BEGIN_MARK"; echo "$CRON_LINE"; echo "$END_MARK") > "$TMP_FILE"
crontab "$TMP_FILE"
rm -f "$TMP_FILE"

echo "✅ cron 定时任务已安装。"
echo "运行频率：${CRON_EXPR}"
echo "卸载命令：bash scripts/install_automation_linux.sh --uninstall"
