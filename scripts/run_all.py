#!/usr/bin/env python3
"""跨平台知识蒸馏系统总入口。

替代 run_all.sh，支持 macOS / Windows / Linux。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from kis_config import CONFIG_PATH, VAULT, layer_path, preflight, print_preflight_report

SCRIPT_DIR = Path(__file__).resolve().parent

SCRIPTS = [
    ("daily_distill.py", "每日知识蒸馏", lambda args: ["--days", str(args.days)]),
    ("weekly_review.py", "每周知识复盘", lambda args: []),
    ("idea_tracker.py", "想法成熟度追踪", lambda args: []),
    ("clipping_refiner.py", "Clippings 内容提炼", lambda args: []),
    ("skill_detector.py", "Skill 自动沉淀检测", lambda args: ["--llm=auto"]),
    ("link_suggester.py", "结构性链接建议", lambda args: []),
    ("skill_upgrader.py", "Skill 升级路线图", lambda args: []),
    ("feedback_loop.py", "输出内容回流闭环", lambda args: []),
    ("quarterly_audit.py", "知识资产季度审计", lambda args: []),
]

SCRIPT_ALIASES = {
    "preflight": "setup_preflight.py",
    "setup": "setup_preflight.py",
    "daily": "daily_distill.py",
    "weekly": "weekly_review.py",
    "idea": "idea_tracker.py",
    "clipping": "clipping_refiner.py",
    "skill": "skill_detector.py",
    "link": "link_suggester.py",
    "links": "link_suggester.py",
    "suggester": "link_suggester.py",
    "upgrader": "skill_upgrader.py",
    "upgrade": "skill_upgrader.py",
    "feedback": "feedback_loop.py",
    "quarterly": "quarterly_audit.py",
    "audit": "quarterly_audit.py",
}


def script_extra_args(script_name: str, args: argparse.Namespace) -> list[str]:
    if script_name == "daily_distill.py":
        return ["--days", str(args.days)]
    if script_name == "setup_preflight.py" and args.create_missing:
        return ["--create-missing"]
    return []


def run_script(script_name: str, extra_args: list[str] | None = None) -> bool:
    script_path = SCRIPT_DIR / script_name
    if not script_path.exists():
        print(f"ERROR: 脚本不存在: {script_path}")
        return False

    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)

    print(f"\n{'=' * 50}", flush=True)
    print(f"  运行: {' '.join(cmd)}", flush=True)
    print(f"{'=' * 50}\n", flush=True)
    result = subprocess.run(cmd, cwd=str(VAULT), check=False)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="知识蒸馏系统跨平台总入口")
    parser.add_argument("--dry-run", action="store_true", help="仅展示将要运行的脚本，不实际执行")
    parser.add_argument("--preflight", action="store_true", help="先展示四层结构预检报告")
    parser.add_argument("--create-missing", action="store_true", help="配合 --only preflight/setup 创建缺失目录")
    parser.add_argument("--only", type=str, choices=list(SCRIPT_ALIASES.keys()), help="仅运行指定工作流")
    parser.add_argument("--days", type=int, default=2, help="每日蒸馏扫描天数 (默认: 2)")
    args = parser.parse_args()

    print("=" * 50, flush=True)
    print("  知识蒸馏系统 - 跨平台运行器", flush=True)
    print(f"  Vault: {VAULT}", flush=True)
    print(f"  Config: {CONFIG_PATH if CONFIG_PATH.exists() else '未找到，使用默认四层结构'}", flush=True)
    print("=" * 50, flush=True)

    result = preflight()
    if args.preflight:
        print()
        print_preflight_report(result)
    elif args.dry_run:
        # dry-run 不开 --preflight 时，至少告知预检概要，避免“静默聊天”。
        problems = []
        if not result.config_exists:
            problems.append("未找到 .knowledge-iteration-system.json")
        if result.state != "完整标准结构":
            problems.append(f"四层结构状态：{result.state}")
        if result.missing_paths:
            problems.append(f"缺失 {len(result.missing_paths)} 个子目录")
        if problems:
            print("\n⚠️  预检提醒（dry-run）：")
            for p in problems:
                print(f"   - {p}")
            print("   建议加 --preflight 查看完整报告，或先跑 setup_preflight.py --create-missing --dry-run。")
        else:
            print("\n✅ 预检通过：四层结构完整、配置已就位。")

    if args.only:
        script_name = SCRIPT_ALIASES[args.only]
        extra = script_extra_args(script_name, args)
        if args.dry_run:
            print(f"\n[Dry Run] 将运行: {sys.executable} {SCRIPT_DIR / script_name} {' '.join(extra)}")
        else:
            run_script(script_name, extra)
        return

    if args.dry_run:
        print("\n[Dry Run] 将按以下顺序运行:")
        for i, (script, name, extra_factory) in enumerate(SCRIPTS, 1):
            extra = extra_factory(args)
            print(f"  {i}/{len(SCRIPTS)} {name}: {sys.executable} {SCRIPT_DIR / script} {' '.join(extra)}")
        print("\n预计输出：")
        print(f"- 报告位置: {layer_path('distilled')}")
        print(f"- Skill 候选: {layer_path('skills') / '待整理'}")
        return

    for i, (script, name, extra_factory) in enumerate(SCRIPTS, 1):
        print(f"\n[{i}/{len(SCRIPTS)}] {name}...", flush=True)
        if not run_script(script, extra_factory(args)):
            print(f"WARNING: {script} 运行出错，继续下一个...", flush=True)

    print("\n" + "=" * 50, flush=True)
    print(f"  全部 {len(SCRIPTS)} 大任务完成！", flush=True)
    print("=" * 50, flush=True)
    print(f"\n报告位置: {layer_path('distilled')}", flush=True)
    print(f"Skill 候选: {layer_path('skills') / '待整理'}", flush=True)



if __name__ == "__main__":
    main()
