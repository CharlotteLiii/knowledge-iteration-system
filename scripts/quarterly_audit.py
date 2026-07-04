#!/usr/bin/env python3
"""知识资产季度审计：按四层结构分层体检，区分自动引用与人工/结构性关联。"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from kis_config import VAULT, iter_markdown_files, layer_path, should_ignore_path, subfolder_path

OUTPUT = layer_path("distilled")

LAYER_LABELS = {
    "inbox": "第一层输入 Inbox",
    "distilled": "第二层蒸馏 Distilled",
    "skills": "第三层技能 Skills",
    "output": "第四层输出 Output",
    "system": "系统与脚本 System",
    "other": "其他 Other",
}

SUBFOLDER_LABELS = {
    "ideas": "输入/想法",
    "clippings": "输入/Clippings",
    "dailyDistill": "蒸馏/每日蒸馏",
    "weeklyReview": "蒸馏/每周复盘",
    "ideaTracking": "蒸馏/想法追踪",
    "clippingRefine": "蒸馏/Clippings提炼",
}

GENERATED_MARKERS = (
    "知识蒸馏", "每周复盘", "Clippings总览报告", "提炼_", "想法成熟度全景",
    "知识资产审计", "DRAFT_", "README",
)

# Official skill package docs are useful files but do not always participate in the Obsidian graph.
PACKAGE_DOC_PARTS = ("/references/", "/templates/", "/assets/", "/examples/")


@dataclass
class FileAsset:
    name: str
    path: Path
    rel: str
    layer: str
    bucket: str
    days_since_edit: int
    link_count: int
    backlinks: int
    curated_backlinks: int
    word_count: int
    headings: int
    tasks: int
    is_generated: bool
    is_draft: bool
    is_published: bool
    is_package_doc: bool

    @property
    def total_connections(self) -> int:
        """All wiki links including automatic reports."""
        return self.link_count + self.backlinks

    @property
    def curated_link_count(self) -> int:
        """Outgoing links only count as curated if the source file is not auto-generated."""
        return 0 if self.is_generated else self.link_count

    @property
    def curated_connections(self) -> int:
        """Connections that likely represent human/structural organization."""
        return self.curated_link_count + self.curated_backlinks

    @property
    def needs_graph_attention(self) -> bool:
        if self.is_generated:
            return False
        if self.is_package_doc:
            return False
        return self.curated_connections == 0


@dataclass
class LayerStats:
    key: str
    label: str
    files: List[FileAsset]

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def words(self) -> int:
        return sum(f.word_count for f in self.files)

    @property
    def links(self) -> int:
        return sum(f.link_count for f in self.files)

    @property
    def generated(self) -> int:
        return sum(1 for f in self.files if f.is_generated)

    @property
    def drafts(self) -> int:
        return sum(1 for f in self.files if f.is_draft)

    @property
    def recent(self) -> int:
        return sum(1 for f in self.files if f.days_since_edit <= 7)

    @property
    def cold(self) -> List[FileAsset]:
        return [f for f in self.files if f.days_since_edit > 30]

    @property
    def graph_orphans(self) -> List[FileAsset]:
        return [f for f in self.files if f.needs_graph_attention]

    @property
    def avg_total_connections(self) -> float:
        return sum(f.total_connections for f in self.files) / self.count if self.count else 0.0

    @property
    def avg_curated_connections(self) -> float:
        return sum(f.curated_connections for f in self.files) / self.count if self.count else 0.0


def safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def rel_to_vault(path: Path) -> str:
    try:
        return str(path.relative_to(VAULT))
    except ValueError:
        return str(path)


def is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def configured_paths() -> Dict[str, Path]:
    paths = {
        "inbox": layer_path("inbox"),
        "distilled": layer_path("distilled"),
        "skills": layer_path("skills"),
        "output": layer_path("output"),
    }
    for key in SUBFOLDER_LABELS:
        try:
            paths[key] = subfolder_path(key)
        except SystemExit:
            pass
    return paths


def classify_layer(path: Path, paths: Dict[str, Path]) -> str:
    rel = rel_to_vault(path)
    if rel.startswith("scripts/") or rel == ".knowledge-iteration-system.json" or rel.startswith(".openclaw"):
        return "system"
    for key in ("inbox", "distilled", "skills", "output"):
        root = paths.get(key)
        if root and is_under(path, root):
            return key
    return "other"


def classify_bucket(path: Path, layer: str, paths: Dict[str, Path]) -> str:
    for key, label in SUBFOLDER_LABELS.items():
        root = paths.get(key)
        if root and is_under(path, root):
            return label
    rel = rel_to_vault(path)
    if layer == "skills" and "待整理" in rel:
        return "技能/待整理草稿"
    if layer == "skills" and "knowledge-iteration-system" in rel:
        return "技能/正式 Skill"
    if layer == "output" and "已发表" in rel:
        return "输出/已发表"
    if layer == "system":
        return "系统/脚本与说明"
    if layer == "other":
        first = rel.split("/", 1)[0]
        legacy_names = {
            "工作": "未映射旧知识/工作",
            "身体与心灵": "未映射旧知识/身体与心灵",
            "FemAI": "未映射旧知识/FemAI",
            "To Do List": "未映射旧知识/待办",
        }
        return legacy_names.get(first, f"未映射旧知识/{first}")
    return LAYER_LABELS.get(layer, layer)


def is_generated_file(path: Path, content: str) -> bool:
    name = path.name
    rel = rel_to_vault(path)
    if any(marker in name for marker in GENERATED_MARKERS):
        return True
    if "第二层：蒸馏层" in rel and re.search(r"\*生成时间：|报告已生成|自动分析|自动提取", content):
        return True
    if "第三层：技能层" in rel and "待整理" in rel and name.startswith("DRAFT_"):
        return True
    return False


def is_draft_file(path: Path, content: str) -> bool:
    rel = rel_to_vault(path)
    return path.name.startswith("DRAFT_") or "待整理" in rel or "[ ]" in content[:3000]


def is_published_file(path: Path, content: str) -> bool:
    rel = rel_to_vault(path)
    return "已发表" in rel or bool(re.search(r"发布链接|已发布|published", content, flags=re.IGNORECASE))


def is_package_doc(path: Path) -> bool:
    rel = "/" + rel_to_vault(path).replace("\\", "/")
    if "knowledge-iteration-system" not in rel:
        return False
    return any(part in rel for part in PACKAGE_DOC_PARTS) or rel.endswith("/SKILL.md")


def extract_links(content: str) -> List[str]:
    links = []
    for raw in re.findall(r"\[\[(.+?)\]\]", content):
        target = raw.split("|")[0].split("#")[0].strip()
        if target:
            links.append(target)
    return links


def build_backlinks(file_records: List[Dict[str, object]], curated_only: bool = False) -> Counter:
    name_set = {str(f["name"]) for f in file_records}
    counter: Counter = Counter()
    for rec in file_records:
        if curated_only and bool(rec["is_generated"]):
            continue
        for link in rec["links"]:  # type: ignore[index]
            if str(link) in name_set:
                counter[str(link)] += 1
    return counter


def scan_assets(include_system: bool = False) -> List[FileAsset]:
    paths = configured_paths()
    raw_records: List[Dict[str, object]] = []

    for fpath in iter_markdown_files(VAULT):
        if should_ignore_path(fpath):
            continue
        layer = classify_layer(fpath, paths)
        if layer == "system" and not include_system:
            continue
        content = safe_read(fpath)
        mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
        links = extract_links(content)
        generated = is_generated_file(fpath, content)
        raw_records.append({
            "name": fpath.stem,
            "path": fpath,
            "rel": rel_to_vault(fpath),
            "layer": layer,
            "bucket": classify_bucket(fpath, layer, paths),
            "days_since_edit": (datetime.now() - mtime).days,
            "link_count": len(links),
            "links": links,
            "word_count": len(content),
            "headings": len(re.findall(r"^#{1,6}\s+", content, flags=re.MULTILINE)),
            "tasks": len(re.findall(r"- \[[ xX]\]", content)),
            "is_generated": generated,
            "is_draft": is_draft_file(fpath, content),
            "is_published": is_published_file(fpath, content),
            "is_package_doc": is_package_doc(fpath),
        })

    backlinks = build_backlinks(raw_records, curated_only=False)
    curated_backlinks = build_backlinks(raw_records, curated_only=True)
    assets: List[FileAsset] = []
    for rec in raw_records:
        name = str(rec["name"])
        assets.append(FileAsset(
            name=name,
            path=rec["path"],  # type: ignore[arg-type]
            rel=str(rec["rel"]),
            layer=str(rec["layer"]),
            bucket=str(rec["bucket"]),
            days_since_edit=int(rec["days_since_edit"]),
            link_count=int(rec["link_count"]),
            backlinks=int(backlinks[name]),
            curated_backlinks=int(curated_backlinks[name]),
            word_count=int(rec["word_count"]),
            headings=int(rec["headings"]),
            tasks=int(rec["tasks"]),
            is_generated=bool(rec["is_generated"]),
            is_draft=bool(rec["is_draft"]),
            is_published=bool(rec["is_published"]),
            is_package_doc=bool(rec["is_package_doc"]),
        ))
    return assets


def layer_stats(assets: List[FileAsset]) -> Dict[str, LayerStats]:
    grouped: Dict[str, List[FileAsset]] = defaultdict(list)
    for asset in assets:
        grouped[asset.layer].append(asset)
    return {
        key: LayerStats(key=key, label=LAYER_LABELS.get(key, key), files=sorted(files, key=lambda f: f.rel))
        for key, files in grouped.items()
    }


def health_status(stats: LayerStats) -> str:
    if not stats.count:
        return "空"
    generated_rate = stats.generated / stats.count
    orphan_rate = len(stats.graph_orphans) / stats.count
    if stats.key == "output" and stats.count == 0:
        return "待启动"
    if generated_rate > 0.75 and stats.key == "distilled":
        return "自动产物偏多"
    if orphan_rate > 0.65 and stats.key not in {"inbox", "output"}:
        return "需整理"
    if stats.key == "inbox" and stats.avg_curated_connections < 1:
        return "待蒸馏"
    if stats.avg_curated_connections >= 1.5 or stats.recent >= max(1, stats.count // 5):
        return "健康"
    return "可优化"


def top_assets(files: List[FileAsset], limit: int = 8, curated: bool = False) -> List[FileAsset]:
    key = (lambda f: (f.curated_connections, f.word_count)) if curated else (lambda f: (f.total_connections, f.word_count))
    return sorted(files, key=key, reverse=True)[:limit]


def cold_assets(files: List[FileAsset], limit: int = 10) -> List[FileAsset]:
    return sorted([f for f in files if f.days_since_edit > 30], key=lambda f: -f.days_since_edit)[:limit]


def graph_orphans(files: List[FileAsset], limit: int = 12) -> List[FileAsset]:
    return sorted([f for f in files if f.needs_graph_attention], key=lambda f: (f.layer, f.rel))[:limit]


def make_layer_table(stats_by_layer: Dict[str, LayerStats]) -> List[str]:
    lines = [
        "| 层级 | 状态 | 文件数 | 近7天活跃 | 自动生成 | 草稿 | 平均人工关联 | 平均总关联 | 需补连接 |",
        "|------|------|--------|------------|----------|------|--------------|----------|----------|",
    ]
    for key in ("inbox", "distilled", "skills", "output", "other"):
        stats = stats_by_layer.get(key, LayerStats(key, LAYER_LABELS.get(key, key), []))
        orphan_text = f"{len(stats.graph_orphans)} ({len(stats.graph_orphans)/stats.count*100:.1f}%)" if stats.count else "0"
        lines.append(
            f"| {stats.label} | {health_status(stats)} | {stats.count} | {stats.recent} | {stats.generated} | {stats.drafts} | {stats.avg_curated_connections:.1f} | {stats.avg_total_connections:.1f} | {orphan_text} |"
        )
    return lines


def make_bucket_table(assets: List[FileAsset]) -> List[str]:
    buckets: Dict[str, List[FileAsset]] = defaultdict(list)
    for asset in assets:
        buckets[asset.bucket].append(asset)
    lines = ["| 分类 | 文件数 | 自动生成 | 平均人工关联 | 平均总关联 | 最近活跃 |", "|------|--------|----------|--------------|----------|----------|"]
    for bucket, files in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        avg_curated = sum(f.curated_connections for f in files) / len(files) if files else 0
        avg_total = sum(f.total_connections for f in files) / len(files) if files else 0
        generated = sum(1 for f in files if f.is_generated)
        recent = sum(1 for f in files if f.days_since_edit <= 7)
        lines.append(f"| {bucket} | {len(files)} | {generated} | {avg_curated:.1f} | {avg_total:.1f} | {recent} |")
    return lines


def recommendations(stats_by_layer: Dict[str, LayerStats], assets: List[FileAsset]) -> List[str]:
    recs: List[str] = []
    inbox = stats_by_layer.get("inbox")
    distilled = stats_by_layer.get("distilled")
    skills = stats_by_layer.get("skills")
    output = stats_by_layer.get("output")
    other = stats_by_layer.get("other")

    if inbox and inbox.count:
        low_curated = [f for f in inbox.files if f.curated_connections == 0]
        if low_curated:
            recs.append(f"- [ ] Inbox 有 {len(low_curated)} 条内容只有自动报告引用，建议挑 5 条高潜输入手动链接到对应蒸馏卡或 Skill 草稿。")
        else:
            recs.append(f"- [ ] Inbox 已有人工关联基础，可继续挑 {min(5, inbox.count)} 条高潜输入推进到输出。")
    if distilled and distilled.count and distilled.generated / distilled.count > 0.6:
        recs.append("- [ ] 蒸馏层自动报告占比较高，建议把高价值报告二次整理成想法追踪或 Skill 候选。")
    if skills:
        drafts = [f for f in skills.files if f.is_draft]
        if drafts:
            recs.append(f"- [ ] Skills 待整理草稿有 {len(drafts)} 个，优先审核人工关联最高或来自高分 Clipping 的草稿。")
    if (not output) or output.count == 0:
        recs.append("- [ ] Output 已发表仍为空：可以从 P2 以上想法或高分 Clipping 里选 1 个做最小发布。")
    graph_attention = [f for f in assets if f.layer not in {"inbox", "output"} and f.needs_graph_attention]
    if graph_attention:
        recs.append(f"- [ ] 有 {len(graph_attention)} 个非输入层资产缺少人工/结构性关联，建议优先给 Skill/概念卡建立 2-3 个双链。")
    cold = [f for f in assets if f.days_since_edit > 30 and not f.is_generated]
    if cold:
        recs.append(f"- [ ] 有 {len(cold)} 个超过 30 天未更新的非自动资产，可抽样回顾是否仍有价值。")
    if other and other.count:
        recs.append(f"- [ ] 有 {other.count} 个文件位于四层结构外，建议决定：迁入 Inbox/Distilled/Output，或在配置里补充映射规则。")
    if not recs:
        recs.append("- [ ] 当前结构较健康，下一步可增加输出回流数据。")
    return recs


def generate_report() -> tuple[Path, int]:
    print("🔍 正在扫描知识库...")
    assets = scan_assets(include_system=False)
    stats_by_layer = layer_stats(assets)
    quarter = (datetime.now().month - 1) // 3 + 1

    total_files = len(assets)
    total_words = sum(f.word_count for f in assets)
    total_links = sum(f.link_count for f in assets)
    total_connections = sum(f.total_connections for f in assets)
    curated_connections = sum(f.curated_connections for f in assets)
    generated_count = sum(1 for f in assets if f.is_generated)
    draft_count = sum(1 for f in assets if f.is_draft)
    recent_count = sum(1 for f in assets if f.days_since_edit <= 7)
    attention = [f for f in assets if f.needs_graph_attention]
    cold = [f for f in assets if f.days_since_edit > 30]

    report: List[str] = [
        f"# 🏥 知识资产分层审计报告 - Q{quarter} {datetime.now().year}", "",
        "> 按四层知识迭代系统分层体检，并区分自动报告引用与人工/结构性关联。", "",
        "## 📊 全库总览", "",
        "| 指标 | 数值 |", "|------|------|",
        f"| 文件总数 | {total_files} |",
        f"| 总字数 | {total_words:,} |",
        f"| 出链总数 | {total_links} |",
        f"| 出链+反链总关联 | {total_connections} |",
        f"| 人工/结构性关联 | {curated_connections} |",
        f"| 平均总关联度 | {total_connections/total_files:.1f} 连接/文件 |" if total_files else "| 平均总关联度 | 0 |",
        f"| 平均人工关联度 | {curated_connections/total_files:.1f} 连接/文件 |" if total_files else "| 平均人工关联度 | 0 |",
        f"| 近 7 天活跃 | {recent_count} |",
        f"| 自动生成资产 | {generated_count} |",
        f"| 草稿/待办资产 | {draft_count} |",
        f"| 需补人工连接 | {len(attention)} ({len(attention)/total_files*100:.1f}%) |" if total_files else "| 需补人工连接 | 0 |",
        f"| 冷知识 >30 天 | {len(cold)} ({len(cold)/total_files*100:.1f}%) |" if total_files else "| 冷知识 >30 天 | 0 |",
        "", "## 🧱 四层结构健康度", "",
    ]
    report.extend(make_layer_table(stats_by_layer))
    report.extend(["", "## 🗂 分类分布", ""])
    report.extend(make_bucket_table(assets))

    report.extend(["", "## 🔥 高人工关联资产", ""])
    curated_top = [f for f in top_assets(assets, curated=True) if f.curated_connections > 0]
    if curated_top:
        report.extend(["| 资产 | 层级 | 人工关联 | 总关联 | 字数 |", "|------|------|----------|--------|------|"])
        for f in curated_top:
            report.append(f"| [[{f.name}]] | {LAYER_LABELS.get(f.layer, f.layer)} | {f.curated_connections} | {f.total_connections} | {f.word_count:,} |")
    else:
        report.append("暂无。")

    report.extend(["", "## 🤖 自动报告带来的高引用资产", ""])
    auto_top = [f for f in top_assets(assets, curated=False) if f.total_connections > f.curated_connections][:8]
    if auto_top:
        report.extend(["| 资产 | 层级 | 总关联 | 人工关联 | 说明 |", "|------|------|--------|----------|------|"])
        for f in auto_top:
            report.append(f"| [[{f.name}]] | {LAYER_LABELS.get(f.layer, f.layer)} | {f.total_connections} | {f.curated_connections} | 主要来自自动报告/总览引用 |")
    else:
        report.append("暂无明显自动引用膨胀。")

    report.extend(["", "## 🧊 冷知识清单（非自动产物优先回顾）", ""])
    cold_non_generated = [f for f in cold_assets(assets, 20) if not f.is_generated][:10]
    if cold_non_generated:
        for f in cold_non_generated:
            report.append(f"- [[{f.name}]]：{f.days_since_edit} 天未更新 · {LAYER_LABELS.get(f.layer, f.layer)}")
    else:
        report.append("暂无明显需要回顾的非自动冷知识。")

    report.extend(["", "## 🕸 需补人工/结构性连接的资产抽样", ""])
    sample = graph_orphans(assets)
    if sample:
        for f in sample:
            report.append(f"- [[{f.name}]] · {LAYER_LABELS.get(f.layer, f.layer)} · {f.bucket}")
    else:
        report.append("暂无需要补人工连接的资产。")

    report.extend(["", "## 🎯 本季度行动建议", ""])
    report.extend(recommendations(stats_by_layer, assets))

    report.extend(["", "## 🔎 审计说明", "",
        "- 总关联 = 文件出链 + 所有反链，包含自动报告和总览报告产生的引用。",
        "- 人工/结构性关联 = 非自动生成文件的出链 + 来自非自动生成文件的反链，更能反映人工整理程度。",
        "- 自动生成资产、正式 Skill 包内 references/templates/SKILL.md 不默认视为需要补连接。",
        "- Inbox 孤立或人工关联低不一定是坏事；它是原料层，重点是定期筛选进入蒸馏/技能/输出。",
        "", f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])

    output_path = OUTPUT / f"Q{quarter}_{datetime.now().year}_知识资产审计.md"
    output_path.write_text("\n".join(report), encoding="utf-8")
    return output_path, total_files


if __name__ == "__main__":
    print("=" * 40)
    print("🏥 知识资产季度审计")
    print("=" * 40)
    output, count = generate_report()
    print(f"✅ 审计报告已生成，扫描了 {count} 篇知识资产")
    print(f"   位置：{output}")
