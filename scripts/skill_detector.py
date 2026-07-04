#!/usr/bin/env python3
"""Skill 可行性评估卡：从 Inbox 扫描候选内容，输出 EVAL 决策卡。

v2 重构（Phase 1）：
- 从"生成 DRAFT 模板"转为"输出 EVAL 可行性评估卡"
- 5 个 Section 严格按顺序，Section 2/3/4 由 Section 1 结论决定展开度
- 正则尽力而为，抽不到标"待补充"
- Section 1 LLM 判断（1 次调用），Section 2 规则优先 LLM 兜底（1 次调用）
- 批量处理 + 缓存 + 降级
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kis_config import iter_markdown_files, layer_path

INPUT_DIR = layer_path("inbox")
SKILLS_DIR = layer_path("skills")
OUTPUT = SKILLS_DIR / "待整理"
CACHE_FILE = OUTPUT / ".skill_detector_cache.json"

# ── Section 1: 五维度诊断 ──────────────────────────────────────────

@dataclass
class DimResult:
    """单个诊断维度的结果。"""
    status: str = "⚠️"       # ✅ / ⚠️ / ❌
    evidence: str = ""       # 原文证据（可为空）
    source: str = "regex"    # regex / llm / none


@dataclass
class Section1Result:
    """Section 1 完整诊断结果。"""
    reusable: DimResult = field(default_factory=DimResult)
    stable_input: DimResult = field(default_factory=DimResult)
    clear_steps: DimResult = field(default_factory=DimResult)
    verifiable_output: DimResult = field(default_factory=DimResult)
    real_case: DimResult = field(default_factory=DimResult)

    @property
    def yes_count(self) -> int:
        return sum(1 for d in self.dimensions() if d.status == "✅")

    @property
    def conclusion(self) -> str:
        c = self.yes_count
        if c >= 4:
            return "🔴 强烈建议做"
        if c >= 2:
            return "🟡 部分适合做"
        return "🟢 不建议单独做"

    @property
    def conclusion_key(self) -> str:
        c = self.yes_count
        if c >= 4:
            return "red"
        if c >= 2:
            return "yellow"
        return "green"

    def dimensions(self) -> List[DimResult]:
        return [self.reusable, self.stable_input, self.clear_steps,
                self.verifiable_output, self.real_case]

    def gaps(self) -> List[str]:
        """根据 ⚠️/❌ 项生成 gap 清单。"""
        gap_map = {
            "内容可复用": "补充可复用的场景描述（谁、什么时候、用什么输入）",
            "输入稳定": "补充典型输入示例（至少 2 个一致的输入格式）",
            "步骤清晰": "补充 ≥3 个明确的编号步骤",
            "输出可验证": '补充可验证的产出描述（做完后能得到什么）',
            "真实案例": "补充一个真实执行案例（含时间/结果数据）",
        }
        dim_names = ["内容可复用", "输入稳定", "步骤清晰", "输出可验证", "真实案例"]
        result = []
        for name, dim in zip(dim_names, self.dimensions()):
            if dim.status in ("⚠️", "❌"):
                result.append(gap_map.get(name, f"补充 {name} 相关证据"))
        if result:
            result.append("补充失败/不适用场景")
        return result


# ── Section 2: 服务谁·用在哪·达到什么效果 ──────────────────────────

# source 枚举——用户明确要求：AI 兜底后的 source 在渲染时显示为
# “原文未明确，AI 分析结果”。取值：
#   原文抽取 / regex → 显示 “原文抽取”
#   ai_infer / llm / “AI 推测”（旧名兼容） → 显示 “原文未明确，AI 分析结果”
#   待补充 / none → 显示 “待补充”

@dataclass
class Section2Field:
    value: str = ""
    source: str = "待补充"   # 原文抽取 / ai_infer / 待补充


def format_source_tag(source: str) -> str:
    """把内部 source 枚举转成 EVAL 卡上展示的人读标签。

    Section 1 仍保留“原文抽取”标签（那里的正则矢得住）；
    Section 2 / 3 按 Phase 3.2 新约定全面走 AI，将 ai_infer 显示为“AI 分析结果”。
    """
    return {
        "原文抽取": "原文抽取",
        "regex": "原文抽取",
        "ai_infer": "AI 分析结果",
        "AI 推测": "AI 分析结果",  # 旧名兼容
        "llm": "AI 分析结果",
        "待补充": "待补充",
        "none": "待补充",
    }.get(source, source)


@dataclass
class Section2Result:
    target_user: Section2Field = field(default_factory=Section2Field)
    trigger_scene: Section2Field = field(default_factory=Section2Field)
    pain_point: Section2Field = field(default_factory=Section2Field)
    expected_effect: Section2Field = field(default_factory=Section2Field)
    unsuitable_scene: Section2Field = field(default_factory=Section2Field)

    def all_fields(self) -> List[Tuple[str, Section2Field]]:
        return [
            ("目标用户", self.target_user),
            ("触发场景", self.trigger_scene),
            ("用户痛点", self.pain_point),
            ("使用后应达到", self.expected_effect),
            ("不适合场景", self.unsuitable_scene),
        ]


# ── Section 3: 建议的 Skill 形态 ──────────────────────────

@dataclass
class Section3Field:
    """Section 3 的单个字段，语义与 Section2Field 完全一致。"""
    value: str = ""
    source: str = "待补充"   # 原文抽取 / ai_infer / 待补充


@dataclass
class Section3Result:
    skill_type: Section3Field = field(default_factory=Section3Field)   # 形态
    inputs: Section3Field = field(default_factory=Section3Field)        # 输入
    outputs: Section3Field = field(default_factory=Section3Field)       # 输出
    step_count: int = 0                                                 # 关键动作数（步骤数）
    tools_required: Section3Field = field(default_factory=Section3Field)   # 需要的工具/账号
    not_required: Section3Field = field(default_factory=Section3Field)     # 不需要的

    def all_fields(self) -> List[Tuple[str, Section3Field]]:
        """按 EVAL 卡渲染顺序返回；步骤数不在此列表内（数字型单独渲染）。"""
        return [
            ("形态", self.skill_type),
            ("输入", self.inputs),
            ("输出", self.outputs),
            ("需要的工具/账号", self.tools_required),
            ("不需要的", self.not_required),
        ]


# ── Regex 抽取 ──────────────────────────────────────────────────────

SECTION1_RULES = [
    ("reusable", [
        r"(模板化|可复用|复用|照做|直接套|通用方法|SOP|标准流程|工作流|标准化|规范化|方法论|框架|实践|skill|Skill|harness|Harness)",
    ]),
    ("stable_input", [
        r"(输入[：:]\s*.+?[\n。])",
        r"(给定|传入|参数|API|配置|安装|部署|工具|平台|仓库|repo|github)",
    ]),
    ("clear_steps", [
        r"((?:^|\n)\s*(?:步骤\s*\d+|第[一二三四五六七八九十]+步)[：:].+){2,}",
        r"((?:第[一二三四五六七八九十]+步).+?){2,}",
        r"(流程[：:].+?\n.+?\n.+)",
        r"((?:^|\n)\s*\d+[.)、]\s+.+?(?:建立|整理|拆解|分析|生成|提炼|收集|输出|验证|复盘|设计|创建|使用|运行|记录|发布).+\n.+){2,}",
    ]),
    ("verifiable_output", [
        r"(产出|输出|生成|完成|做完.*?后|最终.*?得到|得到.*?一个|交付|交付物|得到.*?结果)",
    ]),
    ("real_case", [
        r"(月入\d|万粉|\d+万|\d+分钟|\d+小时|\d+%|案例|实测|亲测|我自己|我试|真实|演示|实战|Demo|demo)",
    ]),
]

SECTION2_RULES = [
    ("target_user", [
        r"(目标用户|目标人群|适用人群|适用对象|面向|推荐给|适用于)",
        r"(如果你是|你是一名|你是做|从事.+?的|做.+?的人)",
    ]),
    ("trigger_scene", [
        r"(当你需要|当你想|如果你想|每次需要|每次都要|每次.*?都)",
    ]),
    ("pain_point", [
        r"(痛点|头疼|最难|最烦|花很多时间|老是|总是|苦于|困扰|效率低|太慢|太麻烦)",
    ]),
    ("expected_effect", [
        r"(最终得到|最终产出|做完.*?后|完成后|预期.*?结果|预期.*?效果)",
    ]),
    ("unsuitable_scene", [
        r"(不适合|不适用|不建议用|不要用|不推荐用|别用|前提是|限制|局限)",
    ]),
]


def _regex_extract(content: str, patterns: List[str], max_len: int = 200, dotall: bool = False) -> Optional[str]:
    """用正则列表依次尝试，返回第一个匹配片段。"""
    flags = re.MULTILINE | (re.DOTALL if dotall else 0)
    for pat in patterns:
        m = re.search(pat, content, flags=flags)
        if m:
            text = re.sub(r"\s+", " ", m.group(0)).strip()
            return text[:max_len] + ("…" if len(text) > max_len else "")
    return None


def _count_occurrences(content: str, patterns: List[str]) -> int:
    count = 0
    for pat in patterns:
        count += len(re.findall(pat, content, flags=re.MULTILINE))
    return count


def _strong_evidence(evidence: str, min_len: int = 2) -> bool:
    """判断证据是否足够充分：长度 >= min_len 且不是过短/过于泛化的词。"""
    if not evidence or evidence == "（原文未明确）":
        return False
    cleaned = evidence.strip()
    # Only filter truly generic 1-2 char matches that carry no meaning
    too_weak = {"的", "了", "是", "我", "你", "他", "在", "和", "就", "也", "都", "只", "很", "更", "最", "太", "要", "会", "能", "可", "到", "对", "从", "把", "被", "让", "给", "用", "为", "因", "所", "或", "及", "与", "如", "若", "个", "些", "这", "那", "哪", "吗", "呢", "吧", "啊", "哦", "嗯", "哈", "但", "而", "却", "还", "又", "再", "才"}
    if cleaned in too_weak:
        return False
    return len(cleaned) >= min_len


def diagnose_section1_regex(content: str, name: str = "") -> Section1Result:
    """纯正则诊断 Section 1 五个维度。"""
    result = Section1Result()

    # 内容可复用 - requires strong evidence
    ev = _regex_extract(content, SECTION1_RULES[0][1])
    if ev and _strong_evidence(ev):
        result.reusable = DimResult(status="✅", evidence=ev, source="regex")
    elif ev:
        result.reusable = DimResult(status="⚠️", evidence=ev, source="regex")
    else:
        result.reusable = DimResult(status="⚠️", source="none")

    # Title heuristic: if title is a question/opinion, reusable likely overestimated
    if result.reusable.status == "✅":
        title = name or ""
        fm_match = re.search(r'^title:\s*"?(.+?)"?\s*$', content, re.MULTILINE)
        if fm_match:
            title = fm_match.group(1).strip()
        if not title:
            h1_match = re.search(r'^#\s+(.+?)$', content, re.MULTILINE)
            if h1_match:
                title = h1_match.group(1).strip()
        question_markers = ['？', '?', '吗', '到底', '真的', '是不是']
        if any(m in title for m in question_markers):
            result.reusable = DimResult(status="⚠️", evidence=ev or "标题含疑问/观点标记，可能非教程", source="regex")

    # 输入稳定 - requires at least 2 occurrences AND strong evidence
    occ = _count_occurrences(content, SECTION1_RULES[1][1])
    ev = _regex_extract(content, SECTION1_RULES[1][1], dotall=True)
    if occ >= 2 and ev and _strong_evidence(ev, min_len=2):
        result.stable_input = DimResult(status="✅", evidence=ev, source="regex")
    elif occ >= 1:
        result.stable_input = DimResult(status="⚠️", evidence=ev or "", source="regex")
    else:
        result.stable_input = DimResult(status="⚠️", source="none")

    # 步骤清晰
    ev = _regex_extract(content, SECTION1_RULES[2][1], max_len=400, dotall=True)
    if ev and len(re.findall(r"(?:\d+[.)、]|第[一二三四五六七八九十]+步)", ev)) >= 2:
        result.clear_steps = DimResult(status="✅", evidence=ev, source="regex")
    else:
        result.clear_steps = DimResult(status="⚠️", source="none")

    # 输出可验证 - requires strong evidence (not just '结果')
    ev = _regex_extract(content, SECTION1_RULES[3][1])
    if ev and _strong_evidence(ev):
        result.verifiable_output = DimResult(status="✅", evidence=ev, source="regex")
    elif ev:
        result.verifiable_output = DimResult(status="⚠️", evidence=ev, source="regex")
    else:
        result.verifiable_output = DimResult(status="⚠️", source="none")

    # 真实案例 - requires strong evidence (not just percentage/weak word)
    ev = _regex_extract(content, SECTION1_RULES[4][1])
    if ev and _strong_evidence(ev):
        result.real_case = DimResult(status="✅", evidence=ev, source="regex")
    elif ev:
        result.real_case = DimResult(status="⚠️", evidence=ev, source="regex")
    else:
        result.real_case = DimResult(status="⚠️", source="none")

    return result


def diagnose_section2_regex(content: str) -> Section2Result:
    """纯正则抽取 Section 2 五个字段。"""
    result = Section2Result()
    for field_name, patterns in SECTION2_RULES:
        ev = _regex_extract(content, patterns, max_len=100)
        field = getattr(result, field_name)
        if ev:
            field.value = ev
            field.source = "原文抽取"
        else:
            field.value = "待补充"
            field.source = "待补充"
        setattr(result, field_name, field)
    return result


# ── 内容预处理 ──────────────────────────────────────────────────────

def safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def strip_frontmatter(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:])
    return content


def clean_line(line: str) -> str:
    line = re.sub(r"<iframe.*?</iframe>", " ", line, flags=re.DOTALL | re.IGNORECASE)
    line = re.sub(r"<[^>]+>", " ", line)
    return re.sub(r"\s+", " ", line).strip()


def is_noise_line(line: str) -> bool:
    stripped = clean_line(line)
    if not stripped:
        return True
    noise_kw = ["发布时间", "编辑时间", "作者", "地区", "IP属地", "点赞", "收藏",
                "评论", "分享", "网页 DOM", "点点 AI", "基础数据", "采集备注",
                "改写结果", "口播优化", "结构化文案", "音频逐字稿"]
    if any(kw in stripped for kw in noise_kw):
        return True
    if re.search(r"iframe|bilibili|frameborder|allowfullscreen|transcript", stripped, re.IGNORECASE):
        return True
    if re.fullmatch(r"[A-Za-z0-9_:/?.=&%#|｜\- ]+", stripped):
        return True
    return False


def first_paragraph(content: str, max_chars: int = 280) -> str:
    body = strip_frontmatter(content)
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", body)]
    for p in paragraphs:
        if len(p) < 30 or p.startswith(("#", "---")):
            continue
        if re.match(r"^\*\*(?:笔记链接|标准链接|作者|采集时间|发布时间|标签)\*\*", p):
            continue
        if re.fullmatch(r"(?:https?://\S+\s*)+", p):
            continue
        if is_noise_line(p) or re.match(r"^#{2,}\s", p):
            continue
        return p[:max_chars] + ("…" if len(p) > max_chars else "")
    text = re.sub(r"\s+", " ", body).strip()
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


def best_one_liner(content: str, name: str) -> str:
    """从原文提取一句话用途描述。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, flags=re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if line.lower().startswith("description:"):
                desc = re.sub(r"\s+", " ", line.split(":", 1)[1].strip().strip("'\"")).strip()
                sentence = re.split(r"[。！？!?]\s*", desc, maxsplit=1)[0]
                if len(sentence) >= 12:
                    return sentence[:220]
    para = first_paragraph(content)
    if not para:
        return f"来自《{name}》，需人工补一句话用途。"
    return re.split(r"[。！？!?]\s*", para, maxsplit=1)[0][:220]


def extract_steps(content: str, limit: int = 8) -> List[str]:
    body = strip_frontmatter(content)
    candidates = []
    for line in body.splitlines():
        raw = line.strip()
        if not raw or is_noise_line(raw):
            continue
        # Skip frontmatter-like lines (tags, metadata)
        if re.match(r"^\d+[.)、]\s*$", raw):
            continue
        if re.match(r"^(?:tags|author|source|published|created|description):", raw, re.IGNORECASE):
            continue
        is_step = bool(re.match(r"^(?:\d+[.)、]|[-*•])\s+", raw))
        has_action = bool(re.search(r"建立|整理|拆解|分析|生成|提炼|收集|输出|验证|复盘|设计|创建|使用|运行|记录|发布", raw))
        if is_step and has_action:
            cleaned = clean_line(raw)
            if 12 <= len(cleaned) <= 120 and cleaned not in candidates:
                candidates.append(cleaned)
        if len(candidates) >= limit:
            break
    if candidates:
        return candidates
    sentences = re.split(r"[。！？!?]\s*", re.sub(r"\s+", " ", body))
    for sentence in sentences:
        if re.search(r"第一|第二|第三|步骤|流程|先|然后|最后|建立|拆解|生成|提炼", sentence):
            cleaned = clean_line(sentence)
            if 12 <= len(cleaned) <= 140 and cleaned not in candidates:
                candidates.append(cleaned)
        if len(candidates) >= limit:
            break
    return candidates


def extract_prompts(content: str, limit: int = 3) -> List[str]:
    prompts = []
    task_blocks = re.findall(
        r"(?:^|\n)#{0,6}\s*任务\s*\d+\s*提示词\s*\n+(.+?)(?=\n#{0,6}\s*任务\s*\d+\s*提示词|\n#{1,6}\s+|\n###\s*三、|\n---|$)",
        content, flags=re.DOTALL | re.IGNORECASE,
    )
    for block in task_blocks:
        text = re.sub(r"\n{3,}", "\n\n", block).strip()
        if len(text) >= 40 and not is_noise_line(text[:120]):
            prompts.append(text[:1500])
        if len(prompts) >= limit:
            return prompts[:limit]
    for block in re.findall(r"```(?:\w+)?\n(.*?)```", content, flags=re.DOTALL):
        if re.search(r"prompt|提示词|请你|帮我|你是|任务", block, re.IGNORECASE):
            prompts.append(block.strip()[:1000])
    if len(prompts) >= limit:
        return prompts[:limit]
    for pattern in [r"(?:prompt|提示词|指令)[：:]\s*(.+?)(?:\n#{1,4}|\n\n|$)",
                    r"(请你.+?)(?:\n\n|$)"]:
        for match in re.findall(pattern, content, flags=re.IGNORECASE | re.DOTALL):
            text = re.sub(r"\s+", " ", match).strip()
            if len(text) >= 20 and text not in prompts:
                prompts.append(text[:1000])
            if len(prompts) >= limit:
                return prompts[:limit]
    return prompts[:limit]


# ── Skill 形态推断 ──────────────────────────────────────────────────

SKILL_TYPE_RULES: Dict[str, List[str]] = {
    "工具调用型": ["api", "工具", "调用", "接口", "请求", "命令行", "cli", "mcp"],
    "工作流型": ["工作流", "流程", "步骤", "自动化", "编排", "流水线"],
    "判断诊断型": ["判断", "诊断", "评估", "打分", "检查", "审核", "筛选"],
    "内容生成型": ["生成", "写作", "创作", "内容", "文案", "脚本", "输出"],
    "知识梳理型": ["知识", "整理", "梳理", "归纳", "总结", "分类", "体系"],
}


def infer_skill_type(content: str, name: str) -> str:
    text = f"{name} {content}".lower()
    scores = []
    for skill_type, keywords in SKILL_TYPE_RULES.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score:
            scores.append((score, skill_type))
    return sorted(scores, reverse=True)[0][1] if scores else "待判断"


# ── Section 3 正则抽取 ─────────────────────────────────────────────

def _regex_first_match(text: str, patterns: List[str]) -> Optional[str]:
    """按顺序试每个 pattern，返回第一个非空捕获。"""
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        val = (m.group(1) if m.groups() else m.group(0)).strip()
        # 太长截断；剥去 markdown 前缀符号
        val = re.sub(r"\s+", " ", val).strip("：: 　-*")
        if 2 <= len(val) <= 80 and not is_noise_line(val):
            return val
    return None


SECTION3_INPUT_PATTERNS = [
    r"输入[：:]\s*(.+?)(?:\n|$)",
    r"需要[：:]\s*(.+?)(?:\n|$)",
    r"(?:准备|前置)[：:]\s*(.+?)(?:\n|$)",
]
SECTION3_OUTPUT_PATTERNS = [
    r"输出[：:]\s*(.+?)(?:\n|$)",
    r"产出[：:]\s*(.+?)(?:\n|$)",
    r"交付[物]?[：:]\s*(.+?)(?:\n|$)",
    r"(?:最终|得到)[：:]?\s*(.+?)(?:\n|$)",
]
SECTION3_TOOLS_PATTERNS = [
    r"(?:工具|需要的工具|所需工具)[：:]\s*(.+?)(?:\n|$)",
    r"(?:依赖|前置依赖|技术栈)[：:]\s*(.+?)(?:\n|$)",
]
SECTION3_NOT_REQUIRED_PATTERNS = [
    r"不需要[：:]\s*(.+?)(?:\n|$)",
    r"(?:无需|免|不用|不依赖)[：:]?\s*(.+?)(?:\n|$)",
]


def diagnose_section3_regex(content: str, name: str) -> Section3Result:
    """尽力从原文里抽 Section 3 字段；抽不到的字段留待 LLM 兜底。"""
    result = Section3Result()

    # 形态：规则强分类，一般都能得出结果——所以标 "原文抽取"（哪怕是启发式）
    st = infer_skill_type(content, name)
    result.skill_type = Section3Field(value=st, source="原文抽取")

    # 步骤数：直接借用 extract_steps
    steps = extract_steps(content)
    result.step_count = len(steps)

    # 输入 / 输出 / 工具 / 反面清单：正则找不到就留 待补充
    v = _regex_first_match(content, SECTION3_INPUT_PATTERNS)
    if v:
        result.inputs = Section3Field(value=v, source="原文抽取")

    v = _regex_first_match(content, SECTION3_OUTPUT_PATTERNS)
    if v:
        result.outputs = Section3Field(value=v, source="原文抽取")

    v = _regex_first_match(content, SECTION3_TOOLS_PATTERNS)
    if v:
        result.tools_required = Section3Field(value=v, source="原文抽取")

    v = _regex_first_match(content, SECTION3_NOT_REQUIRED_PATTERNS)
    if v:
        result.not_required = Section3Field(value=v, source="原文抽取")

    return result


# ── 缓存 ────────────────────────────────────────────────────────────

def load_cache() -> Dict[str, Any]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_cache(data: Dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── LLM Bridge ──────────────────────────────────────────────────────

def prepare_llm_prompt_section1(candidates: List[Dict[str, Any]]) -> str:
    """为 Section 1 的 ⚠️ 维度准备批量 LLM prompt。"""
    lines = ["请分析以下内容的 Skill 化可行性。对每个维度，返回 ✅（满足）/ ⚠️（不确定）/ ❌（不满足），并附一句证据。\n"]
    for i, c in enumerate(candidates):
        dims = c["s1"]
        dim_desc = []
        for d in dims:
            if d["status"] == "⚠️" and d["source"] == "none":
                dim_desc.append(f"  - {d['name']}: 正则未匹配到证据")
        if not dim_desc:
            continue
        lines.append(f"## 候选 {i + 1}: {c['name']}")
        lines.append(f"原文摘要: {c['preview'][:600]}")
        lines.append("需判断的维度:")
        lines.extend(dim_desc)
        lines.append("")
    lines.append("请对每个候选的每个维度，返回 JSON 格式：")
    lines.append('{"candidates": [{"name": "...", "dims": {"维度名": {"status": "✅/⚠️/❌", "evidence": "一句话证据"}}}]}')
    return "\n".join(lines)


def prepare_llm_prompt_section2(candidates: List[Dict[str, Any]]) -> str:
    """为 Section 2 的待补充字段准备批量 LLM prompt。"""
    lines = ['请分析以下内容的适用场景。对每个字段，从原文推断或标注"待补充"。\n']
    for i, c in enumerate(candidates):
        fields = c.get("s2", {})
        missing = [(n, v) for n, v in fields.items() if v["source"] == "待补充"]
        if not missing:
            continue
        lines.append(f"## 候选 {i + 1}: {c['name']}")
        lines.append(f"原文摘要: {c['preview'][:600]}")
        lines.append("待补充字段:")
        for name, _ in missing:
            lines.append(f"  - {name}")
        lines.append("")
    lines.append("请对每个候选的每个字段，返回 JSON 格式：")
    lines.append('{"candidates": [{"name": "...", "fields": {"字段名": "推断内容"}}]}')
    return "\n".join(lines)


# ── EVAL 卡片生成 ───────────────────────────────────────────────────

def render_dimension_row(name: str, dim: DimResult) -> str:
    source_tag = format_source_tag(dim.source)
    ev = dim.evidence or "（原文未明确）"
    return f"| {name} | {dim.status} | {ev} | {source_tag} |"


def render_section1(result: Section1Result) -> str:
    lines = [
        "## 1️⃣ Skill 化可行性诊断",
        "",
        "| 维度 | 判定 | 证据 | 来源 |",
        "|------|------|------|------|",
        render_dimension_row("内容可复用", result.reusable),
        render_dimension_row("输入稳定", result.stable_input),
        render_dimension_row("步骤清晰", result.clear_steps),
        render_dimension_row("输出可验证", result.verifiable_output),
        render_dimension_row("真实案例", result.real_case),
        "",
        f"**综合结论：{result.conclusion}**（{result.yes_count}/5 项 ✅）",
        "",
    ]
    return "\n".join(lines)


def render_section2(result: Section2Result) -> str:
    lines = [
        "## 2️⃣ 服务谁 · 用在哪 · 达到什么效果",
        "",
    ]
    for label, fld in result.all_fields():
        tag = format_source_tag(fld.source)
        value = fld.value if fld.value else "待补充"
        lines.append(f"- **{label}**：{value}【{tag}】")
    lines.append("")
    return "\n".join(lines)


def render_section3(s3: Section3Result) -> str:
    lines = [
        "## 3️⃣ 建议的 Skill 形态",
        "",
    ]
    # 形态
    tag = format_source_tag(s3.skill_type.source)
    lines.append(f"- **形态**：{s3.skill_type.value or '待判断'}【{tag}】")

    # 输入
    tag = format_source_tag(s3.inputs.source)
    value = s3.inputs.value if s3.inputs.value else "待补充"
    lines.append(f"- **输入**：{value}【{tag}】")

    # 输出
    tag = format_source_tag(s3.outputs.source)
    value = s3.outputs.value if s3.outputs.value else "待补充"
    lines.append(f"- **输出**：{value}【{tag}】")

    # 关键动作数（Phase 3.2：step_count 也由 AI 给出）
    if s3.step_count > 0:
        lines.append(f"- **关键动作数**：{s3.step_count} 步【AI 分析结果】")
    else:
        lines.append("- **关键动作数**：待补充【待补充】")

    # 需要的工具/账号
    tag = format_source_tag(s3.tools_required.source)
    value = s3.tools_required.value if s3.tools_required.value else "待补充"
    lines.append(f"- **需要的工具/账号**：{value}【{tag}】")

    # 不需要的
    tag = format_source_tag(s3.not_required.source)
    value = s3.not_required.value if s3.not_required.value else "待补充"
    lines.append(f"- **不需要的**：{value}【{tag}】")

    lines.append("")
    return "\n".join(lines)


def render_section4(gaps: List[str]) -> str:
    lines = ["## 4️⃣ Gap 清单", ""]
    for gap in gaps:
        lines.append(f"- [ ] {gap}")
    lines.append("")
    return "\n".join(lines)


def render_section5(name: str, content: str, candidate: Dict[str, Any]) -> str:
    oneliner = candidate.get("summary", best_one_liner(content, name))
    steps = extract_steps(content)
    prompts = extract_prompts(content)
    lines = [
        "## 5️⃣ 已抽取素材",
        "",
        f"**一句话用途**：{oneliner}",
        "",
    ]
    if steps:
        lines.append("**原文步骤**：")
        for i, s in enumerate(steps, 1):
            lines.append(f"{i}. {s}")
    else:
        lines.append("**原文步骤**：原文未提供可复用步骤")
    lines.append("")
    if prompts:
        lines.append("**Prompt 候选**：")
        for i, p in enumerate(prompts, 1):
            lines.append(f"\n### 模板 {i}\n\n```text\n{p}\n```")
    else:
        lines.append("**Prompt 候选**：原文未提供 Prompt 模板")
    lines.append("")
    lines.append(f"**参考链接**：[[{name}]]")
    lines.append("")
    return "\n".join(lines)


def generate_eval_card(name: str, content: str, s1: Section1Result, s2: Section2Result,
                       s3: Section3Result, candidate: Dict[str, Any]) -> str:
    """生成完整 EVAL 卡片。"""
    conclusion_key = s1.conclusion_key
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    parts = [
        f"# 🎯 Skill 可行性评估卡：{name}",
        "",
        f"> 评估结论：{s1.conclusion} · 评估时间：{now}",
        "",
        render_section1(s1),
    ]

    if conclusion_key in ("red", "yellow"):
        parts.append(render_section2(s2))
        parts.append(render_section3(s3))
        parts.append(render_section4(s1.gaps()))

    parts.append(render_section5(name, content, candidate))
    parts.append(f"*评估时间：{now}*")
    parts.append("")

    return "\n".join(parts)


# ── README 生成 ─────────────────────────────────────────────────────

def generate_readme(evals: List[Dict[str, Any]]) -> str:
    red, yellow, green = [], [], []
    for ev in evals:
        entry = ev.copy()
        if entry["conclusion"] == "red":
            red.append(entry)
        elif entry["conclusion"] == "yellow":
            yellow.append(entry)
        else:
            green.append(entry)

    lines = [
        "# 🎯 Skill 可行性评估索引",
        "",
        f"> 最近评估：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"| 分组 | 数量 |",
        f"|------|------|",
        f"| 🔴 强烈建议做 | {len(red)} |",
        f"| 🟡 部分适合做 | {len(yellow)} |",
        f"| 🟢 不建议单独做 | {len(green)} |",
        "",
    ]

    for label, group, emoji in [("🔴 强烈建议做（≥4 项 ✅）", red, "🔴"),
                                  ("🟡 部分适合做（2–3 项 ✅）", yellow, "🟡"),
                                  ("🟢 不建议单独做（≤1 项 ✅）", green, "🟢")]:
        lines.append(f"## {label}")
        lines.append("")
        if not group:
            lines.append("暂无")
        else:
            lines.append("| 评估卡 | 得分 | 最近评估 |")
            lines.append("|--------|------|----------|")
            for ev in group:
                lines.append(f"| [[EVAL_{ev['name']}]] | {ev['yes_count']}/5 | {ev['eval_time']} |")
        lines.append("")

    lines.append("## 使用说明")
    lines.append("")
    lines.append("1. 🔴 强烈建议做：优先投入时间，按 Gap 清单补齐后即可创建 Skill 草案。")
    lines.append("2. 🟡 部分适合做：先补 Gap 再判断，或拆成更小的子 Skill。")
    lines.append("3. 🟢 不建议单独做：更适合放想法追踪或暂存，不单独建 Skill。")
    lines.append("")
    lines.append(f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    return "\n".join(lines)


# ── 主流程 ──────────────────────────────────────────────────────────

def scan_candidates(min_score: int = 3) -> List[Dict[str, Any]]:
    """扫描 Inbox，返回候选列表。"""
    candidates = []
    if not INPUT_DIR.exists():
        return candidates

    # 关键词打分（保留旧逻辑作为初筛）
    SKILL_KEYWORDS = ["方法", "方法论", "流程", "步骤", "模板", "框架", "prompt", "提示词", "工作流", "指南", "教程", "技巧", "系统"]

    for fpath in iter_markdown_files(INPUT_DIR):
        try:
            content = safe_read(fpath)
            text = content.lower()
            score = sum(1 for kw in SKILL_KEYWORDS if kw.lower() in text)
            if re.search(r"\d\. |第一|第二|第三|步骤", content):
                score += 2
            if extract_steps(content):
                score += 2
            if extract_prompts(content):
                score += 2
            score = min(score, 10)
            if score < min_score:
                continue
            candidates.append({
                "name": fpath.stem,
                "path": str(fpath),
                "content": content,
                "preview": first_paragraph(content, 600),
                "score": score,
            })
        except Exception:
            pass
    return sorted(candidates, key=lambda x: x["score"], reverse=True)


def process_candidates(llm_mode: str = "off") -> Tuple[List[Dict[str, Any]], Path]:
    """主处理流程：扫描 → 正则诊断 → LLM 兜底 → 生成 EVAL 卡 → 生成 README。

    llm_mode:
      - "off" ：不调用任何 LLM
      - "auto"：kis_llm 可用则走 API，否则降级文件桥
      - "api" ：强制 kis_llm API，不可用则报错并降级
      - "file"：强制文件桥
    """
    print("🔍 正在扫描 Inbox 中的 Skill 候选...")
    candidates = scan_candidates()
    if not candidates:
        print("⚠️ 未检测到可评估的 Skill 候选。")
        return [], OUTPUT

    llm_on = llm_mode != "off"
    cache = load_cache()
    evals = []
    llm_needed_s1 = []
    llm_needed_s2 = []
    llm_needed_s3 = []

    for c in candidates:
        content = c["content"]
        name = c["name"]

        # 正则诊断 Section 1
        s1 = diagnose_section1_regex(content, name)

        # 检查缓存
        cache_key = f"{name}:{hash(content) % 100000}"
        if cache_key in cache:
            cached = cache[cache_key]
            if "s1" in cached:
                for dim_name, data in cached["s1"].items():
                    dim = getattr(s1, dim_name)
                    dim.status = data.get("status", dim.status)
                    dim.evidence = data.get("evidence", dim.evidence)
                    dim.source = data.get("source", dim.source)

        # 收集需要 LLM 的维度
        has_llm_gap_s1 = any(d.status == "⚠️" and d.source == "none" for d in s1.dimensions())
        if has_llm_gap_s1 and llm_on:
            llm_needed_s1.append({
                "name": name,
                "preview": c["preview"],
                "s1": [{"name": n, "status": d.status, "source": d.source}
                       for n, d in zip(["reusable", "stable_input", "clear_steps", "verifiable_output", "real_case"],
                                       s1.dimensions())],
            })

        # Section 2：不走正则，交给 AI 全字段推断（Phase 3.2）
        s2 = Section2Result()
        if llm_on:
            llm_needed_s2.append({
                "name": name,
                "preview": c["preview"],
                "s2": {},
            })

        # Section 3：同样全走 AI，包括 skill_type 与 step_count（Phase 3.2）
        s3 = Section3Result()
        if llm_on:
            llm_needed_s3.append({
                "name": name,
                "preview": c["preview"],
                "s3": {},
            })

        evals.append({
            "name": name,
            "content": content,
            "s1": s1,
            "s2": s2,
            "s3": s3,
            "score": c["score"],
            "yes_count": s1.yes_count,
            "conclusion": s1.conclusion_key,
            "eval_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

    # LLM 兜底（如果启用）
    if llm_on and (llm_needed_s1 or llm_needed_s2 or llm_needed_s3):
        _run_llm_augmentation(evals, llm_needed_s1, llm_needed_s2, llm_needed_s3, llm_mode)

    # 更新缓存
    for ev in evals:
        cache_key = f"{ev['name']}:{hash(ev['content']) % 100000}"
        cache[cache_key] = {
            "s1": {n: {"status": d.status, "evidence": d.evidence, "source": d.source}
                   for n, d in zip(["reusable", "stable_input", "clear_steps", "verifiable_output", "real_case"],
                                   ev["s1"].dimensions())},
            "eval_time": ev["eval_time"],
        }
    save_cache(cache)

    # 生成 EVAL 卡片
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for ev in evals:
        card = generate_eval_card(ev["name"], ev["content"], ev["s1"], ev["s2"], ev["s3"],
                                  {"summary": best_one_liner(ev["content"], ev["name"])})
        card_path = OUTPUT / f"EVAL_{ev['name']}.md"
        card_path.write_text(card, encoding="utf-8")

    # 生成 README
    readme = generate_readme(evals)
    readme_path = OUTPUT / "README.md"
    readme_path.write_text(readme, encoding="utf-8")

    return evals, OUTPUT


def _announce_llm_mode(mode: str) -> None:
    """启用 --llm 时，季式提醒当前路弄。"""
    try:
        import kis_llm  # type: ignore
    except Exception:
        kis_llm = None  # type: ignore

    print(f"🤖 --llm 已启用（模式：{mode}）")
    if kis_llm is not None:
        try:
            ok, msg = kis_llm.probe()
        except Exception as exc:  # pragma: no cover
            ok, msg = False, f"probe error: {exc}"
    else:
        ok, msg = False, "kis_llm 未引入"

    if mode == "auto":
        if ok:
            print(f"   → kis_llm API 可用（{msg}），将自动调用批量 API。")
        else:
            print(f"   → kis_llm 不可用（{msg}），降级为文件桥。")
    elif mode == "api":
        if ok:
            print(f"   → 强制使用 kis_llm API（{msg}）。")
        else:
            print(f"   ⚠️ kis_llm 不可用（{msg}），将抛错并降级文件桥。")
    elif mode == "file":
        print("   → 强制使用文件桥：prompt 写到 `.llm_prompt.txt`，手动填 `.llm_result.json` 后重跑。")
    print("")


def _resolve_llm_route(mode: str) -> str:
    """根据 mode 和 kis_llm.probe() 决定实际路由 -> 'api' | 'file'."""
    if mode == "file":
        return "file"
    try:
        import kis_llm  # type: ignore
        ok, _ = kis_llm.probe()
    except Exception:
        ok = False
    if mode == "auto":
        return "api" if ok else "file"
    if mode == "api":
        if not ok:
            print("   ⚠️ --llm=api 但 kis_llm 不可用，自动降级到文件桥。")
            return "file"
        return "api"
    return "file"


def _run_llm_augmentation(evals: List[Dict[str, Any]],
                          s1_needs: List[Dict[str, Any]],
                          s2_needs: List[Dict[str, Any]],
                          s3_needs: List[Dict[str, Any]],
                          mode: str) -> None:
    """统一入口：根据 mode 选路由（kis_llm API 批量 或 文件桥），把 LLM 结果回填进 evals。"""
    if not (s1_needs or s2_needs or s3_needs):
        return
    route = _resolve_llm_route(mode)
    print(f"🤖 LLM 兜底（路由：{route}）：Section 1 {len(s1_needs)} 个，Section 2 {len(s2_needs)} 个，Section 3 {len(s3_needs)} 个…")
    if route == "api":
        _augment_via_kis_llm(evals, s1_needs, s2_needs, s3_needs)
    else:
        _augment_via_file_bridge(evals, s1_needs, s2_needs, s3_needs)


def _augment_via_kis_llm(evals: List[Dict[str, Any]],
                         s1_needs: List[Dict[str, Any]],
                         s2_needs: List[Dict[str, Any]],
                         s3_needs: List[Dict[str, Any]]) -> None:
    """调 kis_llm.call_section{1,2,3}_batch。失败时安静降级为正则结果。"""
    try:
        import kis_llm  # type: ignore
    except Exception as exc:
        print(f"   ⚠️ kis_llm 导入失败：{exc}，保持正则结果。")
        return

    # 将候选映射到 eval 以便回填
    eval_by_name = {ev["name"]: ev for ev in evals}

    if s1_needs:
        items = [{"name": n["name"], "content": eval_by_name[n["name"]]["content"]}
                 for n in s1_needs if n["name"] in eval_by_name]
        try:
            result = kis_llm.call_section1_batch(items)
        except kis_llm.LLMUnavailable as exc:
            print(f"   ⚠️ Section 1 LLM 不可用：{exc}，保持正则结果。")
            result = {}
        for name, dims in result.items():
            ev = eval_by_name.get(name)
            if not ev or not isinstance(dims, dict):
                continue
            # kis_llm 维度名到 skill_detector 字段名的映射
            dim_name_map = {
                "reusable": "reusable",
                "input_stable": "stable_input",
                "steps_clear": "clear_steps",
                "output_verifiable": "verifiable_output",
                "has_case": "real_case",
            }
            for src_key, dst_key in dim_name_map.items():
                data = dims.get(src_key)
                if not isinstance(data, dict):
                    continue
                dim = getattr(ev["s1"], dst_key, None)
                if dim and dim.status == "⚠️" and dim.source == "none":
                    verdict = data.get("verdict", "⚠️")
                    reason = data.get("reason", "")
                    dim.status = verdict
                    dim.evidence = reason
                    dim.source = "llm"
            ev["yes_count"] = ev["s1"].yes_count
            ev["conclusion"] = ev["s1"].conclusion_key

    if s2_needs:
        items = [{"name": n["name"], "content": eval_by_name[n["name"]]["content"]}
                 for n in s2_needs if n["name"] in eval_by_name]
        try:
            result = kis_llm.call_section2_batch(items)
        except kis_llm.LLMUnavailable as exc:
            print(f"   ⚠️ Section 2 LLM 不可用：{exc}，保持正则结果。")
            result = {}
        # kis_llm 字段名 → skill_detector 字段名
        field_map = {
            "target_user": "target_user",
            "trigger_scenario": "trigger_scene",
            "pain_point": "pain_point",
            "expected_outcome": "expected_effect",
            "unfit_scenario": "unsuitable_scene",
        }
        for name, fields in result.items():
            ev = eval_by_name.get(name)
            if not ev or not isinstance(fields, dict):
                continue
            for src_key, dst_key in field_map.items():
                value = fields.get(src_key)
                if not value or value == "null":
                    continue
                f = getattr(ev["s2"], dst_key, None)
                if f is None:
                    continue
                # Phase 3.2：Section 2 全样本走 AI，不再需要 "待补充" 守卫
                f.value = str(value)
                f.source = "ai_infer"

    # ── Section 3 LLM 兜底 ──
    if s3_needs:
        items = [{"name": n["name"], "content": eval_by_name[n["name"]]["content"]}
                 for n in s3_needs if n["name"] in eval_by_name]
        try:
            result = kis_llm.call_section3_batch(items)
        except kis_llm.LLMUnavailable as exc:
            print(f"   ⚠️ Section 3 LLM 不可用：{exc}，保持正则结果。")
            result = {}
        # kis_llm 字段名 → Section3Result 属性名（Phase 3.2）
        s3_field_map = {
            "skill_type": "skill_type",
            "inputs": "inputs",
            "outputs": "outputs",
            "tools_required": "tools_required",
            "not_required": "not_required",
        }
        for name, fields in result.items():
            ev = eval_by_name.get(name)
            if not ev or not isinstance(fields, dict):
                continue
            # 先处理 step_count（数字字段，不使用 Field 结构）
            raw_step = fields.get("step_count")
            if isinstance(raw_step, (int, float)) and int(raw_step) >= 0:
                ev["s3"].step_count = int(raw_step)
            elif isinstance(raw_step, str):
                try:
                    ev["s3"].step_count = max(0, int(raw_step.strip()))
                except (ValueError, AttributeError):
                    pass
            for src_key, dst_key in s3_field_map.items():
                value = fields.get(src_key)
                if value is None or value == "null" or str(value).strip() == "":
                    continue
                f = getattr(ev["s3"], dst_key, None)
                if f is None:
                    continue
                # Phase 3.2：Section 3 不再区分“待补充”——AI 输出就直接覆盖（没正则抽取一层了）
                f.value = str(value)
                f.source = "ai_infer"


def _augment_via_file_bridge(evals: List[Dict[str, Any]],
                             s1_needs: List[Dict[str, Any]],
                             s2_needs: List[Dict[str, Any]],
                             s3_needs: List[Dict[str, Any]]) -> None:
    """历史文件桥机制。维持向后兼容。

    注：文件桥只处理 Section 1/2；Section 3 需要 LLM 时直接跳过并提示，
    因为文件桥场景下让用户手拷 3 个 section 的 prompt 成本过高。用户可切 --llm=api/auto 走 API。
    """
    if s3_needs:
        print(f"   ℹ️  Section 3 有 {len(s3_needs)} 个字段需要 LLM，但文件桥模式不支持 s3。请用 --llm=auto 或 --llm=api。")
    if s1_needs:
        prompt = prepare_llm_prompt_section1(s1_needs)
        llm_result = _call_llm(prompt)
        if llm_result:
            try:
                data = json.loads(llm_result)
                for item in data.get("candidates", []):
                    name = item["name"]
                    dims = item.get("dims", {})
                    for ev in evals:
                        if ev["name"] == name:
                            for dim_name, dim_data in dims.items():
                                dim = getattr(ev["s1"], dim_name, None)
                                if dim and dim.status == "⚠️" and dim.source == "none":
                                    dim.status = dim_data.get("status", "⚠️")
                                    dim.evidence = dim_data.get("evidence", "")
                                    dim.source = "llm"
                            ev["yes_count"] = ev["s1"].yes_count
                            ev["conclusion"] = ev["s1"].conclusion_key
            except json.JSONDecodeError:
                print("⚠️ LLM Section 1 返回格式异常，使用正则结果。")

    if s2_needs:
        prompt = prepare_llm_prompt_section2(s2_needs)
        llm_result = _call_llm(prompt)
        if llm_result:
            try:
                data = json.loads(llm_result)
                for item in data.get("candidates", []):
                    name = item["name"]
                    fields = item.get("fields", {})
                    for ev in evals:
                        if ev["name"] == name:
                            field_map = {
                                "目标用户": "target_user",
                                "触发场景": "trigger_scene",
                                "用户痛点": "pain_point",
                                "使用后应达到": "expected_effect",
                                "不适合场景": "unsuitable_scene",
                            }
                            for field_name, value in fields.items():
                                attr = field_map.get(field_name, field_name)
                                f = getattr(ev["s2"], attr, None)
                                if f and f.source == "待补充" and value and value != "待补充":
                                    f.value = value
                                    f.source = "AI 推测"
            except json.JSONDecodeError:
                print("⚠️ LLM Section 2 返回格式异常，使用正则结果。")


def _call_llm(prompt: str) -> Optional[str]:
    """LLM 调用桥接（文件桥机制）：写入 prompt 文件，等待外部填充结果。

    ⬆️ Phase 2 提醒：本函数不直接调用 kis_llm。文件桥适合 **无 API key** 并且想手动拷贴到
    其他 AI 工具的场景。有 API key 且允许自动外发时，下一代实现会切到
    kis_llm.call_section1 / call_section2（见 SKILL.md “LLM 兼底调用”章节）。

    降级策略：如果 LLM 不可用，返回 None，保持正则结果。
    """
    prompt_file = OUTPUT / ".llm_prompt.txt"
    result_file = OUTPUT / ".llm_result.json"

    try:
        prompt_file.write_text(prompt, encoding="utf-8")
    except OSError:
        return None

    # 检查是否已有结果（之前跑过）
    if result_file.exists():
        try:
            return result_file.read_text(encoding="utf-8")
        except OSError:
            pass

    # 降级：返回 None
    print(f"  ℹ️ LLM prompt 已写入 {prompt_file}，降级使用正则结果。")
    print(f"  💡 将 LLM 分析结果写入 {result_file} 后重新运行即可合并。")
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Skill 可行性评估卡生成器")
    parser.add_argument(
        "--llm",
        nargs="?",
        const="auto",
        default="off",
        choices=["off", "auto", "api", "file"],
        help=("LLM 兜底模式：off=不启用（默认）; auto=kis_llm 可用则 API 否则降级文件桥; "
              "api=强制 kis_llm API; file=强制文件桥。不传值时默认 auto。")
    )
    parser.add_argument("--min-score", type=int, default=3, help="最低关键词得分阈值（默认 3）")
    args = parser.parse_args()

    print("=" * 40)
    print("🎯 Skill 可行性评估")
    print("=" * 40)

    if args.llm != "off":
        _announce_llm_mode(args.llm)

    evals, output_dir = process_candidates(llm_mode=args.llm)

    if evals:
        red = sum(1 for e in evals if e["conclusion"] == "red")
        yellow = sum(1 for e in evals if e["conclusion"] == "yellow")
        green = sum(1 for e in evals if e["conclusion"] == "green")
        print(f"\n✅ 评估完成：{len(evals)} 个候选")
        print(f"   🔴 {red} 个强烈建议做")
        print(f"   🟡 {yellow} 个部分适合做")
        print(f"   🟢 {green} 个不建议单独做")
        print(f"   位置：{output_dir}")
    else:
        print("⚠️ 未检测到可评估的 Skill 候选。")


if __name__ == "__main__":
    main()
