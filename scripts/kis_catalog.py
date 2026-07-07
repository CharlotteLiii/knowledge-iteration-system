#!/usr/bin/env python3
"""输入层分类目录 catalog（Knowledge Iteration System 专用）。

职责：
- catalog.json 是**唯一数据源**（source of truth）：记录每个输入层文档的分类、
  内容 hash、来源、更新时间。
- 输入层分类目录.md 是**渲染产物**（展示用）：从 catalog.json 生成两个视图
  （按分类看文档 / 按文档看分类），人不直接编辑它。
- 待确认分类队列（.kis_pending_categories.json）收集"落入其他"或"LLM 提议新分类"
  的疑难件，等人异步处理，绝不在脚本里同步问用户。

catalog.json 结构：
{
  "version": 1,
  "docs": {
    "<abs_path>": {
      "name": "...", "category_source": "keyword|llm|manual",
      "categories": ["工作流教程", ...], "hash": "<md5>",
      "updated_at": "2026-07-07T21:00:00"
    }
  }
}
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from kis_config import VAULT, content_types, subfolder_path

CATALOG_NAME = "catalog.json"
CATALOG_PATH = VAULT / CATALOG_NAME
PENDING_NAME = ".kis_pending_categories.json"
PENDING_PATH = VAULT / PENDING_NAME
CATALOG_VERSION = 1
OTHER = "其他"

# 分类目录文档落在蒸馏层（复用 dailyDistill 的父层）。
CATALOG_DOC_NAME = "输入层分类目录.md"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _catalog_doc_path() -> Path:
    """分类目录文档：放在蒸馏层根目录下。"""
    # 复用任一蒸馏层子目录的父级 = 蒸馏层根。
    distilled_root = subfolder_path("dailyDistill").parent
    return distilled_root / CATALOG_DOC_NAME


def load_catalog() -> Dict:
    if not CATALOG_PATH.exists():
        return {"version": CATALOG_VERSION, "docs": {}}
    try:
        obj = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {"version": CATALOG_VERSION, "docs": {}}
        obj.setdefault("version", CATALOG_VERSION)
        obj.setdefault("docs", {})
        return obj
    except Exception:
        return {"version": CATALOG_VERSION, "docs": {}}


def save_catalog(catalog: Dict) -> None:
    try:
        CATALOG_PATH.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        pass


def load_pending() -> Dict:
    if not PENDING_PATH.exists():
        return {"version": CATALOG_VERSION, "items": {}}
    try:
        obj = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {"version": CATALOG_VERSION, "items": {}}
        obj.setdefault("items", {})
        return obj
    except Exception:
        return {"version": CATALOG_VERSION, "items": {}}


def save_pending(pending: Dict) -> None:
    try:
        PENDING_PATH.write_text(
            json.dumps(pending, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        pass


def prune_missing(catalog: Dict) -> int:
    """对账清理：移除 catalog 中指向已不存在文件的僵尸条目。

    解决“删除/重命名输入文档后，分类目录残留指向不存在文件的死链 [[旧名]]”。
    返回清理掉的条目数。
    """
    docs = catalog.get("docs", {})
    stale = [key for key in docs if not Path(key).exists()]
    for key in stale:
        del docs[key]
    return len(stale)


def upsert_doc(catalog: Dict, path: Path, name: str, categories: List[str],
               source: str, content_hash: str) -> None:
    """把一篇文档的分类写入 catalog（覆盖式，manual 不被自动覆盖）。"""
    docs = catalog.setdefault("docs", {})
    key = str(path.resolve())
    prev = docs.get(key)
    # 人工归类（manual）优先级最高，自动分类不覆盖它。
    if isinstance(prev, dict) and prev.get("category_source") == "manual" and source != "manual":
        return
    docs[key] = {
        "name": name,
        "categories": categories,
        "category_source": source,
        "hash": content_hash,
        "updated_at": _now_iso(),
    }


def queue_pending(pending: Dict, path: Path, name: str, reason: str,
                  proposals: Optional[List[str]] = None) -> None:
    """把疑难件加入待审队列（幂等：同路径覆盖）。"""
    items = pending.setdefault("items", {})
    items[str(path.resolve())] = {
        "name": name,
        "reason": reason,               # "no_match" | "llm_proposal"
        "proposals": proposals or [],
        "queued_at": _now_iso(),
    }


def render_catalog_doc(catalog: Dict) -> Path:
    """从 catalog.json 渲染双视图 markdown。返回写入路径。"""
    docs = catalog.get("docs", {})
    # 反向索引：分类 -> 文档
    by_cat: Dict[str, List[Dict]] = {}
    for meta in docs.values():
        for cat in (meta.get("categories") or [OTHER]):
            by_cat.setdefault(cat, []).append(meta)

    known_order = list(content_types().keys()) + [OTHER]
    def cat_sort_key(cat: str):
        idx = known_order.index(cat) if cat in known_order else len(known_order)
        return (idx, cat)

    total = len(docs)
    lines: List[str] = [
        "# 🗂 输入层分类目录",
        "",
        "> 输入层每篇文档归属哪些分类的索引。数据源为 catalog.json，本文件是渲染产物，请勿手动编辑。",
        "",
        "## 📊 概览",
        "",
        f"- 已归类文档：**{total}** 篇",
        f"- 分类数：**{len([c for c in by_cat if c != OTHER])}**（不含「{OTHER}」）",
        f"- 落入「{OTHER}」：**{len(by_cat.get(OTHER, []))}** 篇",
        "",
        "## 📁 按分类看文档",
        "",
    ]
    if not by_cat:
        lines.append("暂无已归类文档。")
        lines.append("")
    else:
        for cat in sorted(by_cat.keys(), key=cat_sort_key):
            items = by_cat[cat]
            lines.append(f"### {cat}（{len(items)}）")
            for meta in sorted(items, key=lambda m: m.get("name", "")):
                lines.append(f"- [[{meta.get('name','')}]]")
            lines.append("")

    lines.extend(["## 📄 按文档看分类", ""])
    if not docs:
        lines.append("暂无文档。")
        lines.append("")
    else:
        for meta in sorted(docs.values(), key=lambda m: m.get("name", "")):
            cats = "、".join(meta.get("categories") or [OTHER])
            src = meta.get("category_source", "keyword")
            src_label = {"keyword": "关键词", "llm": "LLM", "manual": "人工"}.get(src, src)
            lines.append(f"- [[{meta.get('name','')}]] → {cats} · {src_label}")
        lines.append("")

    lines.extend(["---", "", f"*生成时间：{_now_iso()}*"])

    out = _catalog_doc_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
