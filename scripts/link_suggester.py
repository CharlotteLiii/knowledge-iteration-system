#!/usr/bin/env python3
"""结构性链接建议：把高价值 Clippings 与想法织成知识网络。

默认只生成带复选框的建议报告；用户在 Obsidian 中勾选后，才可用
--apply-approved 把已勾选链接写回源文件的「相关链接」章节。
"""
from __future__ import annotations

import argparse
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from kis_config import iter_markdown_files, subfolder_path
from kis_config import themes as _themes_config
from kis_config import bridges as _bridges_config
from kis_config import domain_rules as _domain_rules_config

try:
    from clipping_refiner import analyze_file as analyze_clipping
except Exception:  # pragma: no cover - fallback for standalone environments
    analyze_clipping = None

IDEAS = subfolder_path("ideas")
CLIPPINGS = subfolder_path("clippings")
OUTPUT = subfolder_path("linkSuggestions")
DEFAULT_REPORT = OUTPUT / "结构性链接建议.md"
APPROVED_START = "<!-- KIS_APPROVED_LINKS_START -->"
APPROVED_END = "<!-- KIS_APPROVED_LINKS_END -->"

STOPWORDS = {
    "一个", "一种", "这个", "那个", "如何", "怎么", "什么", "为什么", "进行", "可以", "需要", "建议",
    "内容", "方法", "工具", "系统", "自动", "生成", "使用", "教程", "指南", "完整", "全网", "最全",
    "2026", "06", "07", "ai", "AI", "的", "了", "和", "与", "在", "是", "有", "为", "到",
}

# THEME_KEYWORDS / BRIDGE_RULES / 领域启发规则均改为从 taxonomy 配置读取
# （kis_config.themes / bridges / domain_rules）。历史默认值见 scripts/taxonomy.default.json。
THEME_KEYWORDS: Dict[str, List[str]] = _themes_config()
BRIDGE_RULES: Dict[str, List[str]] = _bridges_config()
DOMAIN_RULES: List[dict] = _domain_rules_config()


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


# ---------------------------------------------------------------------------
# 可插拔相似度 backend
#
# 关键词重合得分从“裸交集计数”升级为可选的 TF-IDF 加权。两种后端：
#   - legacy : 共享 token 数 × 2，上限 25（历史行为）
#   - tfidf  : 按 IDF 加权共享 token，除以平均 IDF 得到“有效共享 token 数”，
#              再走同样的 ×2 / cap 25。量纲与 legacy 一致，但罕见专有词权重>1、
#              泛词权重<1，插插链质量更好。纯本地、无 API、无隐私风险。
#
# 未来接 embedding 只需新增一个 backend + 一个 --similarity 选项，主流程不变。
# ---------------------------------------------------------------------------


class RuleOverlapBackend:
    """Legacy backend: raw shared-token count × 2, capped at 25."""

    name = "legacy"

    def __init__(self, corpus: List["Asset"] | None = None) -> None:
        self._corpus = corpus or []

    def keyword_component(self, a: "Asset", b: "Asset") -> Tuple[int, List[str]]:
        a_tokens = tokens(a.text)
        b_tokens = tokens(b.text)
        shared = [w for w in (a_tokens.keys() & b_tokens.keys()) if len(w) >= 2]
        shared = sorted(shared, key=lambda w: (-(a_tokens[w] + b_tokens[w]), w))
        score = min(25, len(shared) * 2) if shared else 0
        return score, shared[:8]


class TfidfBackend:
    """IDF-weighted shared-token scoring, magnitude-compatible with legacy.

    Builds a document-frequency table once from the corpus. A shared token's
    contribution is its IDF; the summed IDF is divided by the corpus mean IDF to
    yield an "effective shared-token count", then scored with the same ×2 / cap-25
    formula as the legacy backend.
    """

    name = "tfidf"

    def __init__(self, corpus: List["Asset"]) -> None:
        self._corpus = corpus
        n_docs = max(len(corpus), 1)
        df: Counter = Counter()
        self._doc_tokens: Dict[str, Counter] = {}
        for asset in corpus:
            toks = tokens(asset.text)
            self._doc_tokens[asset.path.as_posix()] = toks
            for term in toks:
                if len(term) >= 2:
                    df[term] += 1
        # Smoothed IDF: log((1 + N) / (1 + df)) + 1  (always > 0)
        self._idf: Dict[str, float] = {
            term: math.log((1 + n_docs) / (1 + freq)) + 1.0 for term, freq in df.items()
        }
        self._mean_idf = (sum(self._idf.values()) / len(self._idf)) if self._idf else 1.0

    def _tokens_for(self, asset: "Asset") -> Counter:
        return self._doc_tokens.get(asset.path.as_posix()) or tokens(asset.text)

    def keyword_component(self, a: "Asset", b: "Asset") -> Tuple[int, List[str]]:
        a_tokens = self._tokens_for(a)
        b_tokens = self._tokens_for(b)
        shared = [w for w in (a_tokens.keys() & b_tokens.keys()) if len(w) >= 2]
        if not shared:
            return 0, []
        # Order by informativeness (IDF desc), then alphabetically for determinism.
        shared.sort(key=lambda w: (-self._idf.get(w, self._mean_idf), w))
        weighted = sum(self._idf.get(w, self._mean_idf) for w in shared)
        effective = weighted / self._mean_idf if self._mean_idf else len(shared)
        score = min(25, round(effective * 2))
        return score, shared[:8]


_BACKENDS = {"legacy": RuleOverlapBackend, "tfidf": TfidfBackend}
_DEFAULT_BACKEND = "tfidf"
_ACTIVE_BACKEND: object | None = None


def build_backend(kind: str, corpus: List["Asset"]):
    factory = _BACKENDS.get(kind, _BACKENDS[_DEFAULT_BACKEND])
    return factory(corpus)


def set_backend(backend) -> None:
    global _ACTIVE_BACKEND
    _ACTIVE_BACKEND = backend


def get_backend():
    global _ACTIVE_BACKEND
    if _ACTIVE_BACKEND is None:
        _ACTIVE_BACKEND = RuleOverlapBackend([])
    return _ACTIVE_BACKEND


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
    for path in iter_markdown_files(IDEAS, recursive=True):
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


def name_without_prefix(name: str) -> str:
    return re.sub(r"^(DRAFT_|提炼_)", "", name)


def _bridge_score(clip: Asset, idea: Asset, clip_is_source: bool) -> Tuple[int, List[str]]:
    """Directional clipping<->idea bridge scoring, driven by taxonomy config.

    `clip` is always the clipping asset, `idea` always the idea asset, regardless
    of which one is the source of the suggestion. `clip_is_source` only changes
    the human-facing reason wording so both directions read naturally.
    """
    score = 0
    reasons: List[str] = []

    bridge_themes = set(BRIDGE_RULES.get(clip.ctype, []))
    idea_themes = set(themes_for(idea.text))
    matched_bridge = sorted(bridge_themes & idea_themes)
    if matched_bridge:
        score += 18 + min(12, len(matched_bridge) * 4)
        prefix = "类型可参考：" if clip_is_source else "可参考类型："
        reasons.append(prefix + clip.ctype + " → " + "、".join(matched_bridge[:3]))

    idea_text = normalize(idea.text)
    clip_text = normalize(clip.text)
    for rule in DOMAIN_RULES:
        contains = rule.get("idea_contains")
        if contains and contains not in idea_text:
            continue
        idea_regex = rule.get("idea_regex")
        if idea_regex and not re.search(idea_regex, idea_text):
            continue
        clip_regex = rule.get("clip_regex")
        if clip_regex and not re.search(clip_regex, clip_text):
            continue
        score += int(rule.get("score", 0))
        key = "reason_clip_to_idea" if clip_is_source else "reason_idea_to_clip"
        reason = rule.get(key) or rule.get("reason_clip_to_idea") or ""
        if reason:
            reasons.append(reason)
    return score, reasons


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

    kw_score, shared = get_backend().keyword_component(a, b)
    if kw_score:
        score += kw_score
        reasons.append("关键词重合：" + "、".join(shared[:6]))

    if a.kind == "clipping" and b.kind == "idea":
        bridge, bridge_reasons = _bridge_score(a, b, clip_is_source=True)
        score += bridge
        reasons.extend(bridge_reasons)
    elif a.kind == "idea" and b.kind == "clipping":
        bridge, bridge_reasons = _bridge_score(b, a, clip_is_source=False)
        score += bridge
        reasons.extend(bridge_reasons)

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


def load_all_assets() -> Tuple[List[Asset], List[Asset]]:
    """Load asset types used by this workflow (ideas + clippings).

    Skill drafts and refined cards are intentionally not loaded: the report only
    renders clipping<->idea links, so write-back targets are always ideas or
    clippings.
    """
    ideas = load_ideas()
    clippings = load_clippings()
    return ideas, clippings


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


def generate_report(similarity_backend: str = _DEFAULT_BACKEND) -> Tuple[Path, int]:
    print("🕸 正在生成结构性链接建议...")
    ideas = load_ideas()
    clippings = load_clippings()

    high_clippings = [c for c in clippings if c.score >= 50]
    clipping_by_name = {a.name: a for a in high_clippings}
    idea_by_name = {a.name: a for a in ideas}

    # Build the similarity backend from the scored corpus (ideas + high clippings).
    set_backend(build_backend(similarity_backend, [*ideas, *high_clippings]))

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
    ideas, clippings = load_all_assets()
    assets = asset_index([*ideas, *clippings])
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
    parser.add_argument(
        "--similarity",
        choices=["tfidf", "legacy"],
        default=_DEFAULT_BACKEND,
        help="关键词相似度后端：tfidf（默认，IDF 加权）或 legacy（旧版裸计数）。均为纯本地。")
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

    output, count = generate_report(similarity_backend=args.similarity)
    print(f"✅ 链接建议已生成：{count} 条（相似度后端：{args.similarity}）")
    print(f"   位置：{output}")


if __name__ == "__main__":
    main()
