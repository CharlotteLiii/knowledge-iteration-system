#!/bin/bash
# 知识蒸馏自动化安装脚本（macOS LaunchAgents，v0.2+ per-task 版本）
#
# 从 .knowledge-iteration-system.json 的 automation.tasks 表读取每个任务的
# schedule / hour / minute / dayOfWeek，为每个启用的任务生成一个独立的
# LaunchAgent（com.knowledge-iteration.<task_key>.plist）。
#
# 支持的 schedule 值：
#   - daily              → StartCalendarInterval Hour+Minute
#   - weekly             → StartCalendarInterval Weekday+Hour+Minute (0=Sun..6=Sat)
#   - quarterly-last-day → StartCalendarInterval array 覆盖 3/31 6/30 9/30 12/31 的 Hour+Minute
#
# 用法：
#   bash scripts/install_automation.sh --dry-run
#   bash scripts/install_automation.sh
#   bash scripts/install_automation.sh --uninstall
#
# 迁移：会在安装时自动 bootout 老命名 (com.karpathy.knowledge.distiller,
# com.knowledge-iteration.distiller) 的旧 LaunchAgent，防止新旧同时运行。
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
UID_NUM="$(id -u)"
LA_DIR="$HOME/Library/LaunchAgents"
LABEL_PREFIX="com.knowledge-iteration"

# 老命名（需要在新安装时清理）
LEGACY_LABELS=(
  "com.karpathy.knowledge.distiller"
  "com.knowledge-iteration.distiller"   # v0.1 的单任务命名
)

# ---------- Python 探测（沿用 v0.1.1 修复逻辑）----------
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

echo "🔬 知识蒸馏自动化安装脚本（macOS · per-task v0.2+）"
echo "======================================================"
echo "Vault:   $VAULT"
echo "Python:  $PYTHON_BIN"
echo "Plist目录: $LA_DIR"
echo ""

# ---------- 清理老命名的 LaunchAgent ----------
cleanup_legacy() {
  for legacy in "${LEGACY_LABELS[@]}"; do
    local plist="$LA_DIR/${legacy}.plist"
    if [ -f "$plist" ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        echo "[Dry Run] 将清理老 LaunchAgent: $legacy"
      else
        launchctl bootout "gui/${UID_NUM}" "$plist" >/dev/null 2>&1 || true
        rm -f "$plist"
        echo "🔄 已清理老 LaunchAgent: $legacy"
      fi
    fi
  done
}

# ---------- Uninstall 分支 ----------
if [ "$UNINSTALL" -eq 1 ]; then
  echo "将卸载所有 ${LABEL_PREFIX}.* LaunchAgent。"
  if [ "$DRY_RUN" -eq 1 ]; then
    for plist in "$LA_DIR"/${LABEL_PREFIX}.*.plist; do
      [ -e "$plist" ] || continue
      echo "[Dry Run] launchctl bootout gui/$UID_NUM $plist && rm -f $plist"
    done
    cleanup_legacy
    exit 0
  fi
  for plist in "$LA_DIR"/${LABEL_PREFIX}.*.plist; do
    [ -e "$plist" ] || continue
    launchctl bootout "gui/$UID_NUM" "$plist" >/dev/null 2>&1 || true
    rm -f "$plist"
    echo "✅ 已卸载: $(basename "$plist")"
  done
  cleanup_legacy
  echo "✅ 卸载完成"
  exit 0
fi

# ---------- 读取任务表 ----------
# 输出格式：每行一个任务，字段用 tab 分隔：
#   key <TAB> schedule <TAB> hour <TAB> minute <TAB> dayOfWeek <TAB> script <TAB> args_shellquoted
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
    print("ERR", file=sys.stderr)
    for e in errs:
        print(e, file=sys.stderr)
    sys.exit(3)
print("\n".join(rows))
PY
)"

if [ -z "${TASKS_TSV// /}" ]; then
  echo "⚠️ 没有启用的自动化任务。"
  echo "   先跑：python3 scripts/setup_preflight.py --ask-tasks"
  echo "   或者手动 enable: python3 scripts/setup_preflight.py --enable-task daily_distill"
  cleanup_legacy
  exit 0
fi

TASK_COUNT="$(printf '%s\n' "$TASKS_TSV" | grep -c . || true)"
echo "读取到 ${TASK_COUNT} 个启用的自动化任务。"
echo ""

# ---------- 生成单个 plist 的模板 ----------
# 参数：$1 plist_out_path, $2 label, $3 schedule, $4 hour, $5 minute, $6 dayOfWeek, $7 script, $8 args_shellquoted
generate_plist() {
  local out="$1" label="$2" sched="$3" hh="$4" mm="$5" dow="$6" script="$7" args_str="$8"
  local script_path="$VAULT/scripts/$script"
  local stdout_log="$VAULT/scripts/logs/${label}.log"
  local stderr_log="$VAULT/scripts/logs/${label}.error.log"

  # 构造 ProgramArguments <array>
  local prog_args=""
  prog_args+=$'\n'"        <string>$PYTHON_BIN</string>"
  prog_args+=$'\n'"        <string>$script_path</string>"
  if [ -n "$args_str" ]; then
    # args_str 已经 shell-quoted，用 eval 拆回原始 argv
    # shellcheck disable=SC2086
    eval "set -- $args_str"
    for arg in "$@"; do
      # XML escape 最小集合
      local esc="${arg//&/&amp;}"
      esc="${esc//</&lt;}"
      esc="${esc//>/&gt;}"
      prog_args+=$'\n'"        <string>$esc</string>"
    done
  fi

  # 构造调度块 <key>StartCalendarInterval</key> ...
  local sched_block=""
  case "$sched" in
    daily)
      sched_block="    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>$hh</integer>
        <key>Minute</key><integer>$mm</integer>
    </dict>"
      ;;
    weekly)
      sched_block="    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key><integer>$dow</integer>
        <key>Hour</key><integer>$hh</integer>
        <key>Minute</key><integer>$mm</integer>
    </dict>"
      ;;
    quarterly-last-day)
      # 3/31 6/30 9/30 12/31
      sched_block="    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Month</key><integer>3</integer>
            <key>Day</key><integer>31</integer>
            <key>Hour</key><integer>$hh</integer>
            <key>Minute</key><integer>$mm</integer>
        </dict>
        <dict>
            <key>Month</key><integer>6</integer>
            <key>Day</key><integer>30</integer>
            <key>Hour</key><integer>$hh</integer>
            <key>Minute</key><integer>$mm</integer>
        </dict>
        <dict>
            <key>Month</key><integer>9</integer>
            <key>Day</key><integer>30</integer>
            <key>Hour</key><integer>$hh</integer>
            <key>Minute</key><integer>$mm</integer>
        </dict>
        <dict>
            <key>Month</key><integer>12</integer>
            <key>Day</key><integer>31</integer>
            <key>Hour</key><integer>$hh</integer>
            <key>Minute</key><integer>$mm</integer>
        </dict>
    </array>"
      ;;
    *)
      echo "❌ 未知 schedule: $sched" >&2
      return 1
      ;;
  esac

  cat >"$out" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$label</string>
    <key>ProgramArguments</key>
    <array>$prog_args
    </array>
    <key>WorkingDirectory</key>
    <string>$VAULT</string>
$sched_block
    <key>StandardOutPath</key>
    <string>$stdout_log</string>
    <key>StandardErrorPath</key>
    <string>$stderr_log</string>
</dict>
</plist>
PL
}

# ---------- 循环生成 & bootstrap ----------
mkdir -p "$VAULT/scripts/logs"

echo "=== 计划安装的任务 ==="
printf '%s\n' "$TASKS_TSV" | while IFS=$'\t' read -r KEY SCHED HH MM DOW SCRIPT ARGS; do
  [ -z "$KEY" ] && continue
  LABEL="${LABEL_PREFIX}.${KEY}"
  case "$SCHED" in
    daily) sched_desc="每天 $(printf '%02d:%02d' "$HH" "$MM")";;
    weekly) sched_desc="每周 (dow=$DOW) $(printf '%02d:%02d' "$HH" "$MM")";;
    quarterly-last-day) sched_desc="季度最后一天 $(printf '%02d:%02d' "$HH" "$MM")";;
    *) sched_desc="$SCHED $HH:$MM";;
  esac
  echo "  - $LABEL   $sched_desc   → $SCRIPT $ARGS"
done
echo ""

if [ "$DRY_RUN" -eq 1 ]; then
  echo "=== [Dry Run] 预览首个任务的 plist ==="
  first_line="$(printf '%s\n' "$TASKS_TSV" | head -n 1)"
  IFS=$'\t' read -r KEY SCHED HH MM DOW SCRIPT ARGS <<< "$first_line"
  TMP_PLIST="$(mktemp)"
  generate_plist "$TMP_PLIST" "${LABEL_PREFIX}.${KEY}" "$SCHED" "$HH" "$MM" "$DOW" "$SCRIPT" "$ARGS"
  echo "----- ${LABEL_PREFIX}.${KEY}.plist -----"
  cat "$TMP_PLIST"
  echo "----- 预览结束 -----"
  rm -f "$TMP_PLIST"
  echo ""
  echo "实际安装请去掉 --dry-run。"
  exit 0
fi

mkdir -p "$LA_DIR"
cleanup_legacy

# 先卸载所有旧的同前缀 LaunchAgent，避免残留
for old_plist in "$LA_DIR"/${LABEL_PREFIX}.*.plist; do
  [ -e "$old_plist" ] || continue
  launchctl bootout "gui/$UID_NUM" "$old_plist" >/dev/null 2>&1 || true
  rm -f "$old_plist"
done

INSTALLED=0
while IFS=$'\t' read -r KEY SCHED HH MM DOW SCRIPT ARGS; do
  [ -z "$KEY" ] && continue
  LABEL="${LABEL_PREFIX}.${KEY}"
  PLIST_DST="$LA_DIR/${LABEL}.plist"
  generate_plist "$PLIST_DST" "$LABEL" "$SCHED" "$HH" "$MM" "$DOW" "$SCRIPT" "$ARGS"
  launchctl bootstrap "gui/$UID_NUM" "$PLIST_DST"
  INSTALLED=$((INSTALLED + 1))
  echo "✅ 安装并加载: $LABEL"
done <<< "$TASKS_TSV"

echo ""
echo "✅ 完成，共安装 $INSTALLED 个 LaunchAgent。"
echo ""
echo "常用命令："
echo "  查看所有任务：launchctl list | grep '${LABEL_PREFIX}\\.'"
echo "  立即触发某任务：launchctl kickstart -k gui/$UID_NUM/${LABEL_PREFIX}.<task_key>"
echo "  查看日志：ls \"$VAULT/scripts/logs/\""
echo "  卸载全部：bash scripts/install_automation.sh --uninstall"
