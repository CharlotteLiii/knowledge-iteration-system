#!/usr/bin/env python3
"""Skill 升级路径工具（Phase 3）。

读取 `第三层：技能层 (Skills)/待整理/EVAL_*.md` 的可行性评估卡，
根据卡片里的判定结果给出**具体下一步该做什么**，并映射到 Skill 成熟度模型的
Level 0-5（参考 references/maturity-model.md）。

设计原则：
- **不改评估卡**：只读，不写回 EVAL 卡本身。产物是独立的"升级路线图"报告。
- **产物落 Distilled 层**：Skills 层保留人工/评估卡，路线图属于蒸馏产物。
- **无 LLM**：全部基于评估卡里已经明确的 ✅/⚠️/❌ + 待补充 字段推断。
- **可 dry-run**：--dry-run 只打印会写什么，不实际写入。
- **诚实标注**：如果评估卡本身还是"待补充"，不假装能升级。

使用：
    python3 scripts/skill_upgrader.py               # 生成升级路线图
    python3 scripts/skill_upgrader.py --dry-run     # 预览产物
    python3 scripts/skill_upgrader.py --min-yes 4   # 只看强候选
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from kis_config import layer_path

SKILLS_DIR = layer_path("skills")
EVAL_DIR = SKILLS_DIR / "待整理"
DISTILLED = layer_path("distilled")
OUTPUT_FILE = SKILLS_DIR / "Skill 升级路线图.md"


# ── Level 模型 ─────────────────────────────────────────────────────

LEVEL_NAMES = {
    0: "普通笔记（无 Skill 潜力）",
    1: "重复出现的问题",
    2: "有稳定处理步骤",
    3: "有输入输出和判断标准",
    4: "可写成 Skill 草案",
    5: "已验证，可正式沉淀",
}


@dataclass
class EvalCard:
    path: Path
    title: str
    conclusion: str          # 🔴 / 🟡 / 🟢
    yes_count: int           # 0-5
    dim_status: Dict[str, str] = field(default_factory=dict)  # {dim: ✅/⚠️/❌}
    dim_source: Dict[str, str] = field(default_factory=dict)  # {dim: 原文抽取/AI 推测/待补充}
    section2_gaps: List[str] = field(default_factory=list)    # 哪些字段是"待补充"
    section3_gaps: List[str] = field(default_factory=list)
    section4_todos: List[str] = field(default_factory=list)   # EVAL 卡里的 Gap 清单
    step_count: int = 0

    @property
    def level(self) -> int:
        """根据可行性判定推 Level（0-5）。"""
        conclusion = self.conclusion
        yes = self.yes_count
        section2_filled = 5 - len(self.section2_gaps)  # section2 5 个字段
        section3_filled = 6 - len(self.section3_gaps)  # section3 6 个字段
        gap_open = len(self.section4_todos)

        if conclusion == "🟢" or yes <= 1:
            return 0
        if yes == 2:
            return 1
        # yes >= 3
        if section3_filled < 2:
            return 2                   # 有可复用但没抽出形态
        if section2_filled < 3 or gap_open >= 3:
            return 3                   # 有形态但情境模糊
        if gap_open >= 1:
            return 4                   # 只剩少量 Gap
        return 5

    @property
    def next_actions(self) -> List[str]:
        """升级到下一 level 需要做什么。"""
        lv = self.level
        if lv == 5:
            return ["✅ 已就绪：可提交 skill_workshop 或转成正式 Skill。"]
        actions: List[str] = []
        if lv <= 1:
            # 是否值得继续投入
            if self.conclusion == "🟢":
                actions.append("先判断「继续投入价值」：低价值想法可归档，不必强行升 Level。")
            else:
                actions.append("确认这是不是「一次性观察」——若能预见未来会再遇同类需求，才继续升级。")
        if lv <= 2:
            actions.append("把可复用性/输入稳定性写清楚，或用一次真实执行补足证据。")
        if lv <= 3:
            # section3 缺什么
            if "输入" in self.section3_gaps:
                actions.append("明确 Skill 输入：需要什么材料/参数？")
            if "输出" in self.section3_gaps:
                actions.append("明确 Skill 输出：产物形式是什么？")
            if "工具" in self.section3_gaps or "工具/账号" in self.section3_gaps:
                actions.append("列出必需的工具、API、账号权限。")
            if "步骤" in self.section3_gaps and self.step_count < 3:
                actions.append(f"补充 ≥3 个明确编号步骤（当前抽取到 {self.step_count} 步）。")
        if lv <= 3 and self.section2_gaps:
            for gap in self.section2_gaps:
                actions.append(f"补充「{gap}」——原文没写但决定这个 Skill 值不值得做。")
        if lv == 4:
            for todo in self.section4_todos[:3]:
                actions.append(f"关闭 Gap：{todo}")
            actions.append("补齐后跑一次真实场景，把结果作为 Level 5 的「验证证据」。")

        if not actions:
            actions.append(f"继续把 Level {lv+1} 需要的条件补齐（参考 references/maturity-model.md）。")
        return actions


# ── EVAL 卡解析 ────────────────────────────────────────────────────

DIM_LABELS = {
    "内容可复用": "reusable",
    "输入稳定": "input_stable",
    "步骤清晰": "steps_clear",
    "输出可验证": "output_verifiable",
    "真实案例": "has_case",
}


def parse_eval_card(path: Path) -> Optional[EvalCard]:
    """解析单张 EVAL 卡。解析失败返回 None（不阻塞主流程）。"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    title_match = re.search(r"^#\s+.*?[:：]\s*(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem

    conclusion_match = re.search(r"评估结论[:：]\s*([🔴🟡🟢])", text)
    conclusion = conclusion_match.group(1) if conclusion_match else "🟢"

    yes_match = re.search(r"\((\d+)/5\s*项\s*[✅]\)", text) or re.search(r"(\d+)/5\s*项\s*[✅]", text)
    yes_count = int(yes_match.group(1)) if yes_match else 0

    dim_status: Dict[str, str] = {}
    dim_source: Dict[str, str] = {}
    # 表格行： | 内容可复用 | ✅ | 证据 | 原文抽取 |
    for m in re.finditer(r"\|\s*(内容可复用|输入稳定|步骤清晰|输出可验证|真实案例)\s*\|\s*([✅⚠️❌])\s*\|\s*([^|]*?)\s*\|\s*(原文抽取|AI 推测|待补充|none)\s*\|", text):
        label, status, _evidence, source = m.groups()
        dim_status[DIM_LABELS[label]] = status
        dim_source[DIM_LABELS[label]] = source

    # Section 2 gaps
    s2_gaps = []
    s2_labels_map = {
        "目标用户": "目标用户",
        "触发场景": "触发场景",
        "用户痛点": "用户痛点",
        "使用后应达到": "预期效果",
        "不适合场景": "不适合场景",
    }
    for raw_label, display in s2_labels_map.items():
        pattern = rf"-\s*\*\*{re.escape(raw_label)}\*\*[:：]\s*([^\n]+)"
        m = re.search(pattern, text)
        if not m:
            s2_gaps.append(display)
            continue
        line = m.group(1)
        if "待补充" in line or "【待补充】" in line:
            s2_gaps.append(display)

    # Section 3 gaps
    s3_gaps = []
    s3_labels = {
        "形态": "形态",
        "输入": "输入",
        "输出": "输出",
        "关键动作数": "步骤",
        "需要的工具/账号": "工具/账号",
        "不需要的": "反面清单",
    }
    for raw_label, display in s3_labels.items():
        pattern = rf"-\s*\*\*{re.escape(raw_label)}\*\*[:：]\s*([^\n]+)"
        m = re.search(pattern, text)
        if not m:
            s3_gaps.append(display)
            continue
        line = m.group(1)
        if "待补充" in line or "【待补充】" in line:
            s3_gaps.append(display)

    # 步骤数
    step_match = re.search(r"\*\*关键动作数\*\*[:：]\s*(\d+)\s*步", text)
    step_count = int(step_match.group(1)) if step_match else 0

    # Section 4 Gap todos
    section4 = re.search(r"##\s*4️?⃣?\s*Gap\s*清单\s*(.*?)(?=\n##|\Z)", text, re.DOTALL)
    todos: List[str] = []
    if section4:
        for line in section4.group(1).splitlines():
            m = re.match(r"\s*-\s*\[\s*[ x]\s*\]\s*(.+)", line)
            if m:
                todos.append(m.group(1).strip())

    return EvalCard(
        path=path,
        title=title,
        conclusion=conclusion,
        yes_count=yes_count,
        dim_status=dim_status,
        dim_source=dim_source,
        section2_gaps=s2_gaps,
        section3_gaps=s3_gaps,
        section4_todos=todos,
        step_count=step_count,
    )


def collect_cards() -> List[EvalCard]:
    if not EVAL_DIR.exists():
        return []
    cards: List[EvalCard] = []
    for path in sorted(EVAL_DIR.glob("EVAL_*.md")):
        card = parse_eval_card(path)
        if card is not None:
            cards.append(card)
    return cards


# ── 报告生成 ───────────────────────────────────────────────────────

def build_report(cards: List[EvalCard], min_yes: int = 0) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = [
        "# 🚀 Skill 升级路线图",
        "",
        f"> 生成时间：{now}",
        f"> 来源目录：`{EVAL_DIR}`（共扫描 {len(cards)} 张 EVAL 卡）",
        "> 依据：Skill 成熟度模型 Level 0-5（见 references/maturity-model.md）",
        "",
    ]

    filtered = [c for c in cards if c.yes_count >= min_yes]
    if min_yes > 0:
        lines.append(f"> 过滤：只显示 yes_count ≥ {min_yes} 的候选（共 {len(filtered)} 个）")
        lines.append("")

    if not filtered:
        lines.extend([
            "## 📭 无匹配候选",
            "",
            "当前目录没有可评估的 EVAL 卡。请先运行：",
            "",
            "```bash",
            "python3 scripts/skill_detector.py",
            "```",
        ])
        return "\n".join(lines)

    # 按 Level 分组
    by_level: Dict[int, List[EvalCard]] = {i: [] for i in range(6)}
    for c in filtered:
        by_level[c.level].append(c)

    # 概览
    lines.extend([
        "## 📊 分布概览",
        "",
        "| Level | 名称 | 数量 |",
        "|---|---|---|",
    ])
    for lv in range(5, -1, -1):
        count = len(by_level[lv])
        lines.append(f"| {lv} | {LEVEL_NAMES[lv]} | {count} |")
    lines.append("")

    # 分组详情：从 Level 5 到 Level 0
    for lv in range(5, -1, -1):
        group = by_level[lv]
        if not group:
            continue
        lines.append(f"## Level {lv} · {LEVEL_NAMES[lv]}（{len(group)} 个）")
        lines.append("")
        for card in group:
            _emit_card_section(lines, card)
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 📖 Level 模型速查",
        "",
        "| Level | 说明 |",
        "|---|---|",
    ])
    for lv in range(6):
        lines.append(f"| {lv} | {LEVEL_NAMES[lv]} |")
    lines.append("")
    lines.append("详见 `第三层：技能层 (Skills)/knowledge-iteration-system/references/maturity-model.md`。")

    return "\n".join(lines)


def _emit_card_section(lines: List[str], card: EvalCard) -> None:
    file_link = card.path.name
    lines.append(f"### {card.conclusion} {card.title}")
    lines.append("")
    lines.append(f"- **评估卡**：[[{file_link}]]")
    lines.append(f"- **可行性得分**：{card.yes_count}/5 项 ✅")
    lines.append(f"- **判定明细**：" + " · ".join(
        f"{k}={v}" for k, v in card.dim_status.items()
    ))
    if card.section2_gaps:
        lines.append(f"- **Section 2 待补充**：{', '.join(card.section2_gaps)}")
    if card.section3_gaps:
        lines.append(f"- **Section 3 待补充**：{', '.join(card.section3_gaps)}")
    if card.section4_todos:
        lines.append(f"- **未关闭 Gap**：{len(card.section4_todos)} 项")
    lines.append("")
    lines.append("**下一步行动**：")
    for act in card.next_actions:
        lines.append(f"- [ ] {act}")
    lines.append("")


# ── 入口 ───────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Skill 升级路径工具（Phase 3）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将写入的路径与统计，不实际写入")
    parser.add_argument("--min-yes", type=int, default=0, help="只输出 yes_count ≥ N 的候选（默认 0）")
    args = parser.parse_args()

    print("=" * 40)
    print("🚀 Skill 升级路径工具")
    print("=" * 40)

    cards = collect_cards()
    report = build_report(cards, min_yes=args.min_yes)

    if args.dry_run:
        print(f"[dry-run] 将写入：{OUTPUT_FILE}")
        print(f"[dry-run] 扫描到 EVAL 卡：{len(cards)}")
        by_level: Dict[int, int] = {}
        for c in cards:
            by_level[c.level] = by_level.get(c.level, 0) + 1
        for lv in sorted(by_level.keys(), reverse=True):
            print(f"[dry-run]   Level {lv}: {by_level[lv]} 张")
        print(f"[dry-run] 报告字节数：{len(report.encode('utf-8'))}")
        return 0

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(report, encoding="utf-8")
    print(f"✅ 升级路线图已生成：{OUTPUT_FILE}")
    print(f"   扫描 EVAL 卡：{len(cards)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
