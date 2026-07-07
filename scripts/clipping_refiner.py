#!/usr/bin/env python3
"""Clippings 内容提炼流水线：内容类型、观点、方法、金句和资产化建议。

输出目标（本次优化重点）：
- “一句话摘要”结构化展示（内容类型 / 谁在讲 / 核心主张 / 主要方法）
- “可复用方法”统一为有序列表，去噪去平台元数据
- “原文金句”只保留强候选，弱证据整段不输出，避免占位噪音
- “下一步”除了标准动作外，追加基于原文的贴合建议
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from kis_config import is_stopword, iter_markdown_files, subfolder_path
from kis_config import content_types as _content_types
from kis_config import tag_rules as _tag_rules
from kis_config import type_shortcuts as _type_shortcuts

CLIPPINGS = subfolder_path("clippings")
OUTPUT = subfolder_path("clippingRefine")

VALUE_KEYWORDS = ["方法", "流程", "步骤", "案例", "数据", "研究", "对比", "框架", "模板", "prompt", "提示词", "技巧", "指南", "系统", "实操"]
NOISE_PATTERNS = (
    r"iframe|bilibili|frameborder|allowfullscreen",
    r"页面 DOM|网页 DOM|点点 AI|采集时间|原始分享链接|笔记链接",
    r"发布时间|编辑时间|作者|点赞数|收藏数|评论数|前\s*\d+\s*条评论",
    r"视频音频逐字稿|ASR 转录|Transcript",
)
QUOTE_STOPWORDS = {
    "Description", "**Description**", "原始分享链接：", "笔记文字内容已完整提取", "视频音频逐字稿（ASR 转录）：",
    "精简文案版（200 字以内）：", "标题：", "正文内容：", "标签：", "图片 OCR 文字："
}

# Comment/interaction line pattern from xhs / bilibili captures — very high false-positive quote source.
COMMENT_LINE_PATTERN = re.compile(r"^\s*(?:\d+\.\s*)?\*\*[^*]{1,20}\*\*[：:]")
# Lines that look like DOM metadata rows (数字前缀 + 冒号) or bulleted platform data.
PLATFORM_META_PATTERN = re.compile(r"^\s*(?:\d+[.)、]\s*)?(?:点赞|收藏|评论|发布|采集|作者|地区|IP|标签|标题)[数量：: ]")
# Signal phrases that mark a line as an actionable step / method.
METHOD_HINT_PATTERN = re.compile(r"建立|拆解|分析|生成|输出|整理|收集|验证|使用|运行|设计|转化|复盘|提示词|方法|步骤|流程|框架|模板|工具|清单|策略|机制|规则|习惯|案例")
# Signal phrases we treat as a genuine quotable insight (not a question, not metadata).
INSIGHT_HINT_PATTERN = re.compile(r"本质|核心|关键|真正|重点|其实|与其|而不是|才是|才能|一定要|最重要|最难|必须|不要|别再|才叫|才算|才能算|背后|逻辑|规律|真相|归根结底|说到底|最要命的|最值钱的|只有|唯一|绝不|不需要")
# Contrarian / reversal patterns; strong quote signal.
CONTRARIAN_PATTERN = re.compile(r"不是.+而是|与其.+不如|表面.+实际|看似.+其实|not\s+\w+.+but|大多数人都|你以为.+其实|很多人以为")
# Transition markers that reveal argument shifts.
TRANSITION_PATTERN = re.compile(r"但|然而|其实|反而|恰恰|事实上|只不过|确切地说|真正的|however|actually|really")
# English insight hints (for allow-english quotes).
ENGLISH_INSIGHT_PATTERN = re.compile(r"\b(actually|really|truly|instead of|not\s+\w+\s+but|only|never|always|the truth|most people|few people|the key|the point|essentially|fundamentally|matter|matters|dead|wins?|lose[sr]?|secret|nobody|everyone)\b", re.IGNORECASE)

# 内容类型、类型先验权重、类型判定短路规则均改为从 taxonomy 配置读取
# （kis_config.content_types / type_shortcuts）。历史默认值见 scripts/taxonomy.default.json。
def _content_types_map() -> Dict[str, Dict[str, object]]:
    return _content_types()


def _type_priority() -> Dict[str, float]:
    return {ctype: float(meta.get("priority", 1.0)) for ctype, meta in _content_types().items()}


def get_content_hash(content: str) -> str:
    return hashlib.md5(clean_content(content).encode("utf-8")).hexdigest()


def strip_frontmatter(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1 :])
    return content


def is_noise_line(line: str) -> bool:
    text = re.sub(r"\s+", " ", line).strip()
    if not text:
        return True
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in NOISE_PATTERNS):
        return True
    if re.fullmatch(r"\*+\s*Description\s*\*+", text, flags=re.IGNORECASE):
        return True
    if text in QUOTE_STOPWORDS:
        return True
    if text.startswith(("说明：", "注：", "页面标注", "当前页面", "本次 DOM")):
        return True
    if re.fullmatch(r"[A-Za-z0-9_:/?.=&%#|｜\- ]+", text):
        return True
    return False


def clean_content(content: str) -> str:
    content = strip_frontmatter(content)
    content = re.sub(r"<iframe.*?</iframe>", " ", content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r"<[^>]+>", " ", content)
    content = re.sub(r"https?://\S+", " ", content)
    lines = []
    for line in content.splitlines():
        if is_noise_line(line):
            continue
        cleaned_line = re.sub(r"^\s*\*+\s*Description\s*\*+\s*", "", line, flags=re.IGNORECASE).strip()
        if cleaned_line:
            lines.append(cleaned_line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def normalize(text: str) -> str:
    return text.lower().replace("｜", " ").replace("_", " ").replace("-", " ")


def split_sentences(text: str) -> List[str]:
    compact = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[。！？!?])\s*|\n+", compact)
    return [p.strip() for p in parts if len(p.strip()) >= 12]


def content_type(content: str, name: str) -> Tuple[str, int]:
    haystack = normalize(f"{name} {content}")
    ctype_map = _content_types_map()
    priority = _type_priority()
    scored = []
    for ctype, meta in ctype_map.items():
        matched = [kw for kw in meta["keywords"] if normalize(str(kw)) in haystack]  # type: ignore[index]
        if not matched:
            continue
        # Weighted score: match count + priority, with a small title boost.
        title_hits = sum(1 for kw in matched if normalize(str(kw)) in normalize(name))
        score = len(matched) * 2 + title_hits * 2 + priority.get(ctype, 1.0)
        scored.append((score, len(matched), ctype))
    for rule in _type_shortcuts():
        all_kw = [normalize(str(k)) for k in rule.get("all", [])]
        any_kw = [normalize(str(k)) for k in rule.get("any", [])]
        if all(k in haystack for k in all_kw) and (not any_kw or any(k in haystack for k in any_kw)):
            return str(rule["type"]), int(rule.get("score", 16))
    if not scored:
        return "待判断", 0
    score, matched_count, ctype = sorted(scored, reverse=True)[0]
    return ctype, int(round(score))


def auto_tags(content: str, name: str, limit: int = 4) -> List[str]:
    haystack = normalize(f"{name} {content}")
    candidates = []
    tag_rules = _tag_rules()
    for tag, kws in tag_rules.items():
        score = sum(1 for kw in kws if kw in haystack)
        if score:
            candidates.append((score, tag))
    return [tag for _, tag in sorted(candidates, reverse=True)[:limit]]


def extract_summary(content: str) -> Dict[str, str]:
    """Return a structured summary dict so the card can render bullet-like fields."""
    cleaned = clean_content(content)

    # Prefer the frontmatter description block — that's the human-authored abstract.
    description = ""
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, flags=re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if line.lower().startswith("description:"):
                description = line.split(":", 1)[1].strip().strip("'\"")
                # Some captures span multiple lines; grab the block until the next key.
                break

    concise = ""
    match = re.search(r"精简文案版（200[^）]*）[：:]?\s*(.+?)(?:\n###|\n####|\n---|$)", cleaned, flags=re.DOTALL)
    if match:
        concise = re.sub(r"\s+", " ", match.group(1)).strip()[:400]

    # Fall back to the first meaningful paragraph (skip Description headers/noise).
    fallback = ""
    for para in re.split(r"\n\s*\n", cleaned):
        para = re.sub(r"\s+", " ", para).strip()
        if len(para) < 40 or para.startswith("#"):
            continue
        if is_noise_line(para):
            continue
        if re.match(r"^\*+\s*Description\s*\*+", para, flags=re.IGNORECASE):
            continue
        fallback = para[:400]
        break

    core = description or concise or fallback
    return {
        "description": description,
        "concise": concise,
        "fallback": fallback,
        "core": core,
    }


def extract_author(content: str) -> str:
    """Try to identify the source author/creator from raw capture content."""
    m = re.search(r"\*\*作者：\*\*\s*(.+)", content)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:40]
    m = re.search(r"^作者[：:]\s*(.+)$", content, flags=re.MULTILINE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:40]
    return ""


def extract_core_thesis(content: str, description: str) -> str:
    """Best-effort single-sentence core argument. Prefer description; fall back to first strong sentence."""
    if description:
        first = re.split(r"[。！？!?]\s*", description, maxsplit=1)[0]
        first = re.sub(r"\s+", " ", first).strip()
        if len(first) >= 12:
            return first[:160]
    cleaned = clean_content(content)
    for sentence in split_sentences(cleaned):
        if is_noise_line(sentence) or COMMENT_LINE_PATTERN.match(sentence):
            continue
        if INSIGHT_HINT_PATTERN.search(sentence) or METHOD_HINT_PATTERN.search(sentence):
            return sentence[:160]
    # Otherwise return the first meaningful sentence.
    for sentence in split_sentences(cleaned):
        if is_noise_line(sentence) or COMMENT_LINE_PATTERN.match(sentence):
            continue
        return sentence[:160]
    return ""


def _is_comment_or_meta(line: str) -> bool:
    if COMMENT_LINE_PATTERN.match(line):
        return True
    if PLATFORM_META_PATTERN.match(line):
        return True
    return False


def extract_key_points(content: str, limit: int = 5) -> List[str]:
    cleaned = clean_content(content)
    points: List[str] = []
    # Bullets and numbered lines usually carry compressed ideas.
    for line in cleaned.splitlines():
        raw = line.strip()
        if not raw:
            continue
        if not re.match(r"^(?:[-*•]|\d+[.)、]|第[一二三四五六七八九十]+[部分步点])", raw):
            continue
        if _is_comment_or_meta(raw):
            continue
        point = re.sub(r"^(?:[-*•]|\d+[.)、])\s*", "", raw).strip()
        point = re.sub(r"^\*+\s*Description\s*\*+\s*", "", point, flags=re.IGNORECASE).strip()
        point = re.sub(r"\s+", " ", point)
        if _is_comment_or_meta(point):
            continue
        if 12 <= len(point) <= 160 and not is_noise_line(point) and point not in points:
            points.append(point)
        if len(points) >= limit:
            return points

    for sentence in split_sentences(cleaned):
        if _is_comment_or_meta(sentence):
            continue
        if re.search(r"核心|关键|本质|建议|应该|需要|可以|方法|流程|步骤|机会|风险|输出", sentence):
            point = sentence[:160]
            if point not in points and not is_noise_line(point):
                points.append(point)
        if len(points) >= limit:
            break
    return points


def extract_methods(content: str, limit: int = 8) -> List[str]:
    """Return ordered, verb-led methods pulled from bullets, headings, or hint sentences."""
    cleaned = clean_content(content)
    methods: List[str] = []

    def add(item: str) -> None:
        item = re.sub(r"^(?:[-*•]|\d+[.)、])\s*", "", item)
        item = re.sub(r"\s+", " ", item).strip()
        if not item or is_noise_line(item) or _is_comment_or_meta(item):
            return
        if not (12 <= len(item) <= 160):
            return
        # Avoid duplicate + super-similar entries.
        for existing in methods:
            if item == existing or item in existing or existing in item:
                return
        methods.append(item)

    for line in cleaned.splitlines():
        raw = line.strip()
        if not raw or _is_comment_or_meta(raw):
            continue
        # 1) Bulleted / numbered lines that read like an action.
        if re.match(r"^(?:[-*•]|\d+[.)、])\s+", raw):
            if METHOD_HINT_PATTERN.search(raw):
                add(raw)
            elif re.search(r"[：:]\s*.+", raw) and re.search(r"先|然后|接着|最后|首先", raw):
                add(raw)
        if len(methods) >= limit:
            return methods

    if len(methods) < limit:
        # Fallback: any sentence with strong verbs.
        for sentence in split_sentences(cleaned):
            if _is_comment_or_meta(sentence):
                continue
            if METHOD_HINT_PATTERN.search(sentence):
                add(sentence)
            if len(methods) >= limit:
                break
    return methods


def _quote_hard_reject(text: str) -> bool:
    """Return True if a candidate is definitely not a quote (metadata / comment / stopword)."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text or text in QUOTE_STOPWORDS:
        return True
    if is_noise_line(text):
        return True
    if _is_comment_or_meta(text):
        return True
    if text.startswith(("说明：", "注：", "页面标注", "当前页面", "本次 DOM")):
        return True
    if text.endswith(("：", ":")):
        return True
    if text.endswith(("?", "？")) or re.match(r"Q\d+[：:]", text):
        return True
    if re.fullmatch(r"[A-Za-z0-9_:/?.=&%#|｜\- ]+", text):
        return True
    # Frontmatter fields sometimes leak through
    if re.match(r"^(description|tags|title|source|url|link)\s*[：:]", text, flags=re.IGNORECASE):
        return True
    return False


def _has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fa5]", text))


def _has_english_sentence(text: str) -> bool:
    # At least 3 latin words to count as a real English sentence
    latin_words = re.findall(r"[A-Za-z][A-Za-z'’\-]{1,}", text)
    return len(latin_words) >= 3


def score_quote(text: str, source: str, position: float = 0.5) -> int:
    """Score a candidate quote using multiple signals. `source` is 'bold' | 'blockquote' | 'description' | 'body'.
    `position` is 0..1 (0 = article start, 1 = article end).
    """
    text = re.sub(r"\s+", " ", text).strip()
    if _quote_hard_reject(text):
        return -99
    if len(text) < 12 or len(text) > 220:
        return -99

    has_cn = _has_chinese(text)
    has_en = _has_english_sentence(text) and not has_cn
    if not has_cn and not has_en:
        return -99

    score = 0
    if source == "bold":
        score += 3
    elif source == "blockquote":
        score += 3
    elif source == "description":
        score += 2
    # body: +0

    if has_cn:
        if INSIGHT_HINT_PATTERN.search(text):
            score += 3
        if CONTRARIAN_PATTERN.search(text):
            score += 2
        if TRANSITION_PATTERN.search(text):
            score += 1
    else:
        if ENGLISH_INSIGHT_PATTERN.search(text):
            score += 3

    # Numeric / percentage signals: hard evidence
    if re.search(r"\d+\s*%|\d+\s*(?:倍|万|亿|千|百)|Top\s*\d+|月入|一年|入|月|每\s*\d", text, flags=re.IGNORECASE):
        score += 2

    # Length bonus
    tlen = len(text)
    if 25 <= tlen <= 80:
        score += 2
    elif 18 <= tlen <= 24 or 81 <= tlen <= 120:
        score += 1

    # Position: opening or conclusion get a bonus
    if position <= 0.2 or position >= 0.8:
        score += 2

    # Complete-sentence bonus
    if re.search(r"[。！？.!]\s*$", text):
        score += 1

    # Comment residue penalty
    if re.search(r"👍|💬|回复|转发|点赞|\d{2}-\d{2}", text):
        score -= 3

    return score


def _description_sentences(content: str) -> List[str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, flags=re.DOTALL)
    if not m:
        return []
    block = m.group(1)
    # collect description value (possibly multiline before next key)
    lines = block.splitlines()
    desc = ""
    capture = False
    for line in lines:
        low = line.lower().strip()
        if not capture and low.startswith("description:"):
            desc = line.split(":", 1)[1]
            capture = True
            continue
        if capture:
            # next field starts with `word:` at column 0 (no leading space)
            if re.match(r"^\S+:", line):
                break
            desc += " " + line
    if not desc:
        return []
    desc = re.sub(r"\s+", " ", desc).strip().strip("'\"")
    if not desc:
        return []
    parts = re.split(r"(?<=[。！？.!?])\s+", desc)
    return [p.strip() for p in parts if len(p.strip()) >= 12]


def _body_positioned_sentences(body: str) -> List[Tuple[str, float]]:
    compact = re.sub(r"\s+", " ", body).strip()
    if not compact:
        return []
    parts = re.split(r"(?<=[。！？!?])\s*", compact)
    parts = [p.strip() for p in parts if len(p.strip()) >= 12]
    total = max(len(parts) - 1, 1)
    return [(p, i / total) for i, p in enumerate(parts)]


def _similar_quote(a: str, b: str) -> bool:
    shorter, longer = sorted([a, b], key=len)
    if not shorter:
        return False
    # crude longest common substring threshold
    if shorter in longer:
        return True
    # token overlap ratio
    a_tokens = set(re.findall(r"[\u4e00-\u9fa5]{2}|[A-Za-z]{3,}", a))
    b_tokens = set(re.findall(r"[\u4e00-\u9fa5]{2}|[A-Za-z]{3,}", b))
    if not a_tokens or not b_tokens:
        return False
    overlap = len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))
    return overlap >= 0.7


def extract_quotes(content: str, limit: int = 3, min_score: int = 6) -> List[Dict[str, str]]:
    """Return top quotes with source label. Each item is {'text': str, 'source': str, 'score': int}."""
    body = strip_frontmatter(content)
    # Cut off comment / interaction sections
    body_no_comments = re.split(r"###\s*[三四五]\s*[、。.]?\s*前\s*\d+\s*条评论", body, maxsplit=1)[0]
    body_no_comments = re.split(r"##+\s*.*?评论", body_no_comments, maxsplit=1)[0]

    candidates: List[Tuple[str, str, float]] = []  # (text, source, position)
    # 1) bold
    for m in re.finditer(r"\*\*(.+?)\*\*", body_no_comments, flags=re.DOTALL):
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        pos = m.start() / max(len(body_no_comments), 1)
        candidates.append((t, "bold", pos))
    # 2) blockquotes
    for m in re.finditer(r"^>\s*(.+)$", body_no_comments, flags=re.MULTILINE):
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        pos = m.start() / max(len(body_no_comments), 1)
        candidates.append((t, "blockquote", pos))
    # 3) description
    for i, sent in enumerate(_description_sentences(content)):
        candidates.append((sent, "description", 0.05 + i * 0.02))
    # 4) body sentences
    for sent, pos in _body_positioned_sentences(body_no_comments):
        candidates.append((sent, "body", pos))

    # Score all
    scored: List[Dict[str, object]] = []
    for text, source, pos in candidates:
        s = score_quote(text, source, pos)
        if s >= min_score:
            scored.append({"text": text, "source": source, "score": s})

    # sort by score desc, then bold/blockquote > description > body
    source_priority = {"bold": 3, "blockquote": 3, "description": 2, "body": 1}
    scored.sort(key=lambda x: (int(x["score"]), source_priority.get(str(x["source"]), 0)), reverse=True)

    picked: List[Dict[str, str]] = []
    for item in scored:
        if any(_similar_quote(str(item["text"]), str(p["text"])) for p in picked):
            continue
        picked.append({"text": str(item["text"]), "source": str(item["source"]), "score": str(item["score"])})
        if len(picked) >= limit:
            break
    return picked


def is_meaningful_quote(text: str) -> bool:
    """Kept for backwards compat with link_suggester. Approximates the new scorer."""
    return score_quote(text, "body", 0.5) >= 6


def extract_questions(content: str, limit: int = 5) -> List[str]:
    cleaned = clean_content(content)
    qs = []
    for q in re.findall(r"(?:Q\d+[：:].+?|[^。！？!?\n]{8,80}[？?])", cleaned):
        q = re.sub(r"\s+", " ", q).strip()
        if is_noise_line(q) or q.startswith(("说明：", "注：", "页面标注", "当前页面", "本次 DOM")):
            continue
        if not re.search(r"[？?]", q):
            continue
        if re.match(r"\d+[.)、]\s*[^：:]{1,20}[：:].+[？?]", q):
            continue
        if q not in qs:
            qs.append(q)
        if len(qs) >= limit:
            break
    return qs


def noise_signals(content: str) -> List[str]:
    signals = []
    for label, pattern in [
        ("含 iframe/HTML 残留", r"iframe|frameborder|allowfullscreen"),
        ("含评论区采集", r"前\s*\d+\s*条评论|评论/回复|评论数"),
        ("含 ASR 逐字稿", r"Transcript|视频音频逐字稿|ASR"),
        ("含平台元数据", r"点赞数|收藏数|发布时间|采集时间|原始分享链接"),
    ]:
        if re.search(pattern, content, flags=re.IGNORECASE):
            signals.append(label)
    return signals


def calculate_quality_score(content: str, name: str) -> int:
    cleaned = clean_content(content)
    score = 0
    length = len(cleaned)
    if length > 2500:
        score += 25
    elif length > 1000:
        score += 18
    elif length > 400:
        score += 10

    points = extract_key_points(content)
    methods = extract_methods(content)
    quotes = extract_quotes(content)
    ctype, type_score = content_type(cleaned, name)
    score += min(len(points) * 5, 20)
    score += min(len(methods) * 5, 25)
    score += min(len(quotes) * 3, 12)
    score += min(type_score * 3, 15)

    if re.search(r"\d+%|\d+\.\d+|\d+\s*倍|Top\s*\d+", cleaned, flags=re.IGNORECASE):
        score += 5
    if any(kw.lower() in cleaned.lower() for kw in VALUE_KEYWORDS):
        score += 8
    # Penalize noisy captures slightly, but do not discard them.
    score -= min(len(noise_signals(content)) * 3, 10)
    return max(0, min(score, 100))


def asset_suggestion(ctype: str, score: int, methods: List[str]) -> str:
    asset = _content_types_map().get(ctype, {}).get("asset", "想法追踪 / 暂存观察")
    if score >= 70 and methods:
        return f"优先沉淀为：{asset}"
    if score >= 50:
        return f"可提炼为：{asset}"
    return "先暂存；除非与当前项目强相关，否则不建议立刻深挖。"


def detect_duplicates(files_data: List[Dict[str, object]]) -> List[Tuple[str, str]]:
    hash_map = {}
    duplicates = []
    for f in files_data:
        h = f["content_hash"]
        if h in hash_map:
            duplicates.append((hash_map[h], str(f["name"])))
        else:
            hash_map[h] = str(f["name"])
    return duplicates


def analyze_file(path: Path) -> Dict[str, object]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    cleaned = clean_content(content)
    ctype, _ = content_type(cleaned, path.stem)
    points = extract_key_points(content)
    methods = extract_methods(content)
    quotes = extract_quotes(content)
    questions = extract_questions(content)
    score = calculate_quality_score(content, path.stem)
    tags = auto_tags(cleaned, path.stem)
    summary = extract_summary(content)
    author = extract_author(content)
    core_thesis = extract_core_thesis(content, summary.get("description", ""))
    result: Dict[str, object] = {
        "name": path.stem,
        "path": str(path),
        "score": score,
        "type": ctype,
        "tags": tags,
        "author": author,
        "summary": summary,
        "core_thesis": core_thesis,
        "points": points,
        "methods": methods,
        "quotes": quotes,
        "questions": questions,
        "noise": noise_signals(content),
        "suggestion": asset_suggestion(ctype, score, methods),
        "content_hash": get_content_hash(content),
        "word_count": len(cleaned),
    }
    result["next_actions"] = next_actions_from_content(result)
    return result


def next_actions_from_content(analysis: Dict[str, object]) -> List[str]:
    """Content-aware follow-ups derived from the source clipping."""
    actions: List[str] = []
    ctype = str(analysis.get("type", ""))
    methods = analysis.get("methods") or []
    quotes = analysis.get("quotes") or []
    questions = analysis.get("questions") or []
    tags = analysis.get("tags") or []
    noise = analysis.get("noise") or []
    score = int(analysis.get("score", 0))
    summary = analysis.get("summary")
    if isinstance(summary, dict):
        summary_core = str(summary.get("core", ""))
    else:
        summary_core = str(summary or "")

    if ctype == "信息源清单":
        actions.append("把文中提到的博主/媒体逐个拆行，写成“源头 + 适用场景 + 抢看频率”的信息源卡片（进想法追踪）。")
    if ctype in {"工作流教程", "工具教程", "Prompt/模板"} or "Prompt/工作流" in tags:
        actions.append("把原文里的步骤抽成 Skill 草稿：输入 / 步骤 / 输出 / 适用与不适用。")
    if ctype == "案例拆解":
        actions.append("拆一个自己的对照案例，验证原文方法在你手上的成功条件和失败信号。")
    if ctype == "观点文章":
        actions.append("提炼作者的核心判断为一句话，写成想法追踪条目，并附上你同意 / 不同意的一句话反驳。")
    if ctype == "职业机会":
        actions.append("把岗位 / 公司 / 入口 / 需补材料敲成一张机会雷达，归入“AI/remote 机会清单”主题目录（Skill 候选或想法追踪）。")
    if ctype == "商业投研":
        actions.append("提炼一张 客户分层 / 变现链路 / 风险清单 的商业方法论卡片。")
    if ctype == "内容方法论":
        actions.append("将方法套到自己的账号上：同一主题写 3 个样稿标题，判断物料性。")
    if ctype == "创意素材":
        actions.append("拓展成一个小企划：一句话概念 + 受众 + 呈现形式 + 3 个样稿标题。")
    if ctype == "心智成长":
        actions.append("把其中一句反直觉的观点转为反思问题，放进想法追踪里一周后重读。")
    if ctype == "行业情报":
        actions.append("抽取关键公司 / 赛道 / 机会空白点，补到 想法追踪/行业地图 对应节点。")

    if len(methods) >= 3 and score >= 55:
        actions.append("方法列表已比较完整，可直接临摩成 SOP：把步骤改成你习惯的动词（例如以“先…然后…最后…”结构重写）。")
    if questions:
        actions.append("将“关键问题”中 1-2 道写入自己的 想法/灵感集，当作下一次思考入口。")
    if quotes:
        actions.append("从“原文金句”挑 1 句写成小红书 / 微博岁月号选题候选（需自己重新造句）。")
    if noise:
        actions.append("正式沉淀前，清理原文中的 iframe / 评论 / 采集字段，避免污染推荐连接。")
    if summary_core and len(summary_core) > 80:
        actions.append("将作者 description 重写为你自己的一句话缩写，能用你的语言复述才算自己的知识。")

    seen = set()
    unique: List[str] = []
    for a in actions:
        if a in seen:
            continue
        seen.add(a)
        unique.append(a)
    return unique[:6]


def list_lines(items: Iterable[str], empty: str = "暂无自动提取结果。") -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return empty
    return "\n".join(f"- {item}" for item in values)


def ordered_lines(items: Iterable[str], empty: str = "暂无自动提取结果。") -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return empty
    return "\n".join(f"{i}. {item}" for i, item in enumerate(values, 1))


def quote_lines(items: Iterable, empty: str = "此篇未提取到高置信金句（无强候选时不占位）。") -> str:
    values = list(items) if items else []
    if not values:
        return empty
    source_label = {
        "bold": "来自：加粗",
        "blockquote": "来自：引用",
        "description": "来自：描述",
        "body": "来自：正文",
    }
    lines = []
    for item in values:
        if isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            src = str(item.get("source", "body"))
            if not text:
                continue
            lines.append(f"> {text}\n>\n> — {source_label.get(src, '来自：正文')}")
        else:
            text = str(item).strip()
            if not text:
                continue
            lines.append(f"> {text}")
    if not lines:
        return empty
    return "\n\n".join(lines)


def summary_block(f: Dict[str, object]) -> str:
    summary = f.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {"core": str(summary)}
    core = summary.get("core") or "作者没有提供明确的一句话概括。"
    ctype = f.get("type") or "待判断"
    author = f.get("author") or "未知"
    thesis = f.get("core_thesis") or core
    methods = f.get("methods") or []
    if methods:
        method_gist = "；".join(m for m in methods[:3])
    else:
        method_gist = "原文未给出可直接拆解的方法。"
    lines = [
        f"- **内容类型**：{ctype}",
        f"- **谁在讲**：{author}",
        f"- **核心主张**：{thesis}",
        f"- **主要方法**：{method_gist}",
    ]
    return "\n".join(lines)


def next_step_block(f: Dict[str, object]) -> str:
    default_actions = [
        "判断是否关联当前项目/想法",
        "如果方法完整，沉淀为 Skill 草稿",
        "如果观点清晰，沉淀为想法追踪条目",
        "如果适合发布，转入 Output 选题池",
    ]
    parts = ["### 标准动作", ""]
    parts.extend(f"- [ ] {a}" for a in default_actions)
    parts.extend(["", "### 基于本篇原文的建议", ""])
    tailored = f.get("next_actions") or []
    if tailored:
        parts.extend(f"- [ ] {a}" for a in tailored)
    else:
        parts.append("- [ ] 本篇自动分析未能给出额外建议，请结合当前项目自行判断。")
    return "\n".join(parts)


def generate_card(f: Dict[str, object]) -> str:
    return f"""# 📑 内容提炼卡片：{f['name']}

## 质量评估

- 质量分：**{f['score']}/100**
- 内容类型：{f['type']}
- 自动标签：{', '.join(f['tags']) if f['tags'] else '-'}
- 清洗后字数：{f['word_count']}
- 资产化建议：{f['suggestion']}

## 一句话摘要

{summary_block(f)}

## 核心观点

{ordered_lines(f['points'])}

## 可复用方法

{ordered_lines(f['methods'])}

## 原文金句

{quote_lines(f['quotes'])}

## 关键问题

{list_lines(f['questions'])}

## 噪音/待清理字段

{list_lines(f['noise'], '未检测到明显采集噪音。')}

## 下一步

{next_step_block(f)}

来源：[[{f['name']}]]
"""


def generate_report() -> tuple[Path | None, int, int, int]:
    print("📝 正在提炼所有 Clippings...")
    files_data: List[Dict[str, object]] = []

    if not CLIPPINGS.exists():
        print("Clippings 目录不存在")
        return None, 0, 0, 0

    for fpath in iter_markdown_files(CLIPPINGS):
        files_data.append(analyze_file(fpath))

    files_data.sort(key=lambda x: int(x["score"]), reverse=True)
    duplicates = detect_duplicates(files_data)
    average_score = sum(int(f["score"]) for f in files_data) / len(files_data) if files_data else 0

    excellent = [f for f in files_data if int(f["score"]) >= 70]
    good = [f for f in files_data if 50 <= int(f["score"]) < 70]
    normal = [f for f in files_data if int(f["score"]) < 50]
    card_candidates = [f for f in files_data if int(f["score"]) >= 45]

    type_counter = Counter(str(f["type"]) for f in files_data)
    tag_counter = Counter(tag for f in files_data for tag in f["tags"])  # type: ignore[union-attr]

    report: List[str] = [
        "# 📑 Clippings 内容提炼报告", "",
        "> 自动分析外部抓取内容：类型、观点、方法、金句、噪音和资产化方向。", "",
        "## 📊 内容质量总览", "",
        "| 质量等级 | 数量 |", "|----------|------|",
        f"| 🌟 优质（70分以上） | {len(excellent)} |",
        f"| ✅ 良好（50-70分） | {len(good)} |",
        f"| 📝 普通（50分以下） | {len(normal)} |",
        "", f"- 分析总数：**{len(files_data)}** 篇",
        f"- 平均质量分：**{average_score:.1f}**", "",
        "## 🧭 内容类型分布", "",
    ]
    for ctype, count in type_counter.most_common():
        report.append(f"- **{ctype}**：{count} 篇")
    report.append("")

    if tag_counter:
        report.extend(["## 🏷️ 高频标签", ""])
        report.append("、".join(f"{tag}({count})" for tag, count in tag_counter.most_common(12)))
        report.append("")

    if duplicates:
        report.extend(["## ⚠️ 检测到重复内容", ""])
        for a, b in duplicates:
            report.append(f"- [[{a}]] 与 [[{b}]] 内容高度相似，建议合并")
        report.append("")

    report.extend(["## 🌟 优先处理内容", "", "| 内容名称 | 分数 | 类型 | 资产化建议 |", "|---------|------|------|------------|"])
    for f in files_data[:12]:
        report.append(f"| [[{f['name']}]] | {f['score']}/100 | {f['type']} | {f['suggestion']} |")

    report.extend(["", "## 🎯 本轮应用建议", ""])
    if excellent:
        report.append("- 优先把优质内容中“可复用方法”完整的条目转成 Skill 草稿。")
    if type_counter:
        top_type, top_count = type_counter.most_common(1)[0]
        report.append(f"- 当前最集中的内容类型是 **{top_type}**（{top_count} 篇），适合做一次主题聚合。")
    noisy = [f for f in files_data if f["noise"]]
    if noisy:
        report.append(f"- 有 {len(noisy)} 篇内容含采集噪音，做正式卡片前建议清理 iframe/评论区/平台元数据。")
    report.append("")

    all_methods = []
    for f in files_data:
        for method in f["methods"]:  # type: ignore[union-attr]
            all_methods.append((str(f["name"]), str(method)))
    if all_methods:
        report.extend(["## 🧰 可复用方法摘录", ""])
        for name, method in all_methods[:15]:
            report.append(f"- [[{name}]]：{method}")
        report.append("")

    report.extend(["---", "", f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"])

    OUTPUT.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT / "Clippings总览报告.md"
    output_path.write_text("\n".join(report), encoding="utf-8")

    for f in card_candidates:
        card_path = OUTPUT / f"提炼_{f['name']}.md"
        card_path.write_text(generate_card(f), encoding="utf-8")

    return output_path, len(files_data), len(excellent), len(good)


if __name__ == "__main__":
    print("=" * 40)
    print("📑 Clippings 内容提炼流水线")
    print("=" * 40)
    output, total, excellent, good = generate_report()
    if output:
        print(f"✅ 分析了 {total} 篇内容")
        print(f"   推荐了 {excellent} 篇优质内容")
        print(f"   生成了 {good} 篇良好内容备选")
        print(f"   位置：{OUTPUT}")
