#!/bin/bash
# Linux 定时任务安装脚本（cron · per-task v0.2+）
#
# 从 .knowledge-iteration-system.json 的 automation.tasks 表读取每个任务的
# schedule / hour / minute / dayOfWeek，在 crontab 中生成一段带 BEGIN/END
# 标记的块。
#
# 支持的 schedule 值：
#   - daily              → 'M H * * *'
#   - weekly             → 'M H * * dayOfWeek' (0=Sun..6=Sat)
#   - quarterly-last-day → 拆成两行：'M H 31 3,12 *' + 'M H 30 6,9 *'
#
# 用法：
#   bash scripts/install_automation_linux.sh --dry-run
#   bash scripts/install_automation_linux.sh
#   bash scripts/install_automation_linux.sh --uninstall
set -euo pipefail

DRY_RUN=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    *) echo "未知参数: $arg"; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT="$(cd "$SCRIPT_DIR/.." && pwd)"
BEGIN_MARK="# BEGIN knowledge-iteration-system"
END_MARK="# END knowledge-iteration-system"

# ---------- Python 探测 ----------
PYTHON_BIN=""
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

echo "🔬 知识蒸馏自动化安装脚本（Linux cron · per-task v0.2+）"
echo "======================================================"
echo "Vault:  $VAULT"
echo "Python: $PYTHON_BIN"
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

# ---------- 读取任务表 ----------
# 每行输出：key <TAB> schedule <TAB> hour <TAB> minute <TAB> dow <TAB> script <TAB> args_shellquoted
TASKS_TSV="$(cd "$VAULT" && "$PYTHON_BIN" - <<'PY'
import shlex, sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts").resolve()))
from kis_config import ordered_task_items, validate_task
errs = []
rows = []
for key, task in ordered_task_items():
    if not task.get("enabled", True):
        continue
    verr = validate_task(key, task)
    if verr:
        errs.extend(verr)
        continue
    schedule = task.get("schedule")
    hour = int(task.get("hour", 9))
    minute = int(task.get("minute", 0))
    dow = int(task.get("dayOfWeek", -1)) if task.get("dayOfWeek") is not None else -1
    script = str(task.get("script", ""))
    args = task.get("args") or []
    if not isinstance(args, list):
        args = []
    args_str = " ".join(shlex.quote(str(a)) for a in args)
    rows.append("\t".join([key, schedule, str(hour), str(minute), str(dow), script, args_str]))
if errs:
    for e in errs:
        print(e, file=sys.stderr)
    sys.exit(3)
print("\n".join(rows))
PY
)"

if [ -z "${TASKS_TSV// /}" ]; then
  echo "⚠️ 没有启用的自动化任务。"
  echo "   先跑：python3 scripts/setup_preflight.py --ask-tasks"
  exit 0
fi

mkdir -p "$VAULT/scripts/logs"

build_cron_lines() {
  # 打印全部 cron 行到 stdout（不含 BEGIN/END 标记）
  echo "$TASKS_TSV" | while IFS=$'\t' read -r KEY SCHED HH MM DOW SCRIPT ARGS; do
    [ -z "$KEY" ] && continue
    local logfile="$VAULT/scripts/logs/${KEY}.log"
    local errfile="$VAULT/scripts/logs/${KEY}.error.log"
    # cron 不加载用户 shell rc（.bashrc/.zshrc），分离部署时需显式带上 KIS_VAULT_ROOT。
    # 仅当已设置时注入；默认部署（scripts 在 Vault 根下）保持原行为。
    local env_prefix=""
    if [ -n "${KIS_VAULT_ROOT:-}" ]; then
      env_prefix="KIS_VAULT_ROOT='$KIS_VAULT_ROOT' "
    fi
    local cmd="cd '$VAULT' && ${env_prefix}'$PYTHON_BIN' '$VAULT/scripts/$SCRIPT' $ARGS >> '$logfile' 2>> '$errfile'"
    case "$SCHED" in
      daily)
        echo "# $KEY (daily)"
        echo "$MM $HH * * *  $cmd"
        ;;
      weekly)
        echo "# $KEY (weekly, dow=$DOW)"
        echo "$MM $HH * * $DOW  $cmd"
        ;;
      quarterly-last-day)
        echo "# $KEY (quarterly last day; 3/31, 6/30, 9/30, 12/31)"
        echo "$MM $HH 31 3,12 *  $cmd"
        echo "$MM $HH 30 6,9 *  $cmd"
        ;;
      *)
        echo "# WARN: unsupported schedule $SCHED for $KEY, skipped"
        ;;
    esac
  done
}

echo "=== 计划安装的任务 ==="
echo "$TASKS_TSV" | while IFS=$'\t' read -r KEY SCHED HH MM DOW SCRIPT ARGS; do
  [ -z "$KEY" ] && continue
  case "$SCHED" in
    daily) desc="每天 $(printf '%02d:%02d' "$HH" "$MM")";;
    weekly) desc="每周 (dow=$DOW) $(printf '%02d:%02d' "$HH" "$MM")";;
    quarterly-last-day) desc="季度最后一天 $(printf '%02d:%02d' "$HH" "$MM")";;
    *) desc="$SCHED $HH:$MM";;
  esac
  echo "  - $KEY   $desc   → $SCRIPT $ARGS"
done
echo ""

if [ "$DRY_RUN" -eq 1 ]; then
  echo "=== [Dry Run] 预览 crontab 块 ==="
  echo "$BEGIN_MARK"
  build_cron_lines
  echo "$END_MARK"
  echo ""
  echo "实际安装请去掉 --dry-run。"
  exit 0
fi

TMP_FILE="$(mktemp)"
{
  crontab -l 2>/dev/null | sed "/$BEGIN_MARK/,/$END_MARK/d"
  echo "$BEGIN_MARK"
  build_cron_lines
  echo "$END_MARK"
} > "$TMP_FILE"
crontab "$TMP_FILE"
rm -f "$TMP_FILE"

echo "✅ cron 任务已安装。"
echo ""
echo "常用命令："
echo "  查看：crontab -l | sed -n '/${BEGIN_MARK}/,/${END_MARK}/p'"
echo "  查日志：ls \"$VAULT/scripts/logs/\""
echo "  卸载：bash scripts/install_automation_linux.sh --uninstall"
