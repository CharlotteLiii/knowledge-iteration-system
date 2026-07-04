#!/usr/bin/env python3
"""结构性链接建议：把高价值 Clippings 与想法织成知识网络。

默认只生成带复选框的建议报告；用户在 Obsidian 中勾选后，才可用
--apply-approved 把已勾选链接写回源文件的「相关链接」章节。
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from kis_config import iter_markdown_files, layer_path, subfolder_path

try:
    from clipping_refiner import analyze_file as analyze_clipping
except Exception:  # pragma: no cover - fallback for standalone environments
    analyze_clipping = None

IDEAS = subfolder_path("ideas")
CLIPPINGS = subfolder_path("clippings")
CLIPPING_REFINE = subfolder_path("clippingRefine")
SKILLS = layer_path("skills")
DISTILLED = layer_path("distilled")
OUTPUT = subfolder_path("linkSuggestions")
DEFAULT_REPORT = OUTPUT / "结构性链接建议.md"
APPROVED_START = "<!-- KIS_APPROVED_LINKS_START -->"
APPROVED_END = "<!-- KIS_APPROVED_LINKS_END -->"

STOPWORDS = {
    "一个", "一种", "这个", "那个", "如何", "怎么", "什么", "为什么", "进行", "可以", "需要", "建议",
    "内容", "方法", "工具", "系统", "自动", "生成", "使用", "教程", "指南", "完整", "全网", "最全",
    "2026", "06", "07", "ai", "AI", "的", "了", "和", "与", "在", "是", "有", "为", "到",
}

THEME_KEYWORDS: Dict[str, List[str]] = {
    "AI 工作流": ["ai", "agent", "codex", "claude", "prompt", "提示词", "自动化", "工作流", "obsidian", "harness"],
    "知识管理": ["知识库", "obsidian", "笔记", "卡片", "蒸馏", "知识管理", "skill"],
    "内容/IP": ["小红书", "账号", "内容", "选题", "视频", "脚本", "栏目", "博主", "变现", "阅读赚钱"],
    "职业机会": ["remote", "远程", "面试", "岗位", "职业", "求职", "公司", "学习路径"],
    "商业投研": ["投资", "美股", "财经", "投研", "商业", "客户", "运营", "增长", "风险", "日报"],
    "创意表达": ["创意", "故事", "表达", "拍摄", "编导", "短视频", "vlog", "街头采访"],
    "个人成长": ["成长", "冥想", "心智", "关系", "快乐", "淡定", "女性", "中女", "herstory"],
    "美业经营": ["美业", "门店", "客户", "美容", "顾问", "店长", "复购", "留存", "客单"],
}

BRIDGE_RULES: Dict[str, List[str]] = {
    "内容方法论": ["女性内容 IP", "内容/IP", "创意表达", "个人成长"],
    "创意素材": ["创意表达", "内容/IP"],
    "信息源清单": ["AI 工作流", "知识管理", "职业机会"],
    "行业情报": ["AI 工作流", "职业机会", "商业投研"],
    "工作流教程": ["AI 工作流", "知识管理", "美业经营"],
    "工具教程": ["AI 工作流", "知识管理"],
    "Prompt/模板": ["AI 工作流", "知识管理", "美业经营"],
    "案例拆解": ["职业机会", "内容/IP", "商业投研"],
    "职业机会": ["职业机会", "个人成长"],
    "商业投研": ["商业投研", "美业经营"],
    "观点文章": ["个人成长", "职业机会", "AI 工作流"],
    "心智成长": ["个人成长", "创意表达"],
}


@dataclass
class Asset:
    name: str
    path: Path
    kind: str
    layer: str
    text: str
    score: int = 0
    ctype: str = ""
    tags: Tuple[str, ...] = ()

    @property
    def wikilink(self) -> str:
        return f"[[{self.name}]]"


def safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def normalize(text: str) -> str:
    return text.lower().replace("｜", " ").replace("_", " ").replace("-", " ")


def tokens(text: str) -> Counter:
    normalized = normalize(text)
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]{1,}|[\u4e00-\u9fa5]{2,}", normalized)
    result = Counter()
    for word in words:
        if word in STOPWORDS:
            continue
        if len(word) > 18 and re.fullmatch(r"[\u4e00-\u9fa5]+", word):
            # Long Chinese runs are usually sentences; keep short chunks.
            for i in range(0, min(len(word), 24) - 1, 2):
                chunk = word[i:i + 2]
                if chunk not in STOPWORDS:
                    result[chunk] += 1
        else:
            result[word] += 1
    return result


def top_keywords(text: str, limit: int = 18) -> List[str]:
    return [word for word, _ in tokens(text).most_common(limit)]


def themes_for(text: str) -> List[str]:
    haystack = normalize(text)
    themes = []
    for theme, kws in THEME_KEYWORDS.items():
        if any(normalize(kw) in haystack for kw in kws):
            themes.append(theme)
    return themes


def first_paragraph(content: str, limit: int = 600) -> str:
    content = re.sub(r"---.*?---", " ", content, count=1, flags=re.DOTALL)
    content = re.sub(r"<[^>]+>", " ", content)
    for para in re.split(r"\n\s*\n", content):
        para = re.sub(r"\s+", " ", para).strip()
        if len(para) > 30:
            return para[:limit]
    return re.sub(r"\s+", " ", content).strip()[:limit]


def load_ideas() -> List[Asset]:
    assets: List[Asset] = []
    for path in iter_markdown_files(IDEAS, recursive=False):
        content = safe_read(path)
        assets.append(Asset(
            name=path.stem,
            path=path,
            kind="idea",
            layer="Inbox/Ideas",
            text=f"{path.stem}\n{first_paragraph(content, 1200)}",
        ))
    return assets


def load_clippings() -> List[Asset]:
    assets: List[Asset] = []
    for path in iter_markdown_files(CLIPPINGS):
        content = safe_read(path)
        score = 0
        ctype = ""
        tags: Tuple[str, ...] = ()
        summary = first_paragraph(content, 1200)
        if analyze_clipping:
            try:
                data = analyze_clipping(path)
                score = int(data.get("score", 0))
                ctype = str(data.get("type", ""))
                tags = tuple(str(t) for t in data.get("tags", []))  # type: ignore[arg-type]
                summary = "\n".join([
                    str(data.get("summary", "")),
                    " ".join(str(x) for x in data.get("points", [])),  # type: ignore[arg-type]
                    " ".join(str(x) for x in data.get("methods", [])),  # type: ignore[arg-type]
                ])[:1800]
            except Exception:
                pass
        assets.append(Asset(
            name=path.stem,
            path=path,
            kind="clipping",
            layer="Inbox/Clippings",
            text=f"{path.stem}\n{ctype}\n{' '.join(tags)}\n{summary}",
            score=score,
            ctype=ctype,
            tags=tags,
        ))
    return assets


def load_skill_drafts() -> List[Asset]:
    draft_dir = SKILLS / "待整理"
    assets: List[Asset] = []
    if not draft_dir.exists():
        return assets
    for path in iter_markdown_files(draft_dir):
        if not path.name.startswith("DRAFT_"):
            continue
        content = safe_read(path)
        name = path.stem
        # Keep the DRAFT_ title because Obsidian links need the actual file stem.
        assets.append(Asset(
            name=name,
            path=path,
            kind="skill_draft",
            layer="Skills/Drafts",
            text=f"{name}\n{first_paragraph(content, 1600)}",
        ))
    return assets


def load_refined_cards() -> List[Asset]:
    assets: List[Asset] = []
    if not CLIPPING_REFINE.exists():
        return assets
    for path in iter_markdown_files(CLIPPING_REFINE):
        if not path.name.startswith("提炼_"):
            continue
        content = safe_read(path)
        assets.append(Asset(
            name=path.stem,
            path=path,
            kind="refined_card",
            layer="Distilled/ClippingRefine",
            text=f"{path.stem}\n{first_paragraph(content, 1400)}",
        ))
    return assets


def name_without_prefix(name: str) -> str:
    return re.sub(r"^(DRAFT_|提炼_)", "", name)


def similarity(a: Asset, b: Asset) -> Tuple[int, List[str], List[str]]:
    if a.name == b.name:
        return 0, [], []
    a_base = name_without_prefix(a.name)
    b_base = name_without_prefix(b.name)
    score = 0
    reasons: List[str] = []

    if a_base == b_base:
        score += 60
        reasons.append("标题完全对应")
    elif a_base in b_base or b_base in a_base:
        score += 35
        reasons.append("标题高度相似")

    a_themes = set(themes_for(a.text))
    b_themes = set(themes_for(b.text))
    shared_themes = sorted(a_themes & b_themes)
    if shared_themes:
        score += min(25, len(shared_themes) * 8)
        reasons.append("主题相同：" + "、".join(shared_themes[:3]))

    a_tokens = tokens(a.text)
    b_tokens = tokens(b.text)
    shared = [word for word in (a_tokens.keys() & b_tokens.keys()) if len(word) >= 2]
    shared = sorted(shared, key=lambda w: a_tokens[w] + b_tokens[w], reverse=True)
    if shared:
        score += min(25, len(shared) * 2)
        reasons.append("关键词重合：" + "、".join(shared[:6]))

    if a.kind == "clipping" and b.kind == "skill_draft" and a_base in b_base:
        score += 20
        reasons.append("Clipping 已生成对应 Skill 草稿")
    if a.kind == "clipping" and b.kind == "idea":
        bridge_themes = set(BRIDGE_RULES.get(a.ctype, []))
        idea_themes = set(themes_for(b.text))
        matched_bridge = sorted(bridge_themes & idea_themes)
        if matched_bridge:
            score += 18 + min(12, len(matched_bridge) * 4)
            reasons.append("类型可参考：" + a.ctype + " → " + "、".join(matched_bridge[:3]))
        clip_text = normalize(a.text)
        idea_text = normalize(b.text)
        if "小红书" in idea_text and re.search(r"视频|内容|选题|账号|博主|变现|阅读赚钱|脚本|栏目", clip_text):
            score += 16
            reasons.append("可作为小红书/内容账号参考")
        if "美业" in idea_text and re.search(r"客户|运营|商业|风险|增长|投研|日报|工作流|自动化|prompt|提示词|系统", clip_text):
            score += 16
            reasons.append("可作为美业经营/客户资产系统参考")
        if re.search(r"系统|skill|提示词|流程|框架", idea_text) and re.search(r"codex|工作流|自动化|prompt|提示词|agent", clip_text):
            score += 12
            reasons.append("可借鉴为 AI 工作流/系统化方法")

    if a.kind == "idea" and b.kind == "clipping":
        idea_themes = set(themes_for(a.text))
        bridge_themes = set(BRIDGE_RULES.get(b.ctype, []))
        matched_bridge = sorted(idea_themes & bridge_themes)
        if matched_bridge:
            score += 18 + min(12, len(matched_bridge) * 4)
            reasons.append("可参考类型：" + b.ctype + " → " + "、".join(matched_bridge[:3]))
        idea_text = normalize(a.text)
        clip_text = normalize(b.text)
        if "小红书" in idea_text and re.search(r"视频|内容|选题|账号|博主|变现|阅读赚钱|脚本|栏目", clip_text):
            score += 16
            reasons.append("可为小红书/内容账号提供素材")
        if "美业" in idea_text and re.search(r"客户|运营|商业|风险|增长|投研|日报|工作流|自动化|prompt|提示词|系统", clip_text):
            score += 16
            reasons.append("可为美业经营/客户资产系统提供参考")
        if re.search(r"系统|skill|提示词|流程|框架", idea_text) and re.search(r"codex|工作流|自动化|prompt|提示词|agent", clip_text):
            score += 12
            reasons.append("可借鉴为 AI 工作流/系统化方法")

    return score, reasons[:4], shared[:8]


def suggest_pairs(source: List[Asset], targets: List[Asset], min_score: int = 28, limit_per_source: int = 4) -> Dict[str, List[Tuple[Asset, int, List[str], List[str]]]]:
    result: Dict[str, List[Tuple[Asset, int, List[str], List[str]]]] = {}
    for src in source:
        candidates = []
        for target in targets:
            if src.path == target.path:
                continue
            score, reasons, shared = similarity(src, target)
            if score >= min_score:
                candidates.append((target, score, reasons, shared))
        candidates.sort(key=lambda item: item[1], reverse=True)
        if candidates:
            result[src.name] = candidates[:limit_per_source]
    return result


def load_all_assets() -> Tuple[List[Asset], List[Asset], List[Asset], List[Asset]]:
    """Load all asset types used by this workflow."""
    ideas = load_ideas()
    clippings = load_clippings()
    drafts = load_skill_drafts()
    refined = load_refined_cards()
    return ideas, clippings, drafts, refined


def asset_index(assets: Iterable[Asset]) -> Dict[str, Asset]:
    """Map Obsidian note stem to asset. Last write wins for duplicate names."""
    return {asset.name: asset for asset in assets}


def render_suggestions(title: str, sources: Dict[str, Asset], suggestions: Dict[str, List[Tuple[Asset, int, List[str], List[str]]]]) -> List[str]:
    lines = [f"## {title}", ""]
    if not suggestions:
        lines.append("暂无高置信链接建议。")
        lines.append("")
        return lines
    for src_name, items in suggestions.items():
        src = sources[src_name]
        meta = []
        if src.ctype:
            meta.append(f"类型：{src.ctype}")
        if src.score:
            meta.append(f"分数：{src.score}/100")
        lines.append(f"### {src.wikilink}" + (f"（{'；'.join(meta)}）" if meta else ""))
        for target, score, reasons, shared in items:
            reason_text = "；".join(reasons) if reasons else "相似度较高"
            lines.append(f"- [ ] → {target.wikilink} · 置信度 {score} · {reason_text}")
        lines.append("")
    return lines


def generate_report() -> Tuple[Path, int]:
    print("🕸 正在生成结构性链接建议...")
    ideas = load_ideas()
    clippings = load_clippings()
    drafts = load_skill_drafts()
    refined = load_refined_cards()

    high_clippings = [c for c in clippings if c.score >= 50]
    clipping_by_name = {a.name: a for a in high_clippings}
    idea_by_name = {a.name: a for a in ideas}
    draft_by_name = {a.name: a for a in drafts}
    refined_by_name = {a.name: a for a in refined}

    clipping_to_idea = suggest_pairs(high_clippings, ideas, min_score=34, limit_per_source=3)
    idea_to_clipping = suggest_pairs(ideas, high_clippings, min_score=34, limit_per_source=5)

    total_links = sum(len(v) for group in [clipping_to_idea, idea_to_clipping] for v in group.values())

    report: List[str] = [
        "# 🕸 结构性链接建议", "",
        "> 目标：把高价值 Clippings 与想法织成双向关联网。当前只生成建议，不自动改写原文件。", "",
        "## 📊 总览", "",
        "| 类型 | 数量 |", "|------|------|",
        f"| 高分 Clippings（>=50） | {len(high_clippings)} |",
        f"| 想法 | {len(ideas)} |",
        f"| 推荐链接总数 | {total_links} |",
        "", "## 🧭 使用方式", "",
        "1. 先人工确认建议是否准确。",
        "2. 想采用的建议，把对应行的 `- [ ]` 改成 `- [x]`。",
        "3. 再运行 `python scripts/link_suggester.py --apply-approved`，脚本只会写回已勾选项。",
        "4. 默认生成报告不会修改任何原文；不建议无确认地自动批量写回，避免把噪音关系永久写进知识库。",
        "",
    ]

    report.extend(render_suggestions("Clipping → 想法", clipping_by_name, clipping_to_idea))
    report.extend(render_suggestions("想法 → 可参考 Clippings", idea_by_name, idea_to_clipping))

    report.extend(["## 🏷 高分 Clippings 类型索引", ""])
    by_type: Dict[str, List[Asset]] = defaultdict(list)
    for clipping in high_clippings:
        by_type[clipping.ctype or "待判断"].append(clipping)
    for ctype, items in sorted(by_type.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        report.append(f"### {ctype}")
        for item in sorted(items, key=lambda x: x.score, reverse=True)[:12]:
            report.append(f"- {item.wikilink} · {item.score}/100" + (f" · {'、'.join(item.tags[:4])}" if item.tags else ""))
        report.append("")

    report.extend(["---", "", f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"])

    OUTPUT.mkdir(parents=True, exist_ok=True)
    output_path = DEFAULT_REPORT
    output_path.write_text("\n".join(report), encoding="utf-8")
    return output_path, total_links


def parse_approved_links(report_path: Path) -> Dict[str, List[Tuple[str, str]]]:
    """Parse checked suggestions from a generated report.

    Returns {source_note_name: [(target_note_name, reason_text), ...]}.
    """
    if not report_path.exists():
        raise FileNotFoundError(f"未找到结构性链接建议报告：{report_path}")

    approved: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    current_source = ""
    heading_re = re.compile(r"^###\s+\[\[(.+?)\]\]")
    checked_re = re.compile(r"^-\s*\[[xX]\]\s*→\s*\[\[(.+?)\]\]\s*·\s*(.+)$")

    for raw_line in report_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        heading = heading_re.match(raw_line.strip())
        if heading:
            current_source = heading.group(1).strip()
            continue
        checked = checked_re.match(raw_line.strip())
        if checked and current_source:
            target = checked.group(1).strip()
            reason = checked.group(2).strip()
            approved[current_source].append((target, reason))
    return approved


def approved_block(links: List[Tuple[str, str]]) -> str:
    lines = [APPROVED_START]
    seen = set()
    for target, reason in links:
        key = target.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        clean_reason = re.sub(r"\s+", " ", reason).strip()
        lines.append(f"- [[{key}]]（结构性链接建议：{clean_reason}）")
    lines.append(APPROVED_END)
    return "\n".join(lines)


def apply_links_to_content(content: str, links: List[Tuple[str, str]]) -> str:
    """Insert or update the generated approved-link block without touching manual notes."""
    block = approved_block(links)
    marker_re = re.compile(
        rf"{re.escape(APPROVED_START)}.*?{re.escape(APPROVED_END)}",
        flags=re.DOTALL,
    )
    if marker_re.search(content):
        return marker_re.sub(block, content)

    related_heading_re = re.compile(r"(^##\s+相关链接\s*\n)", flags=re.MULTILINE)
    match = related_heading_re.search(content)
    if match:
        insert_at = match.end()
        return content[:insert_at] + "\n" + block + "\n" + content[insert_at:]

    content = content.rstrip() + "\n\n## 相关链接\n\n" + block + "\n"
    return content


def apply_approved(report_path: Path = DEFAULT_REPORT, dry_run: bool = False) -> Tuple[int, int, List[str]]:
    """Write checked links back to source notes.

    Only source notes with checked items are touched. Existing generated block is replaced;
    manual text outside the markers is preserved.
    """
    ideas, clippings, drafts, refined = load_all_assets()
    assets = asset_index([*ideas, *clippings, *drafts, *refined])
    approved = parse_approved_links(report_path)

    changed_files = 0
    applied_links = 0
    missing_sources: List[str] = []

    for source_name, links in approved.items():
        source = assets.get(source_name)
        if not source:
            missing_sources.append(source_name)
            continue
        original = source.path.read_text(encoding="utf-8", errors="ignore")
        updated = apply_links_to_content(original, links)
        if updated != original:
            changed_files += 1
            if not dry_run:
                source.path.write_text(updated, encoding="utf-8")
        applied_links += len(links)

    return applied_links, changed_files, missing_sources


def main() -> None:
    parser = argparse.ArgumentParser(description="生成结构性链接建议，或写回已勾选建议。")
    parser.add_argument("--apply-approved", action="store_true", help="只写回报告中已勾选的 - [x] 建议。")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="结构性链接建议报告路径。")
    parser.add_argument("--dry-run", action="store_true", help="预览写回数量，不修改文件。")
    args = parser.parse_args()

    print("=" * 40)
    print("🕸 结构性链接建议")
    print("=" * 40)

    if args.apply_approved:
        print("✍️  正在写回已勾选的结构性链接建议...")
        count, files, missing = apply_approved(args.report, dry_run=args.dry_run)
        mode = "预览" if args.dry_run else "完成"
        print(f"✅ 写回{mode}：{count} 条链接，涉及 {files} 个文件")
        if missing:
            print("⚠️ 未找到源文件：" + "、".join(missing[:10]))
        return

    output, count = generate_report()
    print(f"✅ 链接建议已生成：{count} 条")
    print(f"   位置：{output}")


if __name__ == "__main__":
    main()
