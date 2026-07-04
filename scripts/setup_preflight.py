#!/usr/bin/env python3
"""Setup / Preflight for the Knowledge Iteration System.

Use this before sharing/installing the system on a new computer.
It checks the four-layer structure, optionally creates missing folders,
asks the user whether to install per-task automation (v0.2+) with per-task
schedules, writes `.knowledge-iteration-system.json`, and regenerates the
auto system introduction document.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional, Tuple

from kis_config import (
    AUTOMATION_INTERVAL_CHOICES,
    TASK_ORDER,
    automation_config,
    automation_interval_days,
    automation_tasks,
    create_missing_structure,
    ordered_task_items,
    parse_hhmm,
    preflight,
    print_preflight_report,
    save_automation_settings,
    save_task_settings,
    system_intro_path,
    validate_task,
    write_default_config,
    write_system_intro,
)


LEGACY_INTERVAL_PROMPT = """
【每日蒸馏自动化 — 旧接口】
除非你手动触发，每日蒸馏脚本会按你选的间隔在后台自动跑一次。
你希望多久自动跑一次？
  1) 每 1 天（每天）
  2) 每 2 天
  3) 每 3 天
  4) 每 4 天
  0) 暂不开启自动化（我需要时再手动跑）
"""

DAY_OF_WEEK_LABELS = ("周日", "周一", "周二", "周三", "周四", "周五", "周六")


def _describe_task(task: Dict[str, Any]) -> str:
    sched = task.get("schedule", "?")
    hour = int(task.get("hour", 9))
    minute = int(task.get("minute", 0))
    hhmm = f"{hour:02d}:{minute:02d}"
    if sched == "daily":
        return f"每天 {hhmm}"
    if sched == "weekly":
        dow = int(task.get("dayOfWeek", 0))
        return f"每{DAY_OF_WEEK_LABELS[dow]} {hhmm}"
    if sched == "quarterly-last-day":
        return f"每季度最后一天 {hhmm}"
    return f"{sched} {hhmm}"


def print_task_table(tasks_iter=None) -> None:
    tasks_iter = tasks_iter if tasks_iter is not None else ordered_task_items()
    print("| 任务 | 触发时间 | 启用 |")
    print("|------|----------|------|")
    for key, task in tasks_iter:
        label = task.get("label", key)
        enabled = "✅" if task.get("enabled", True) else "⏸"
        print(f"| {label} | {_describe_task(task)} | {enabled} |")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    if not sys.stdin or not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw = input(f"{prompt} {suffix}: ").strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("请输入 y 或 n。")


def ask_hhmm(prompt: str, default: Tuple[int, int]) -> Tuple[int, int]:
    if not sys.stdin or not sys.stdin.isatty():
        return default
    default_str = f"{default[0]:02d}:{default[1]:02d}"
    while True:
        raw = input(f"{prompt} [默认 {default_str}]: ").strip()
        if raw == "":
            return default
        try:
            return parse_hhmm(raw)
        except ValueError as exc:
            print(f"  ⚠️ {exc}")


def ask_day_of_week(default: int) -> int:
    if not sys.stdin or not sys.stdin.isatty():
        return default
    labels = " / ".join(f"{i}={n}" for i, n in enumerate(DAY_OF_WEEK_LABELS))
    while True:
        raw = input(f"星期几？{labels} [默认 {default}={DAY_OF_WEEK_LABELS[default]}]: ").strip()
        if raw == "":
            return default
        if raw.isdigit():
            n = int(raw)
            if 0 <= n <= 6:
                return n
        print("请输入 0-6 之间的数字。")


def interactive_task_wizard() -> Optional[Dict[str, Dict[str, Any]]]:
    """Prompt user to accept defaults, edit per-task, or skip automation.

    Returns dict of per-task overrides to save, or None to skip / keep current.
    """
    if not sys.stdin or not sys.stdin.isatty():
        return None
    print()
    print("【自动化任务清单】")
    print("下列自动化任务会安装到系统调度器（macOS launchd / Linux cron / Windows Task Scheduler）：")
    print()
    print_task_table()
    print()
    print("选项：")
    print("  Y  按上表默认时间全部安装（推荐）")
    print("  e  逐项编辑（可禁用/改时间）")
    print("  n  不安装任何自动化任务")
    while True:
        raw = input("请选择 [Y/e/n]: ").strip().lower()
        if raw == "" or raw == "y":
            return {}  # accept all defaults; no per-task overrides needed
        if raw == "n":
            # disable every known task
            updates: Dict[str, Dict[str, Any]] = {}
            for key, _ in ordered_task_items():
                updates[key] = {"enabled": False}
            return updates
        if raw == "e":
            return interactive_edit_tasks()
        print("请输入 Y / e / n。")


def interactive_edit_tasks() -> Dict[str, Dict[str, Any]]:
    updates: Dict[str, Dict[str, Any]] = {}
    for key, task in ordered_task_items():
        label = task.get("label", key)
        print()
        print(f"—— {label} ({key}) ——")
        default_enabled = bool(task.get("enabled", True))
        enable = ask_yes_no("是否启用该任务？", default=default_enabled)
        patch: Dict[str, Any] = {}
        if enable != default_enabled:
            patch["enabled"] = enable
        if enable:
            hour = int(task.get("hour", 9))
            minute = int(task.get("minute", 0))
            new_hour, new_minute = ask_hhmm("触发时间 HH:MM", default=(hour, minute))
            if new_hour != hour:
                patch["hour"] = new_hour
            if new_minute != minute:
                patch["minute"] = new_minute
            if task.get("schedule") == "weekly":
                dow = int(task.get("dayOfWeek", 0))
                new_dow = ask_day_of_week(default=dow)
                if new_dow != dow:
                    patch["dayOfWeek"] = new_dow
        if patch:
            updates[key] = patch
    return updates


def parse_task_cli_flags(args: argparse.Namespace) -> Dict[str, Dict[str, Any]]:
    """Turn --enable-task / --disable-task / --set-task NAME=HH:MM / --set-task-dow into updates."""
    updates: Dict[str, Dict[str, Any]] = {}
    tasks_now = automation_tasks()

    def _touch(key: str) -> Dict[str, Any]:
        if key not in tasks_now:
            raise SystemExit(f"未知任务：{key}。可用任务：{', '.join(TASK_ORDER)}")
        updates.setdefault(key, {})
        return updates[key]

    for key in args.enable_task or []:
        _touch(key)["enabled"] = True
    for key in args.disable_task or []:
        _touch(key)["enabled"] = False
    for spec in args.set_task or []:
        if "=" not in spec:
            raise SystemExit(f"--set-task 格式无效：{spec}，需要 NAME=HH:MM")
        name, value = spec.split("=", 1)
        try:
            hh, mm = parse_hhmm(value)
        except ValueError as exc:
            raise SystemExit(f"--set-task {name}: {exc}") from exc
        patch = _touch(name)
        patch["hour"] = hh
        patch["minute"] = mm
    for spec in args.set_task_dow or []:
        if "=" not in spec:
            raise SystemExit(f"--set-task-dow 格式无效：{spec}，需要 NAME=N (0-6)")
        name, value = spec.split("=", 1)
        try:
            dow = int(value)
        except ValueError as exc:
            raise SystemExit(f"--set-task-dow {name}: 需要 0-6 的整数") from exc
        if not (0 <= dow <= 6):
            raise SystemExit(f"--set-task-dow {name}: {dow} 越界 (0-6)")
        _touch(name)["dayOfWeek"] = dow
    return updates


def apply_and_validate(updates: Dict[str, Dict[str, Any]], dry_run: bool) -> bool:
    """Apply updates (or preview them), returning True if config was touched."""
    if not updates:
        return False
    # Preview + validate against merged view
    merged_preview = {k: dict(v) for k, v in automation_tasks().items()}
    for key, patch in updates.items():
        base = dict(merged_preview.get(key, {}))
        base.update(patch)
        merged_preview[key] = base
    errors: List[str] = []
    for key, cfg in merged_preview.items():
        errors.extend(validate_task(key, cfg))
    if errors:
        print("\n❌ 任务配置无效，未保存：")
        for e in errors:
            print(f"  - {e}")
        raise SystemExit(2)

    if dry_run:
        print("\n[Dry Run] 将保存以下任务覆盖：")
        for key, patch in updates.items():
            print(f"  {key}: {patch}")
        return False
    save_task_settings(updates)
    print("\n✅ 任务配置已保存。")
    return True


def parse_legacy_interval(value: str) -> Optional[int]:
    if value.strip().lower() in {"none", "off", "manual", "no", "0"}:
        return None
    try:
        n = int(value)
    except ValueError as exc:
        raise SystemExit(f"--set-daily-interval 参数无效：{value}") from exc
    if n not in AUTOMATION_INTERVAL_CHOICES:
        raise SystemExit(
            f"--set-daily-interval 只支持 {'/'.join(str(c) for c in AUTOMATION_INTERVAL_CHOICES)} 或 0/none"
        )
    return n


def legacy_ask_interval_interactive(default_choice: Optional[int]) -> Optional[int]:
    if not sys.stdin or not sys.stdin.isatty():
        return default_choice
    print(LEGACY_INTERVAL_PROMPT)
    while True:
        raw = input("请输入编号 [默认: 2 天]: ").strip()
        if raw == "":
            return 2
        if raw == "0":
            return None
        if raw.isdigit():
            n = int(raw)
            if n in AUTOMATION_INTERVAL_CHOICES:
                return n
        print("输入无效，请输入 0/1/2/3/4。")


def main() -> None:
    parser = argparse.ArgumentParser(description="知识迭代系统预检 / 初始化")
    parser.add_argument("--create-missing", action="store_true", help="创建缺失的四层/子文件夹，并写入默认配置")
    parser.add_argument("--write-config", action="store_true", help="仅写入默认 .knowledge-iteration-system.json（不覆盖已有配置）")
    parser.add_argument("--dry-run", action="store_true", help="只显示将要创建的文件夹 / 保存的配置，不实际写入")

    # v0.2+ per-task flags
    parser.add_argument("--list-tasks", action="store_true", help="列出全部自动化任务及当前时间")
    parser.add_argument("--ask-tasks", action="store_true", help="强制进入自动化任务交互向导")
    parser.add_argument("--no-ask", action="store_true", help="即使是首次运行也不弹自动化询问（保持当前值/默认关闭）")
    parser.add_argument("--enable-task", action="append", metavar="NAME", help="启用指定任务（可多次）")
    parser.add_argument("--disable-task", action="append", metavar="NAME", help="禁用指定任务（可多次）")
    parser.add_argument("--set-task", action="append", metavar="NAME=HH:MM", help="设置任务触发时间（可多次）")
    parser.add_argument("--set-task-dow", action="append", metavar="NAME=N", help="设置每周任务的星期几 0=Sun..6=Sat（可多次）")

    # Legacy v0.1 flags (kept for backward compatibility)
    parser.add_argument("--set-daily-interval", type=str, default=None,
                        help="[legacy] 设置每日蒸馏 dailyIntervalDays（1/2/3/4 或 0/none）")
    parser.add_argument("--ask-interval", action="store_true", help="[legacy] 强制交互式询问 dailyIntervalDays")

    parser.add_argument("--regen-intro", action="store_true",
                        help="重新生成 “📚 知识迭代系统说明.md”，即使没有修改自动化配置")

    args = parser.parse_args()

    result = preflight()
    print_preflight_report(result)

    if args.write_config:
        if args.dry_run:
            print("\n[Dry Run] 将写入默认配置文件（若不存在）。")
        else:
            path = write_default_config(overwrite=False)
            print(f"\n✅ 配置文件已就绪：{path}")

    if args.create_missing:
        missing = create_missing_structure(dry_run=args.dry_run)
        if args.dry_run:
            print("\n[Dry Run] 将创建以下缺失文件夹：")
            for path in missing:
                print(f"- {path}")
        else:
            print("\n✅ 缺失文件夹已补齐：")
            for path in missing:
                print(f"- {path}")
            print("✅ 默认配置文件已就绪。")

    config_touched = False

    if args.list_tasks:
        print("\n## 自动化任务清单")
        print_task_table()
        # `--list-tasks` is informational; short-circuit further prompts.
        return

    # v0.2 per-task flags take priority over the interactive wizard.
    cli_updates = parse_task_cli_flags(args)
    if cli_updates:
        if apply_and_validate(cli_updates, dry_run=args.dry_run):
            config_touched = True

    auto_cfg = automation_config()
    ask_on_first_use = bool(auto_cfg.get("askOnFirstUse", True))
    # Consider "already asked" as: user config file exists AND user has ever explicitly
    # touched the task table or legacy interval field.
    user_has_tasks_config = isinstance(auto_cfg.get("tasks"), dict) and bool(auto_cfg.get("tasks"))
    legacy_interval_set = automation_interval_days() is not None

    should_run_wizard = args.ask_tasks or (
        ask_on_first_use
        and not user_has_tasks_config
        and not legacy_interval_set
        and not cli_updates
        and not args.no_ask
        and not args.set_daily_interval
        and not args.ask_interval
    )

    if should_run_wizard:
        picked = interactive_task_wizard()
        if picked is not None:
            if apply_and_validate(picked, dry_run=args.dry_run):
                config_touched = True
            if not args.dry_run:
                save_automation_settings(ask_on_first_use=False)
            if not args.dry_run:
                print()
                print("👉 下一步：运行下列命令让定时任务生效")
                print("   macOS  : bash scripts/install_automation.sh")
                print("   Linux  : bash scripts/install_automation_linux.sh")
                print("   Windows: .\\scripts\\install_automation.ps1")

    # -------- Legacy v0.1 interval fallback --------
    if args.set_daily_interval is not None:
        new_interval = parse_legacy_interval(args.set_daily_interval)
        if args.dry_run:
            print(f"\n[Dry Run] 将把每日自动化间隔设为：{new_interval or '关闭'}。")
        else:
            save_automation_settings(interval_days=new_interval, ask_on_first_use=False)
            config_touched = True
            print(f"\n✅ 每日自动化间隔已保存：{new_interval or '关闭（手动模式）'}。")
    elif args.ask_interval:
        picked_int = legacy_ask_interval_interactive(default_choice=None)
        if args.dry_run:
            print(f"\n[Dry Run] 将把每日自动化间隔设为：{picked_int or '关闭'}。")
        else:
            save_automation_settings(interval_days=picked_int, ask_on_first_use=False)
            config_touched = True
            print(f"\n✅ 每日自动化间隔已保存：{picked_int or '关闭（手动模式）'}。")

    # Rewrite the intro doc whenever we touched config, or when explicitly asked,
    # or when the intro doc is missing.
    intro_path = system_intro_path()
    should_regen = args.regen_intro or config_touched or (not intro_path.exists())
    if should_regen and not args.dry_run:
        path = write_system_intro(overwrite=True)
        print(f"\n📚 已刷新系统说明：{path}")
    elif args.dry_run and should_regen:
        print(f"\n[Dry Run] 将刷新系统说明：{intro_path}")


if __name__ == "__main__":
    main()
