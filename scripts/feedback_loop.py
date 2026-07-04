#!/usr/bin/env python3
"""输出回流闭环（Phase 3 · γ 方案：本地统计 + LLM 抽样总结）。

设计原则：
- **产物落 Distilled 层**：`第二层：蒸馏层 (Distilled)/输出回流分析.md`
- **回流建议独立文件**：`第二层：蒸馏层 (Distilled)/输出回流建议.md`（供人工审阅后决定是否手动更新 Skills）
- **不静默改 Skills 层**：脚本**永不**直接改写方法论文件；只输出"建议 diff"，用户在报告里勾选后自己手动搬。
- **LLM 抽样**：只抽最近 N 篇（默认 20）走 LLM 总结，控制成本；未启用 LLM 时降级为纯统计。
- **γ 路由**：LLM 走 `kis_llm.call_json`，失败/未配置一律降级不阻塞。
- **可 dry-run**：--dry-run 只打印目标路径与统计。

隐私边界：
- 输入是「已发表内容」= 已经公开发过的东西，理论上无隐私增量。
- 但仍然走 kis_llm.py 的配置：未启用 LLM → 完全离线；启用 LLM → 内容被发送到你配置的 API。

使用：
    python3 scripts/feedback_loop.py                     # 本地统计（无 LLM）
    python3 scripts/feedback_loop.py --dry-run           # 预览
    python3 scripts/feedback_loop.py --llm               # 抽样 LLM 总结（默认 auto）
    python3 scripts/feedback_loop.py --llm=api           # 强制 LLM
    python3 scripts/feedback_loop.py --sample 30         # 抽样 30 篇
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kis_config import iter_markdown_files, layer_path

PUBLISHED_DIR = layer_path("output") / "已发表"
DISTILLED = layer_path("distilled")
OUTPUT_FILE = DISTILLED / "输出回流分析.md"
SUGGESTIONS_FILE = DISTILLED / "输出回流建议.md"
DEFAULT_SAMPLE = 20


# ── 扫描 ───────────────────────────────────────────────────────────

def scan_published() -> List[Dict[str, Any]]:
    """扫描已发表目录，读取文件正文。"""
    items: List[Dict[str, Any]] = []
    if not PUBLISHED_DIR.exists():
        return items
    for fpath in iter_markdown_files(PUBLISHED_DIR):
        try:
            stat = fpath.stat()
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        items.append({
            "name": fpath.stem,
            "path": fpath,
            "mtime": datetime.fromtimestamp(stat.st_mtime),
            "size": stat.st_size,
            "content": content,
        })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


# ── 本地统计 ───────────────────────────────────────────────────────

PLATFORM_HINTS = {
    "小红书": ["xiaohongshu", "小红书", "xhs", "点点"],
    "公众号": ["mp.weixin", "微信公众号", "gongzhonghao"],
    "即刻": ["okjike", "即刻"],
    "知乎": ["zhihu", "知乎"],
    "B站": ["bilibili", "b23.tv", "B站"],
    "抖音": ["douyin", "抖音"],
    "推特": ["twitter", "x.com"],
}


def detect_platforms(items: List[Dict[str, Any]]) -> Counter:
    counter: Counter = Counter()
    for item in items:
        content = item["content"]
        matched = False
        for platform, hints in PLATFORM_HINTS.items():
            if any(h.lower() in content.lower() for h in hints):
                counter[platform] += 1
                matched = True
                break
        if not matched:
            counter["未标注"] += 1
    return counter


def monthly_distribution(items: List[Dict[str, Any]]) -> Counter:
    return Counter(item["mtime"].strftime("%Y-%m") for item in items)


def word_frequency(items: List[Dict[str, Any]], top: int = 20) -> List[Tuple[str, int]]:
    """粗略高频词——只用于给 LLM 提示，不做最终结论。"""
    try:
        from kis_config import is_stopword
    except ImportError:
        def is_stopword(w: str) -> bool:
            return False

    counter: Counter = Counter()
    for item in items:
        text = item["content"].lower()
        # 简单切词
        tokens = re.findall(r"[\u4e00-\u9fa5]{2,}|[a-z]{3,}", text)
        for tok in tokens:
            if is_stopword(tok):
                continue
            if len(tok) < 2:
                continue
            counter[tok] += 1
    return counter.most_common(top)


# ── LLM 抽样总结 ──────────────────────────────────────────────────

FEEDBACK_SYSTEM_PROMPT = (
    "你是一个内容创作方法论提炼助手。用户会给你一组已发表过的短标题列表 + 每篇的开头预览。"
    "你的任务是从中总结出**已经被验证过的成功模式**，不要脑补数据、不要虚构"
    "阅读量或点赞数。只依据文本本身的题材、结构、口吻做归纳。"
    "所有回答必须是合法 JSON。"
)


def build_feedback_prompt(items: List[Dict[str, Any]]) -> Tuple[str, str]:
    """返回 (system, user)。"""
    blocks: List[str] = []
    for i, item in enumerate(items[:50], 1):  # 双重保险：最多 50 篇
        preview = item["content"].strip().replace("\n", " ")[:300]
        blocks.append(f"{i}. 【{item['mtime'].strftime('%Y-%m-%d')}】{item['name']}\n   预览：{preview}")

    joined = "\n\n".join(blocks)

    user_prompt = f"""下面是最近 {len(items)} 篇已发表内容，请归纳其中的规律。

严格返回如下 JSON：
{{
  "topic_clusters": [{{"name": "主题", "count": 数量, "example_titles": ["...", "..."]}}, ...],
  "title_patterns": ["观察到的标题句式1", "观察到的标题句式2", ...],
  "content_structures": ["观察到的常见结构1", ...],
  "publishing_rhythm": "关于发布节律的一句话观察",
  "reflow_suggestions": [{{"target": "适合回流到哪个方法论主题", "reason": "…", "confidence": "高/中/低"}}, ...]
}}

只用给定内容做归纳；如果样本太少或规律不明显，字段可返回空数组，绝不虚构。

已发表内容列表：
{joined}
"""
    return FEEDBACK_SYSTEM_PROMPT, user_prompt


def call_feedback_llm(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """调用 kis_llm.call_json。失败一律返回 None，不阻塞。"""
    try:
        import kis_llm  # type: ignore
    except Exception:
        print("   ⚠️ kis_llm 模块未引入，跳过 LLM 总结。")
        return None

    ok, msg = kis_llm.probe()
    if not ok:
        print(f"   ⚠️ kis_llm 不可用（{msg}），跳过 LLM 总结。")
        return None

    system, user = build_feedback_prompt(items)
    try:
        result = kis_llm.call_json(system, user, cache_purpose="feedback_loop")
        return result
    except kis_llm.LLMUnavailable as exc:
        print(f"   ⚠️ LLM 调用失败：{exc}，跳过 LLM 总结。")
        return None


# ── 报告生成 ───────────────────────────────────────────────────────

def build_stats_report(items: List[Dict[str, Any]], llm_result: Optional[Dict[str, Any]] = None) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = [
        "# 🔄 输出回流分析",
        "",
        f"> 生成时间：{now}",
        f"> 来源：`{PUBLISHED_DIR}`",
        f"> LLM 总结：{'✅ 已启用' if llm_result else '⚠️ 未启用（仅本地统计）'}",
        "",
    ]

    if not items:
        lines.extend([
            "## 📭 空目录",
            "",
            "「已发表」目录不存在或为空。请把源文件放入该目录后重跑。",
            "",
            "本次未生成回流建议。",
        ])
        return "\n".join(lines)

    # 基础统计
    lines.append("## 📊 基础统计")
    lines.append("")
    lines.append(f"- 已发表总数：**{len(items)}** 篇")
    lines.append(f"- 累计字节数：{sum(int(i['size']) for i in items):,}")
    latest, earliest = items[0], items[-1]
    lines.append(f"- 时间跨度：{earliest['mtime'].strftime('%Y-%m-%d')} → {latest['mtime'].strftime('%Y-%m-%d')}")
    lines.append("")

    # 平台分布
    platforms = detect_platforms(items)
    if platforms:
        lines.append("## 🏷️ 平台分布（启发式，仅供参考）")
        lines.append("")
        for platform, count in platforms.most_common():
            lines.append(f"- {platform}：{count} 篇")
        lines.append("")

    # 月度分布
    monthly = monthly_distribution(items)
    if monthly:
        lines.append("## 📅 月度分布")
        lines.append("")
        for month in sorted(monthly.keys()):
            lines.append(f"- {month}：{monthly[month]} 篇")
        lines.append("")

    # 高频词
    top_words = word_frequency(items, top=15)
    if top_words:
        lines.append("## 🔤 高频词（Top 15）")
        lines.append("")
        lines.append("| 词 | 出现次数 |")
        lines.append("|---|---|")
        for w, c in top_words:
            lines.append(f"| {w} | {c} |")
        lines.append("")

    # 最近清单
    lines.append("## 📝 最近 20 篇")
    lines.append("")
    for item in items[:20]:
        lines.append(f"- {item['mtime'].strftime('%Y-%m-%d')} · {item['name']}")
    if len(items) > 20:
        lines.append(f"- …（省略更早 {len(items) - 20} 篇）")
    lines.append("")

    # LLM 抽样总结
    if llm_result:
        lines.append("---")
        lines.append("")
        lines.append("## 🤖 LLM 抽样归纳")
        lines.append("")
        lines.append("> ⚠️ 以下由 LLM 从文本归纳，未使用平台真实互动数据。请当作**待验证假设**看待。")
        lines.append("")

        clusters = llm_result.get("topic_clusters") or []
        if clusters:
            lines.append("### 主题聚类")
            lines.append("")
            for c in clusters:
                if not isinstance(c, dict):
                    continue
                name = c.get("name", "?")
                count = c.get("count", "?")
                examples = c.get("example_titles") or []
                lines.append(f"- **{name}**（{count} 篇）")
                for ex in examples[:3]:
                    lines.append(f"  - {ex}")
            lines.append("")

        patterns = llm_result.get("title_patterns") or []
        if patterns:
            lines.append("### 标题句式")
            lines.append("")
            for p in patterns:
                lines.append(f"- {p}")
            lines.append("")

        structures = llm_result.get("content_structures") or []
        if structures:
            lines.append("### 内容结构")
            lines.append("")
            for s in structures:
                lines.append(f"- {s}")
            lines.append("")

        rhythm = llm_result.get("publishing_rhythm")
        if rhythm:
            lines.append("### 发布节律")
            lines.append("")
            lines.append(f"> {rhythm}")
            lines.append("")

    return "\n".join(lines)


def build_suggestions_report(items: List[Dict[str, Any]], llm_result: Optional[Dict[str, Any]] = None) -> str:
    """独立的"回流建议"文件——供人工审阅后决定是否搬运到 Skills 层。

    脚本永不直接改 Skills 层文件。所有建议都是"待用户勾选"状态。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = [
        "# 🔁 输出回流建议",
        "",
        f"> 生成时间：{now}",
        "> **重要**：本文件只是**建议清单**。脚本不会自动改 Skills 层。",
        "> 你在下面把认可的项前面 `- [ ]` 勾成 `- [x]`，然后自己决定要不要手动搬到方法论文件。",
        "",
    ]

    if not items:
        lines.append("暂无已发表内容，无建议可生成。")
        return "\n".join(lines)

    suggestions = (llm_result or {}).get("reflow_suggestions") or []

    if not suggestions:
        lines.extend([
            "## 无 LLM 建议",
            "",
            "本次未启用 LLM 或 LLM 未产出建议。以下是**基于本地统计的通用回流方向**（低置信度）：",
            "",
            f"- [ ] 你在最近 {min(len(items), 90)} 天内发了 {len(items)} 篇——是否值得沉淀「你的发布节律」方法论？",
            "- [ ] 高频词若显著集中在某几个主题，考虑把「选题集中战线」记入创作方法论。",
            "- [ ] 若某个平台占比压倒性，可以考虑「跨平台改写 Skill」作为增长杠杆。",
            "",
            "更精确的建议需要启用 LLM：`python3 scripts/feedback_loop.py --llm`。",
        ])
        return "\n".join(lines)

    lines.append("## LLM 建议清单")
    lines.append("")
    lines.append("> 每条建议来自 LLM 从已发表内容里的观察。置信度由 LLM 自评。")
    lines.append("")

    for i, s in enumerate(suggestions, 1):
        if not isinstance(s, dict):
            continue
        target = s.get("target", "未指定")
        reason = s.get("reason", "")
        confidence = s.get("confidence", "?")
        lines.append(f"### 建议 {i} · 置信度 {confidence}")
        lines.append("")
        lines.append(f"- **建议回流到**：{target}")
        lines.append(f"- **理由**：{reason}")
        lines.append(f"- [ ] 采纳此建议 → 手动更新对应 Skills 层文件")
        lines.append(f"- [ ] 不采纳（可写理由：）")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 使用说明",
        "",
        "1. 审阅上面每条建议。",
        "2. 采纳的项把 `- [ ]` 改成 `- [x]`。",
        "3. **手动**把经验写到对应 Skills 层文件里——脚本不会替你做。",
        "4. 下一轮 `feedback_loop.py` 跑时会覆盖本文件；如果想保留决策记录，另存副本或提交 git。",
    ])
    return "\n".join(lines)


# ── 入口 ───────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="输出回流闭环（Phase 3 · γ 方案）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将写入的路径与统计")
    parser.add_argument(
        "--llm",
        nargs="?",
        const="auto",
        default="off",
        choices=["off", "auto", "api"],
        help="LLM 抽样总结模式：off=不启用（默认）; auto=kis_llm 可用则调用; api=强制。不传值默认 auto。",
    )
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                        help=f"送 LLM 的抽样数量（默认 {DEFAULT_SAMPLE}，从最近开始）")
    args = parser.parse_args()

    print("=" * 40)
    print("🔄 输出回流闭环（Phase 3 · γ）")
    print("=" * 40)

    items = scan_published()
    llm_result: Optional[Dict[str, Any]] = None
    llm_enabled = args.llm != "off"

    if llm_enabled and items:
        sample = items[: max(1, args.sample)]
        print(f"🤖 LLM 抽样总结：{len(sample)} 篇（模式：{args.llm}）")
        llm_result = call_feedback_llm(sample)

    stats_report = build_stats_report(items, llm_result)
    suggestions_report = build_suggestions_report(items, llm_result)

    if args.dry_run:
        print(f"[dry-run] 将写入统计报告：{OUTPUT_FILE}")
        print(f"[dry-run] 将写入建议清单：{SUGGESTIONS_FILE}")
        print(f"[dry-run] 已发表文件数：{len(items)}")
        print(f"[dry-run] LLM 结果：{'有' if llm_result else '无'}")
        print(f"[dry-run] 报告字节数：stats={len(stats_report.encode('utf-8'))}, suggestions={len(suggestions_report.encode('utf-8'))}")
        return 0

    DISTILLED.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(stats_report, encoding="utf-8")
    SUGGESTIONS_FILE.write_text(suggestions_report, encoding="utf-8")
    print(f"✅ 统计报告：{OUTPUT_FILE}")
    print(f"✅ 建议清单：{SUGGESTIONS_FILE}")
    if not items:
        print("💡 「已发表」目录为空，报告已按空态生成。")
    elif not llm_enabled:
        print("💡 未启用 LLM。想要更深层归纳请加 `--llm`（会发送已发表内容到你配置的 LLM 端点）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
