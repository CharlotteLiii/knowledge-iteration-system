#!/usr/bin/env python3
"""输入层文档分类器（Knowledge Iteration System 专用）。

两种可插拔后端（对齐 link_suggester 的 backend 模式）：
- KeywordClassifier（默认，离线）：用 taxonomy.contentTypes 的关键词做多标签命中。
  一个都不命中 → 归入 OTHER（"其他"），并进入待审队列等人工归类。
- LLMClassifier（opt-in）：复用 kis_llm.call_json 做语义多标签分类，带 hash 缓存、
  无网/未配置自动降级为 KeywordClassifier。可提议"疑似新分类"（不自动写配置）。

设计约束：
- 分类维度**复用 clipping ctype 的同一套 key**（taxonomy.contentTypes 的键），不新造表。
- LLM 默认 off；无 LLM 也能完整运转（关键词 + OTHER 兜底 + 待审队列）。
- 分类器不写配置、不改原文；新增分类的批准权在人手里（onboarding / 异步队列）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from kis_config import content_types, TAXONOMY

OTHER = "其他"

# 多标签最低命中阈值：只有命中 >= min_hits 的分类才作为标签打上，
# 弱命中不进多标签，避免"沾边即打"稀释目录。可在 taxonomy.json 用
# `classify.minKeywordHits` 覆盖（默认 2）。
def _min_hits() -> int:
    cfg = TAXONOMY.get("classify") if isinstance(TAXONOMY, dict) else None
    if isinstance(cfg, dict):
        val = cfg.get("minKeywordHits")
        if isinstance(val, int) and val >= 1:
            return val
    return 2


def _normalize(text: str) -> str:
    return text.lower().replace("｜", " ").replace("_", " ").replace("-", " ")


@dataclass
class Classification:
    categories: List[str]                 # 命中的分类（可能多个；空→已回落 OTHER 前的状态）
    source: str                           # "keyword" | "llm" | "manual"
    fell_back_to_other: bool = False      # 是否因零命中而归入 OTHER
    proposals: List[str] = field(default_factory=list)  # LLM 提议的疑似新分类（需人工批准）


class KeywordClassifier:
    """离线多标签分类：命中 taxonomy.contentTypes 关键词即打该标签。

    精准模式（默认 min_hits=2）：只有命中 >= min_hits 个关键词的分类才作为标签。
    若没有任何分类达到阈值，则退而取命中最强的**单个**分类作主分类兜底，
    避免把弱命中文档无谓归入 OTHER；真正零命中才落 OTHER。
    """

    name = "keyword"

    def __init__(self, min_hits: Optional[int] = None) -> None:
        self._types = content_types()
        self._min_hits = min_hits if (isinstance(min_hits, int) and min_hits >= 1) else _min_hits()

    def classify(self, name: str, content: str) -> Classification:
        haystack = _normalize(f"{name} {content}")
        matched: List[Tuple[int, str]] = []
        for ctype, meta in self._types.items():
            kws = meta.get("keywords", []) if isinstance(meta, dict) else []
            hits = sum(1 for kw in kws if _normalize(str(kw)) in haystack)
            if hits:
                matched.append((hits, ctype))
        if not matched:
            return Classification(categories=[OTHER], source="keyword", fell_back_to_other=True)
        matched.sort(key=lambda x: (-x[0], x[1]))
        # 精准多标签：只保留达到阈值的分类。
        strong = [c for h, c in matched if h >= self._min_hits]
        if strong:
            return Classification(categories=strong, source="keyword")
        # 无强命中 → 取最强单类作主分类兜底（不落 OTHER）。
        return Classification(categories=[matched[0][1]], source="keyword")


class LLMClassifier:
    """语义多标签分类（opt-in）。失败/未配置自动降级为 KeywordClassifier。"""

    name = "llm"

    def __init__(self) -> None:
        self._fallback = KeywordClassifier()
        self._types = content_types()

    def classify(self, name: str, content: str) -> Classification:
        try:
            import kis_llm
        except Exception:
            return self._degrade(name, content)

        ok, _ = kis_llm.probe()
        if not ok:
            return self._degrade(name, content)

        allowed = list(self._types.keys())
        system = (
            "你是知识库文档分类助手。只能从给定分类清单里选，允许命中多个分类。"
            "如果原文明显不属于任何给定分类，categories 返回空数组，并在 proposals 里给出"
            "1-2 个建议的新分类名（简短名词短语）。只依据原文，不脑补。返回严格 JSON。"
        )
        user = (
            f"分类清单（只能从中选）：{allowed}\n\n"
            "返回 JSON：{\"categories\":[...],\"proposals\":[...]}。\n"
            "categories 是命中的分类名（必须来自清单）；proposals 仅在都不命中时给出。\n\n"
            f"文档标题：{name}\n文档正文（可能截断）：\n<<<\n{content[:4000]}\n>>>"
        )
        try:
            obj = kis_llm.call_json(system, user, cache_purpose="input_classify")
        except Exception:
            return self._degrade(name, content)

        cats_raw = obj.get("categories") or []
        proposals_raw = obj.get("proposals") or []
        # 只保留清单内的合法分类，防止模型漂移造新类。
        cats = [c for c in cats_raw if isinstance(c, str) and c in self._types]
        proposals = [p for p in proposals_raw if isinstance(p, str) and p.strip()][:2]

        if cats:
            return Classification(categories=cats, source="llm", proposals=proposals)
        # 零命中 → OTHER 兜底，带上提议供人工决策
        return Classification(
            categories=[OTHER], source="llm", fell_back_to_other=True, proposals=proposals
        )

    def _degrade(self, name: str, content: str) -> Classification:
        result = self._fallback.classify(name, content)
        # 保留来源为 keyword，标明是降级结果。
        return result


def build_classifier(kind: str):
    """kind: 'keyword'（默认）| 'llm'。未知值回落 keyword。"""
    if kind == "llm":
        return LLMClassifier()
    return KeywordClassifier()
