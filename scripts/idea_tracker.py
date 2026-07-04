#!/usr/bin/env python3
"""想法成熟度追踪：用多维评分评估每个想法的推进价值。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from kis_config import iter_markdown_files, subfolder_path

IDEAS = subfolder_path("ideas")
OUTPUT = subfolder_path("ideaTracking")

MATURITY = {
    "seed": {"name": "种子想法", "emoji": "🌱"},
    "sprout": {"name": "发芽想法", "emoji": "🌿"},
    "mature": {"name": "成熟想法", "emoji": "🌳"},
    "done": {"name": "已落地", "emoji": "✅"},
}

DIMENSIONS = {
    "clarity": "清晰度",
    "actionability": "可执行性",
    "asset_value": "资产化价值",
    "business_value": "商业/增长潜力",
    "content_value": "内容/IP 潜力",
    "evidence": "证据与关联",
    "personal_energy": "个人能量",
}

THEME_RULES: Dict[str, List[str]] = {
    "女性内容 IP": ["女性", "女性主义", "中女", "小红书", "账号", "博主", "栏目", "视频", "内容"],
    "美业经营": ["美业", "客户", "资产", "运营", "复购", "私域", "风险", "投资", "门店"],
    "AI 工作流": ["ai", "agent", "codex", "claude", "prompt", "提示词", "自动化", "工作流", "工具"],
    "创意叙事": ["街头采访", "30年", "游戏", "冲突", "立场", "心智", "梦", "小猫", "蝴蝶", "爷爷", "奶奶", "故事", "创意"],
    "生活设计": ["家居", "收纳", "空间", "整理", "设计"],
}


@dataclass
class IdeaAnalysis:
    name: str
    path: Path
    level: str
    priority: str
    total: int
    scores: Dict[str, int]
    themes: List[str]
    links: List[str]
    line_count: int
    signals: List[str]
    risks: List[str]
    next_actions: List[str]
    asset_type: str


def safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def strip_frontmatter(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1 :])
    return content


def normalize(text: str) -> str:
    return text.lower().replace("｜", " ").replace("_", " ").replace("-", " ")


def count_lines(content: str) -> int:
    body = strip_frontmatter(content)
    return len([line for line in body.splitlines() if line.strip() and not line.strip().startswith("#")])


def score_by_patterns(text: str, patterns: List[str], cap: int = 5) -> int:
    score = 0
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            score += 1
    return min(score, cap)


def detect_themes(name: str, content: str) -> List[str]:
    haystack = normalize(f"{name} {content}")
    themes = []
    for theme, keywords in THEME_RULES.items():
        if any(normalize(kw) in haystack for kw in keywords):
            themes.append(theme)
    return themes


def infer_asset_type(name: str, content: str, themes: List[str]) -> str:
    text = normalize(f"{name} {content}")
    if re.search(r"系统|流程|框架|方法|步骤|模板|prompt|提示词|工作流", text):
        return "方法论 / Skill 候选"
    if re.search(r"账号|小红书|视频|栏目|采访|故事|创意", text):
        return "内容企划 / 输出选题"
    if "美业经营" in themes:
        return "商业运营框架"
    if "生活设计" in themes:
        return "设计原则 / 实用清单"
    return "想法观察"


def analyze_idea(path: Path) -> IdeaAnalysis:
    content = safe_read(path)
    body = strip_frontmatter(content)
    text = normalize(f"{path.stem} {body}")
    links = re.findall(r"\[\[(.+?)\]\]", content)
    line_count = count_lines(content)
    themes = detect_themes(path.stem, body)

    scores: Dict[str, int] = {}
    scores["clarity"] = min(5, 1 + (line_count >= 5) + (line_count >= 12) + bool(re.search(r"背景|来源|概述|目标|问题|为什么|核心概念|系统目标|功能|商业模式", body)) + bool(re.search(r"一句话|核心|方向|草案|架构", body)))
    scores["actionability"] = score_by_patterns(text, [r"下一步|行动|计划|todo|步骤|流程|每天|发布|执行|拆解|做成|尝试|记录|跟进|运营|规划|计算|匹配|搭建|更新方式|继续补充"], 5)
    scores["asset_value"] = score_by_patterns(text, [r"系统|框架|方法论|模板|skill|prompt|工作流|原则|清单|栏目|企划|引擎|体系|模型|架构|规划"], 5)
    scores["business_value"] = score_by_patterns(text, [r"商业|变现|客户|运营|增长|复购|投资|风险|账号|收入|赚钱|产品|门店|消费|客单|留存|咨询|盈利|盈亏"], 5)
    scores["content_value"] = score_by_patterns(text, [r"小红书|视频|栏目|选题|采访|故事|表达|观点|账号|发布|创意|叙事|共学|成长|反思"], 5)
    scores["evidence"] = min(5, len(links) + bool(re.search(r"案例|数据|来源|共学营|资料|clipping|链接", text)) + (line_count >= 20))
    scores["personal_energy"] = score_by_patterns(text, [r"喜欢|触动|梦|爷爷|奶奶|成长|身体|关系|反思|心智|自己|生活"], 5)

    # Strong manual-ish boosts: structured product/business ideas and repeatable content projects
    if re.search(r"系统目标|核心功能|商业模式|客户分层|运营体系|铁三角", text):
        scores["asset_value"] = min(5, scores["asset_value"] + 2)
        scores["business_value"] = min(5, scores["business_value"] + 2)
        scores["actionability"] = min(5, scores["actionability"] + 1)
    if re.search(r"更新方式|每天发|内容方向|一句话简介|气质关键词", text):
        scores["content_value"] = min(5, scores["content_value"] + 2)
        scores["actionability"] = min(5, scores["actionability"] + 1)
        scores["asset_value"] = min(5, scores["asset_value"] + 1)

    # Weighted total, max 100.
    weights = {
        "clarity": 2,
        "actionability": 3,
        "asset_value": 3,
        "business_value": 2,
        "content_value": 2,
        "evidence": 2,
        "personal_energy": 1,
    }
    raw = sum(scores[k] * weights[k] for k in scores)
    max_raw = sum(5 * w for w in weights.values())
    total = round(raw / max_raw * 100)

    has_output = bool(re.search(r"已发表|已发布|已完成|已落地|上线|发布链接|成果", text))
    if has_output:
        level = "done"
    elif total >= 72 and scores["actionability"] >= 3 and scores["asset_value"] >= 3:
        level = "mature"
    elif total >= 38 or line_count >= 10:
        level = "sprout"
    else:
        level = "seed"

    if total >= 72:
        priority = "P0 立即推进"
    elif total >= 50:
        priority = "P1 本周推进"
    elif total >= 32:
        priority = "P2 保持观察"
    else:
        priority = "P3 暂存"

    signals: List[str] = []
    if scores["business_value"] >= 3:
        signals.append("有商业/增长线索")
    if scores["content_value"] >= 3:
        signals.append("适合转成内容栏目或选题")
    if scores["asset_value"] >= 3:
        signals.append("可沉淀为方法论或 Skill")
    if scores["personal_energy"] >= 3:
        signals.append("有明显个人情绪/叙事能量")
    if scores["evidence"] >= 3:
        signals.append("已有一定资料或关联支撑")

    risks: List[str] = []
    if scores["clarity"] < 3:
        risks.append("想法边界还不清楚")
    if scores["actionability"] < 3:
        risks.append("下一步动作不够具体")
    if scores["evidence"] < 2:
        risks.append("缺少案例、资料或链接支撑")
    if scores["business_value"] >= 3 and scores["actionability"] < 3:
        risks.append("有商业潜力但缺执行路径")

    next_actions: List[str] = []
    if scores["clarity"] < 3:
        next_actions.append("补一句话定义：它解决什么问题，给谁用。")
    if scores["actionability"] < 3:
        next_actions.append("写 3 个下一步动作，最好能在 30 分钟内启动。")
    if scores["evidence"] < 3:
        next_actions.append("链接 2-3 篇相关 Clippings 或真实案例。")
    if scores["asset_value"] >= 3:
        next_actions.append("整理成框架：输入、步骤、输出、判断标准。")
    if scores["content_value"] >= 3:
        next_actions.append("拆 3 个标题/栏目样稿，验证表达方向。")
    if scores["business_value"] >= 3:
        next_actions.append("补充目标用户、价值主张和最小可验证场景。")
    if not next_actions:
        next_actions.append("保留观察，等更多材料或触发场景出现。")

    return IdeaAnalysis(
        name=path.stem,
        path=path,
        level=level,
        priority=priority,
        total=total,
        scores=scores,
        themes=themes,
        links=links,
        line_count=line_count,
        signals=signals,
        risks=risks,
        next_actions=list(dict.fromkeys(next_actions))[:5],
        asset_type=infer_asset_type(path.stem, body, themes),
    )


def score_table(scores: Dict[str, int]) -> str:
    lines = ["| 维度 | 分数 |", "|------|------|"]
    for key, label in DIMENSIONS.items():
        lines.append(f"| {label} | {scores[key]}/5 |")
    return "\n".join(lines)


def generate_report() -> tuple[Path, int]:
    ideas: List[IdeaAnalysis] = []
    if IDEAS.exists():
        for fpath in iter_markdown_files(IDEAS, recursive=False):
            ideas.append(analyze_idea(fpath))

    ideas.sort(key=lambda x: x.total, reverse=True)
    groups = {k: [] for k in MATURITY}
    for idea in ideas:
        groups[idea.level].append(idea)

    total = len(ideas)
    report: List[str] = [
        "# 🌱 想法成熟度全景报告", "",
        "> 用多维评分判断想法是否值得继续投入，而不是只看字数和链接数。", "",
        "## 📊 整体状态", "",
        "| 成熟度 | 数量 | 占比 |",
        "|--------|------|------|",
    ]
    for level, info in MATURITY.items():
        count = len(groups[level])
        pct = count / total * 100 if total else 0
        report.append(f"| {info['emoji']} {info['name']} | {count} | {pct:.1f}% |")
    report.extend(["", f"- 想法总数：**{total}** 个", ""])

    report.extend(["## 🚦 推进优先级", ""])
    if ideas:
        report.append("| 优先级 | 想法 | 总分 | 推荐资产 | 主题 |")
        report.append("|--------|------|------|----------|------|")
        for idea in ideas:
            report.append(f"| {idea.priority} | [[{idea.name}]] | {idea.total}/100 | {idea.asset_type} | {', '.join(idea.themes) or '-'} |")
    else:
        report.append("暂无想法。")
    report.append("")

    for level, info in MATURITY.items():
        level_ideas = groups[level]
        if not level_ideas:
            continue
        report.append(f"## {info['emoji']} {info['name']}")
        report.append("")
        for idea in level_ideas:
            report.append(f"### [[{idea.name}]] — {idea.total}/100 · {idea.priority}")
            report.append("")
            report.append(f"- 推荐资产：{idea.asset_type}")
            report.append(f"- 主题：{', '.join(idea.themes) if idea.themes else '未形成明确主题'}")
            report.append(f"- 有效内容行数：{idea.line_count}")
            report.append(f"- 关联链接数：{len(idea.links)}")
            if idea.signals:
                report.append(f"- 亮点信号：{'；'.join(idea.signals)}")
            if idea.risks:
                report.append(f"- 风险/缺口：{'；'.join(idea.risks)}")
            report.append("")
            report.append(score_table(idea.scores))
            report.append("")
            report.append("**下一步动作：**")
            for action in idea.next_actions:
                report.append(f"- [ ] {action}")
            report.append("")

    report.extend(["## 💡 本周行动建议", ""])
    p0 = [idea for idea in ideas if idea.priority.startswith("P0")]
    p1 = [idea for idea in ideas if idea.priority.startswith("P1")]
    if p0:
        report.append("### 立即推进")
        for idea in p0[:3]:
            report.append(f"- [[{idea.name}]]：{idea.next_actions[0]}")
        report.append("")
    if p1:
        report.append("### 本周推进")
        for idea in p1[:5]:
            report.append(f"- [[{idea.name}]]：{idea.next_actions[0]}")
        report.append("")
    if not p0 and not p1:
        report.append("- 暂无必须立即推进的想法；建议先补充高潜力想法的背景和案例。")
    report.append(f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT / "想法成熟度全景.md"
    output_file.write_text("\n".join(report), encoding="utf-8")
    return output_file, total


if __name__ == "__main__":
    print("=" * 40)
    print("🌱 想法成熟度追踪")
    print("=" * 40)
    output, total = generate_report()
    print(f"✅ 报告已生成，分析了 {total} 个想法")
    print(f"   位置：{output}")
