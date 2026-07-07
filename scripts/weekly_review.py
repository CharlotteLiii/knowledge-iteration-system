#!/usr/bin/env python3
"""每周知识复盘：汇总近7天输入，生成可读的“人工解读版”周报。

目标不是做粗糙词频榜，而是输出更接近人工复盘的结构：
- 基础数据概览
- 本周主题归纳
- 值得继续推进的想法
- Clippings 方向判断
- 下周建议深入方向

实现仍保持本地、可分享、跨平台：不调用外部模型，不写死用户路径。
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from kis_config import iter_markdown_files, is_stopword, subfolder_path
import kis_state

TASK_KEY = "weekly_review"

INPUT_IDEAS = subfolder_path("ideas")
INPUT_CLIPPINGS = subfolder_path("clippings")
OUTPUT = subfolder_path("weeklyReview")

# 领域专用噪声。语法功能词已由 kis_config.STOPWORDS 处理。
EXTRA_NOISE = {
    "iframe", "bilibili", "player", "frameborder", "allowfullscreen", "transcript",
    "description", "src", "href", "img", "png", "jpg", "jpeg", "gif",
    "xhs", "xiaohongshu", "webshare", "xsec", "token", "discovery", "item", "pc_web",
    "douyin", "weixin", "weibo", "asr",
}

THEME_RULES: Dict[str, Dict[str, object]] = {
    "AI 工具化工作流": {
        "keywords": ["ai", "agent", "codex", "claude", "gpt", "github", "编程agent", "自动化", "工作流", "prompt", "cli", "harness engineering", "obsidian", "智能体"],
        "why": "本周多次出现 AI 工具、编程 Agent、自动化协作和效率工具，适合沉淀成可复用工作流。",
        "action": "把高频 AI 工具内容整理成一张“AI 工作流卡片”，明确场景、输入、步骤、输出和适用边界。",
    },
    "女性内容 IP 与商业化": {
        "keywords": ["女性", "女性主义", "中女", "博主", "ip", "变现", "阅读赚钱", "书籍合作", "女性博主", "内容商业化"],
        "why": "女性议题、内容表达和商业化线索同时出现，说明它不只是选题，而可能是账号定位/产品方向。",
        "action": "拆解 3-5 个栏目方向：身份叙事、观点表达、商业案例、个人成长、方法论输出。",
    },
    "美业经营与客户资产": {
        "keywords": ["美业", "客户资产", "美业客户", "美业投资", "风险管控", "门店", "复购", "私域", "客户运营"],
        "why": "美业相关想法已经从灵感进入系统性经营问题，具备方法论和商业化潜力。",
        "action": "优先推进“美业客户资产运营系统”，整理成框架：客户分层、触达节奏、复购机制、风险指标。",
    },
    "远程工作与 AI 职业机会": {
        "keywords": ["remote", "远程", "求职", "面试", "ai公司", "职业", "打工人", "可remote", "platform", "女生可remote"],
        "why": "远程、AI 公司、职业出路等内容集中出现，适合形成机会雷达和行动清单。",
        "action": "建立一个“AI/remote 机会清单”：公司、岗位、要求、投递入口、可复用简历素材。",
    },
    "创意表达与长期叙事": {
        "keywords": ["街头采访", "30年后的世界", "游戏灵感", "冲突", "立场", "心智", "梦", "小猫", "蝴蝶", "爷爷", "奶奶", "故事", "创意"],
        "why": "本周有不少偏叙事、情绪和创意实验的输入，适合转化为内容栏目或视觉企划。",
        "action": "挑一个最有画面感的想法做成小企划：一句话概念、受众、呈现形式、3 个样稿标题。",
    },
    "生活空间与秩序感": {
        "keywords": ["家居", "收纳", "一体式收纳", "生活空间", "房间整理"],
        "why": "生活空间类内容虽不一定最多，但适合沉淀成设计原则或实用内容。",
        "action": "把收纳建议整理成“问题-原则-方案-注意事项”的设计卡片。",
    },
}


def _build_entry(fpath: Path) -> Dict[str, object]:
    mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
    category = "想法" if INPUT_IDEAS in fpath.parents or fpath.parent == INPUT_IDEAS else "Clippings"
    return {
        "path": fpath,
        "name": fpath.stem,
        "mtime": mtime,
        "category": category,
        "text": safe_read(fpath),
    }


def scan_all_files(days_back: int = 7) -> List[Dict[str, object]]:
    """时间窗模式：扫描最近 days_back 天（手动覆盖用）。"""
    cutoff = datetime.now() - timedelta(days=days_back)
    files: List[Dict[str, object]] = []
    for base in [INPUT_IDEAS, INPUT_CLIPPINGS]:
        if not base.exists():
            continue
        for fpath in iter_markdown_files(base):
            mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
            if mtime < cutoff:
                continue
            files.append(_build_entry(fpath))
    return sorted(files, key=lambda x: x["mtime"], reverse=True)


def scan_incremental_files() -> Tuple[List[Dict[str, object]], "kis_state.IncrementalScan"]:
    """Checkpoint 模式（默认）：自上次周报以来的新增/变化。独立于日报 checkpoint。"""
    scan = kis_state.scan_incremental(TASK_KEY, [INPUT_IDEAS, INPUT_CLIPPINGS], recursive=True)
    files = [_build_entry(p) for p in scan.files if p.exists()]
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return files, scan


def safe_read(path: Path, max_chars: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""


def normalize_text(value: str) -> str:
    return value.lower().replace("｜", " ").replace("_", " ").replace("-", " ")


def extract_keywords(files: Iterable[Dict[str, object]], limit: int = 20) -> List[Tuple[str, int]]:
    counter: Counter[str] = Counter()
    for item in files:
        text = normalize_text(f"{item['name']} {item.get('text', '')}")
        # Chinese terms, English product/tool names, short mixed tokens.
        tokens = re.findall(r"[\u4e00-\u9fa5]{2,6}|[A-Za-z][A-Za-z0-9+.#/-]{1,24}", text)
        for token in tokens:
            token_norm = token.lower().strip("-_/#.。！？!?,，：:；;（）()[]【】《》<>\"'")
            if is_stopword(token_norm) or token_norm in EXTRA_NOISE:
                continue
            counter[token_norm] += 1
    return counter.most_common(limit)


def theme_score(item: Dict[str, object], keywords: List[str]) -> int:
    haystack = normalize_text(f"{item['name']} {item.get('text', '')}")
    score = 0
    for kw in keywords:
        kw_norm = normalize_text(kw)
        if kw_norm in haystack:
            # 标题命中更重要。
            score += 3 if kw_norm in normalize_text(str(item["name"])) else 1
    return score


def classify_themes(files: List[Dict[str, object]]) -> List[Dict[str, object]]:
    themes: List[Dict[str, object]] = []
    for theme, meta in THEME_RULES.items():
        keywords = list(meta["keywords"])  # type: ignore[index]
        matched = []
        total_score = 0
        for item in files:
            score = theme_score(item, keywords)
            if score > 0:
                matched.append((score, item))
                total_score += score
        matched.sort(key=lambda pair: (pair[0], pair[1]["mtime"]), reverse=True)  # type: ignore[index]
        if matched:
            themes.append({
                "name": theme,
                "score": total_score,
                "count": len(matched),
                "examples": [item for _, item in matched[:5]],
                "why": meta["why"],
                "action": meta["action"],
            })
    return sorted(themes, key=lambda x: (x["score"], x["count"]), reverse=True)


def pick_promising_ideas(thoughts: List[Dict[str, object]], themes: List[Dict[str, object]], limit: int = 5) -> List[Tuple[Dict[str, object], str]]:
    theme_names = [str(t["name"]) for t in themes]
    picks = []
    for item in thoughts:
        matched_themes = []
        for theme_name, meta in THEME_RULES.items():
            if theme_score(item, list(meta["keywords"])) > 0:  # type: ignore[index]
                matched_themes.append(theme_name)
        if matched_themes:
            reason = f"关联主题：{' / '.join(matched_themes[:2])}"
        else:
            reason = "独立灵感，适合先保留观察"
        # 更偏商业化/方法论/内容栏目者优先。
        priority = 0
        name = normalize_text(str(item["name"]))
        for word in ["系统", "运营", "风险", "账号", "创意", "方法", "商业", "客户", "ai"]:
            if word in name:
                priority += 1
        picks.append((priority, item, reason))
    picks.sort(key=lambda x: (x[0], x[1]["mtime"]), reverse=True)  # type: ignore[index]
    return [(item, reason) for _, item, reason in picks[:limit]]


def clipping_direction_summary(clippings: List[Dict[str, object]], themes: List[Dict[str, object]]) -> List[str]:
    lines = []
    for theme in themes[:5]:
        examples = [e for e in theme["examples"] if e["category"] == "Clippings"]  # type: ignore[index]
        if not examples:
            continue
        example_names = "、".join(f"[[{e['name']}]]" for e in examples[:3])
        lines.append(f"- **{theme['name']}**：{theme['why']} 代表内容：{example_names}")
    if not lines and clippings:
        lines.append("- 本周 Clippings 较分散，建议先做去噪和主题归并，再决定是否沉淀为概念卡/工作流。")
    return lines


def build_human_interpretation(files: List[Dict[str, object]], thoughts: List[Dict[str, object]], clippings: List[Dict[str, object]], themes: List[Dict[str, object]]) -> List[str]:
    if not files:
        return ["本周没有扫描到新增输入。建议下周先保证 Inbox 捕获，再谈蒸馏。"]

    top_theme_names = [str(t["name"]) for t in themes[:3]]
    if top_theme_names:
        core = " + ".join(top_theme_names)
        return [
            f"这周的知识输入主线不是散的，核心更像是：**{core}**。",
            "脚本已过滤掉网页采集字段、时间字段、互动字段等噪音词；下面的方向更偏“可行动主题”，不是单纯词频。",
        ]
    return [
        "这周输入量不低，但主题尚未形成明显聚类。建议先做一次 Clippings 去重和想法成熟度评估。",
    ]


def generate_weekly_report(files: List[Dict[str, object]]) -> Tuple[Path, int]:
    thoughts = [f for f in files if f["category"] == "想法"]
    clippings = [f for f in files if f["category"] == "Clippings"]
    keywords = extract_keywords(files)
    themes = classify_themes(files)
    promising_ideas = pick_promising_ideas(thoughts, themes)
    week_num = datetime.now().isocalendar()[1]

    report: List[str] = [
        f"# 📊 每周知识复盘 - 第 {week_num} 周",
        "",
        "> 汇总本周新知识，识别真实主题，规划下周可执行方向。",
        "",
        "## 📈 本周数据概览",
        "",
        "| 指标 | 数量 |",
        "|------|------|",
        f"| 新增笔记总数 | {len(files)} |",
        f"| 新增想法 | {len(thoughts)} |",
        f"| 新增 Clippings | {len(clippings)} |",
        "",
        "## 🧠 AI 二次解读",
        "",
    ]
    report.extend(build_human_interpretation(files, thoughts, clippings, themes))
    report.append("")

    report.extend(["## 🔥 本周真实主题", ""])
    if themes:
        for i, theme in enumerate(themes[:6], 1):
            examples = "、".join(f"[[{e['name']}]]" for e in theme["examples"][:3])  # type: ignore[index]
            report.extend([
                f"### {i}. {theme['name']}",
                "",
                f"- 命中内容：{theme['count']} 条",
                f"- 判断：{theme['why']}",
                f"- 代表笔记：{examples}",
                "",
            ])
    else:
        report.append("本周没有形成足够明确的主题聚类。")
        report.append("")

    report.extend(["## 💡 值得继续推进的想法", ""])
    if promising_ideas:
        for item, reason in promising_ideas:
            report.append(f"- [[{item['name']}]] — {reason}")
    else:
        report.append("本周没有新增想法，或新增想法暂未显示明显推进价值。")
    report.append("")

    report.extend(["## 📑 本周 Clippings 方向判断", ""])
    summary_lines = clipping_direction_summary(clippings, themes)
    report.extend(summary_lines)
    if clippings:
        report.append("")
        report.append("### 本周 Clippings 清单")
        report.append("")
        for c in clippings[:12]:
            report.append(f"- [[{c['name']}]]")
        if len(clippings) > 12:
            report.append(f"- ... 还有 {len(clippings) - 12} 篇")
    report.append("")

    report.extend(["## 🎯 下周建议深入方向", ""])
    if themes:
        for theme in themes[:3]:
            report.append(f"- **{theme['name']}**：{theme['action']}")
    else:
        report.extend([
            "- **先做去噪**：清理重复 Clippings 和低价值网页残留字段。",
            "- **先跑想法追踪**：判断哪些想法值得继续推进。",
            "- **先补输入上下文**：给关键想法补充来源、为什么重要、下一步动作。",
        ])
    report.append("")

    report.extend(["## 🧹 自动关键词参考（已过滤噪音）", ""])
    if keywords:
        report.append("这些词只作为辅助参考，不直接等同于下周方向：")
        report.append("")
        report.append("、".join(f"{kw}({count})" for kw, count in keywords[:15]))
    else:
        report.append("暂无有效关键词。")
    report.append("")

    report.extend(["## 🗂 本周新增想法清单", ""])
    for t in thoughts:
        report.append(f"- [[{t['name']}]]")
    if not thoughts:
        report.append("无")
    report.append("")
    report.append(f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT / f"{datetime.now().strftime('%Y-%m-%d')}_每周复盘.md"
    output_file.write_text("\n".join(report), encoding="utf-8")
    return output_file, len(files)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="每周知识复盘")
    parser.add_argument("--days", type=int, help="手动覆盖：扫描最近 N 天（不读写 checkpoint）")
    parser.add_argument("--since", type=str, help="手动覆盖：扫描自指定日期起（YYYY-MM-DD，不读写 checkpoint）")
    parser.add_argument("--reset-checkpoint", action="store_true", help="清除本任务 checkpoint 后退出。")
    args = parser.parse_args()

    print("=" * 40)
    print("📊 每周知识复盘")
    print("=" * 40)

    if args.reset_checkpoint:
        removed = kis_state.reset_task(TASK_KEY)
        print(f"{'✅ 已清除' if removed else 'ℹ️ 无'} checkpoint（任务：{TASK_KEY}）")
        return

    scan = None
    if args.since:
        try:
            since_dt = datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            print(f"⚠️ --since 日期格式错误（需 YYYY-MM-DD）：{args.since}")
            return
        cutoff_days = max(1, (datetime.now() - since_dt).days + 1)
        print(f"📂 [手动] 扫描 {args.since} 起新增内容（不更新 checkpoint）...")
        files = scan_all_files(cutoff_days)
    elif args.days is not None:
        print(f"📂 [手动] 扫描最近 {args.days} 天（不更新 checkpoint）...")
        files = scan_all_files(args.days)
    else:
        files, scan = scan_incremental_files()
        if scan.last_run_at:
            print(f"📂 [增量] 自上次复盘（{scan.last_run_at}）以来新增/变化的内容...")
        else:
            print("📂 [增量] 首次复盘，把当前输入层全部视为新增...")

    output, count = generate_weekly_report(files)
    print(f"✅ 报告已生成，扫描了 {count} 篇笔记")
    print(f"   位置：{output}")

    if scan is not None:
        kis_state.commit_scan(TASK_KEY, scan)


if __name__ == "__main__":
    main()
