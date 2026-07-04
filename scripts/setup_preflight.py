#!/usr/bin/env python3
"""Setup / Preflight for the Knowledge Iteration System.

Use this before sharing/installing the system on a new computer.
It checks the four-layer structure, optionally creates missing folders,
asks the user to pick an automation cadence, writes
`.knowledge-iteration-system.json`, and regenerates the auto system
introduction document under the Distilled layer.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from kis_config import (
    AUTOMATION_INTERVAL_CHOICES,
    automation_config,
    automation_interval_days,
    create_missing_structure,
    preflight,
    print_preflight_report,
    save_automation_settings,
    system_intro_path,
    write_default_config,
    write_system_intro,
)


PROMPT_INTRO = """
【每日蒸馏自动化】
除非你手动触发，每日蒸馏脚本会按你选的间隔在后台自动跑一次。
你希望多久自动跑一次？
  1) 每 1 天（每天）
  2) 每 2 天
  3) 每 3 天
  4) 每 4 天
  0) 暂不开启自动化（我需要时再手动跑）
"""


def ask_interval_interactive(default_choice: Optional[int]) -> Optional[int]:
    if not sys.stdin or not sys.stdin.isatty():
        return default_choice
    print(PROMPT_INTRO)
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


def parse_interval_arg(value: str) -> Optional[int]:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="知识迭代系统预检 / 初始化")
    parser.add_argument("--create-missing", action="store_true", help="创建缺失的四层/子文件夹，并写入默认配置")
    parser.add_argument("--write-config", action="store_true", help="仅写入默认 .knowledge-iteration-system.json（不覆盖已有配置）")
    parser.add_argument("--dry-run", action="store_true", help="只显示将要创建的文件夹，不实际写入")
    parser.add_argument(
        "--set-daily-interval",
        type=str,
        default=None,
        help="设置每日蒸馏自动化间隔天数（1/2/3/4 或 0/none 表示关闭），不交互直接生效",
    )
    parser.add_argument(
        "--ask-interval",
        action="store_true",
        help="强制交互式询问自动化间隔（首次运行时默认会询问）",
    )
    parser.add_argument(
        "--no-ask",
        action="store_true",
        help="即使是首次运行也不弹自动化询问（保持当前值/默认关闭）",
    )
    parser.add_argument(
        "--regen-intro",
        action="store_true",
        help="重新生成 “📚 知识迭代系统说明.md”，即使没有修改自动化配置",
    )
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

    interval_changed = False
    current_interval = automation_interval_days()
    auto_cfg = automation_config()
    ask_on_first_use = bool(auto_cfg.get("askOnFirstUse", True))

    # Priority: explicit CLI flag > interactive prompt (only when appropriate).
    if args.set_daily_interval is not None:
        new_interval = parse_interval_arg(args.set_daily_interval)
        if args.dry_run:
            print(f"\n[Dry Run] 将把每日自动化间隔设为：{new_interval or '关闭'}。")
        else:
            save_automation_settings(interval_days=new_interval, ask_on_first_use=False)
            interval_changed = True
            print(f"\n✅ 每日自动化间隔已保存：{new_interval or '关闭（手动模式）'}。")
    elif args.ask_interval or (ask_on_first_use and current_interval is None and not args.no_ask):
        picked = ask_interval_interactive(default_choice=None)
        if args.dry_run:
            print(f"\n[Dry Run] 将把每日自动化间隔设为：{picked or '关闭'}。")
        else:
            save_automation_settings(interval_days=picked, ask_on_first_use=False)
            interval_changed = True
            print(f"\n✅ 每日自动化间隔已保存：{picked or '关闭（手动模式）'}。")
            if picked is not None:
                print("👉 下一步：运行 `bash scripts/install_automation.sh` (macOS) / `.\\install_automation.ps1` (Windows) / `bash scripts/install_automation_linux.sh` (Linux) 让定时任务生效。")
    elif args.no_ask and ask_on_first_use and not args.dry_run:
        save_automation_settings(ask_on_first_use=False)

    # Rewrite the intro doc whenever we touched config, or when explicitly asked,
    # or when the intro doc is missing.
    intro_path = system_intro_path()
    should_regen = args.regen_intro or interval_changed or (not intro_path.exists())
    if should_regen and not args.dry_run:
        path = write_system_intro(overwrite=True)
        print(f"\n📚 已刷新系统说明：{path}")
    elif args.dry_run and should_regen:
        print(f"\n[Dry Run] 将刷新系统说明：{intro_path}")


if __name__ == "__main__":
    main()
