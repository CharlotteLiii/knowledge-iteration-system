#!/usr/bin/env python3
"""Shared configuration helpers for the Knowledge Iteration System scripts.

This module keeps the automation scripts path-agnostic and shareable:
- Resolves the vault root from the scripts directory.
- Loads `.knowledge-iteration-system.json` when present.
- Falls back to the canonical four-layer structure when absent.
- Provides preflight checks without deleting, moving, or renaming user files.
"""
from __future__ import annotations

import json
import os
import re
import fnmatch
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent


def _resolve_vault_root() -> Path:
    """定位 Vault 根目录，支持三种部署形态：

    1. **环境变量 `KIS_VAULT_ROOT` 显式声明**（优先级最高）。
       适用：scripts 与 Vault 分开部署（如 scripts 用软链 / clone 到 dev 目录 /
       多 Vault 共享同一套 scripts）。例：
           export KIS_VAULT_ROOT="/path/to/vault"
    2. **`__file__.parent.parent` 的父目录**（历史默认）。
       适用：scripts 直接拷贝到 Vault 根下、未经软链。
       注意 `.resolve()` 会展开软链：如果 `scripts` 是指向外部目录的软链，
       这个默认会担误 Vault，请改用环境变量方式。
    """
    env_value = os.environ.get("KIS_VAULT_ROOT", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return SCRIPT_DIR.parent


VAULT = _resolve_vault_root()
CONFIG_NAME = ".knowledge-iteration-system.json"
CONFIG_PATH = VAULT / CONFIG_NAME

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 1,
    "layers": {
        "inbox": "第一层：输入层 (Inbox)",
        "distilled": "第二层：蒸馏层 (Distilled)",
        "skills": "第三层：技能层 (Skills)",
        "output": "第四层：输出层 (Output)",
    },
    "subfolders": {
        "ideas": "第一层：输入层 (Inbox)/想法/灵感集",
        "clippings": "第一层：输入层 (Inbox)/Clippings",
        "dailyDistill": "第二层：蒸馏层 (Distilled)/每日蒸馏",
        "weeklyReview": "第二层：蒸馏层 (Distilled)/每周复盘",
        "ideaTracking": "第二层：蒸馏层 (Distilled)/想法追踪",
        "clippingRefine": "第二层：蒸馏层 (Distilled)/Clippings提炼",
        "linkSuggestions": "第二层：蒸馏层 (Distilled)/结构性链接建议",
    },
    "docs": {
        "systemIntro": "📚 知识迭代系统说明.md",
    },
    "scripts": {
        "dir": "scripts",
        "runner": "scripts/run_all.py",
    },
    "automation": {
        "dailyIntervalDays": None,
        "dailyScanDays": 2,
        "dailyRunAtHour": 9,
        "askOnFirstUse": True,
    },
}

AUTOMATION_INTERVAL_CHOICES: Tuple[int, ...] = (1, 2, 3, 4)

LAYER_ALIASES: Dict[str, Tuple[str, ...]] = {
    "inbox": ("第一层：输入层 (Inbox)", "Inbox", "输入层", "01 Inbox", "01_输入层", "01-输入层"),
    "distilled": ("第二层：蒸馏层 (Distilled)", "Distilled", "蒸馏层", "02 Distilled", "02_蒸馏层", "02-蒸馏层"),
    "skills": ("第三层：技能层 (Skills)", "Skills", "技能层", "方法论", "Workflows", "03 Skills", "03_技能层", "03-技能层"),
    "output": ("第四层：输出层 (Output)", "Output", "Outputs", "输出层", "发布", "04 Output", "04_输出层", "04-输出层"),
}

IGNORE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}

IGNORE_PARTS = {
    ".git",
    ".obsidian",
    ".trash",
    ".stversions",
    ".claude",
    ".cursor",
    ".vscode",
    "__pycache__",
}

IGNORE_PATTERNS = (
    "*.baiduyun.uploading.cfg",
    ".*.baiduyun.uploading.cfg",
    "*.tmp",
    "*.temp",
    "*.swp",
    "~$*",
)

# Shared stopword set used by daily / weekly / clipping keyword scoring.
# 目标：过滤中英文里几乎不携带主题信息的高频功能词、平台字段与采集残留。
ENGLISH_STOPWORDS = {
    "the", "and", "for", "you", "your", "yours", "that", "this", "these", "those",
    "with", "from", "but", "not", "are", "was", "were", "been", "being", "have",
    "has", "had", "will", "would", "can", "could", "should", "shall", "may", "might",
    "must", "just", "only", "also", "any", "all", "some", "one", "two", "three",
    "about", "into", "onto", "out", "off", "over", "under", "than", "then", "there",
    "here", "where", "when", "what", "which", "who", "whom", "whose", "why", "how",
    "very", "much", "more", "most", "such", "still", "even", "ever", "never", "like",
    "want", "need", "know", "make", "made", "take", "give", "got", "get", "see",
    "say", "said", "tell", "told", "come", "came", "look", "looks", "way", "day",
    "time", "good", "bad", "new", "old", "big", "small", "first", "last", "next",
    "now", "today", "tomorrow", "yesterday", "our", "ours", "they", "them", "their",
    "his", "her", "hers", "him", "she", "its", "itself", "myself", "yourself",
    "themselves", "ourselves", "if", "else", "or", "nor", "as", "at", "by", "be",
    "is", "am", "an", "a", "of", "on", "in", "to", "do", "does", "did", "done",
    "so", "too", "up", "down", "back", "lot", "lots", "per", "via", "vs", "etc",
    "okay", "ok", "yeah", "yes", "no", "hi", "hey", "oh", "ah", "uh", "um",
    "post", "posts", "page", "pages", "video", "videos", "note", "notes", "item",
    "link", "links", "url", "http", "https", "www", "com", "cn", "html",
    "it", "its", "i", "me", "we", "us", "my", "mine", "don", "doesn", "didn",
    "isn", "wasn", "aren", "weren", "haven", "hasn", "hadn", "won", "wouldn",
    "shouldn", "couldn", "cannot", "can't", "don't", "won't", "i'm", "you're",
    "they're", "we're", "i've", "you've", "they've", "we've", "i'll", "you'll",
    "use", "uses", "used", "using", "try", "tries", "tried", "trying", "put",
    "puts", "putting", "go", "goes", "went", "gone", "going", "let", "lets", "letting",
    "thing", "things", "stuff", "kind", "type", "types", "part", "parts", "end",
    "start", "begin", "began", "begun", "actually", "basically", "literally",
    "probably", "maybe", "perhaps", "pretty", "really", "quite", "almost", "already",
    "another", "anyway", "anyone", "anything", "anywhere", "everyone", "everything",
    "everywhere", "someone", "something", "somewhere", "nothing", "nobody", "none",
    "few", "fewer", "many", "several", "other", "others", "another", "same", "different",
    "story", "stories", "list", "lists", "context", "content", "contents",
    "and", "or", "but", "nor", "yet", "so", "for", "since", "while", "until", "unless",
    "because", "although", "though", "whereas", "whether", "either", "neither",
}

CHINESE_STOPWORDS = {
    "的", "了", "是", "我", "你", "他", "她", "它", "们", "就", "在", "和", "跟",
    "给", "把", "被", "让", "到", "从", "对", "往", "向", "以", "用", "为", "因",
    "所", "或", "及", "与", "若", "如", "要", "想", "能", "会", "该", "却", "还",
    "也", "都", "只", "很", "更", "最", "太", "再", "又", "却", "但", "而", "呢",
    "吗", "啊", "呀", "哦", "哈", "嗯",
    "一个", "这个", "那个", "什么", "如何", "怎么", "为什么", "因为", "所以",
    "可以", "可能", "不是", "没有", "自己", "我们", "他们", "你们", "时候",
    "进行", "通过", "以及", "还是", "其实", "非常", "很多", "真的", "现在",
    "作者", "天前", "小时前", "分钟前", "昨天", "今天", "明天", "刚刚",
    "采集", "网页", "回复", "评论", "条评论", "点赞", "收藏", "分享", "关注",
    "小红书", "笔记", "全文", "展开", "更多", "链接", "原文", "阅读", "浏览",
    "视频", "图片", "发布", "来自", "平台", "账号", "用户", "博主",
    "内容", "来源", "标题", "正文",
}

# Composite set exposed to other scripts. Import as `STOPWORDS` for consistency.
STOPWORDS = ENGLISH_STOPWORDS | CHINESE_STOPWORDS


def is_stopword(token: str) -> bool:
    """Return True if the normalized token should be dropped from keyword output."""
    if not token:
        return True
    token = token.strip().lower()
    if not token:
        return True
    if token.isdigit():
        return True
    if len(token) < 2:
        return True
    if token in STOPWORDS:
        return True
    # Single-letter English tokens are noise; keep 2+ letters (e.g. "ai", "ui", "os").
    if re.fullmatch(r"[a-z]", token):
        return True
    return False


def should_ignore_path(path: Path) -> bool:
    """Return True for sync/system/cache files that should not enter knowledge workflows."""
    parts = set(path.parts)
    if parts & IGNORE_PARTS:
        return True
    name = path.name
    if name in IGNORE_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in IGNORE_PATTERNS)


def iter_markdown_files(root: Path, recursive: bool = True) -> Iterable[Path]:
    """Yield markdown files under root while applying shared ignore rules."""
    if not root.exists():
        return
    iterator = root.rglob("*.md") if recursive else root.glob("*.md")
    for path in iterator:
        if should_ignore_path(path):
            continue
        yield path


@dataclass
class PreflightResult:
    root: Path
    config_exists: bool
    readable: bool
    writable: bool
    layer_status: Dict[str, Dict[str, str]]
    subfolder_status: Dict[str, Dict[str, str]]
    missing_paths: List[Path]
    state: str


def _merge_dict(default: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(default)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> Dict[str, Any]:
    """Load local config, falling back to canonical defaults."""
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        user_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"配置文件 JSON 解析失败：{CONFIG_PATH}\n{exc}") from exc
    if not isinstance(user_config, dict):
        raise SystemExit(f"配置文件格式错误：{CONFIG_PATH} 顶层必须是 JSON object")
    return _merge_dict(DEFAULT_CONFIG, user_config)


CONFIG = load_config()


def rel_path(section: str, key: str) -> str:
    try:
        value = CONFIG[section][key]
    except KeyError as exc:
        raise SystemExit(f"配置缺失：{section}.{key}") from exc
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"配置无效：{section}.{key} 必须是非空字符串")
    return value


def resolve_config_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return VAULT / path


def layer_path(key: str) -> Path:
    return resolve_config_path(rel_path("layers", key))


def subfolder_path(key: str) -> Path:
    return resolve_config_path(rel_path("subfolders", key))


def scripts_dir() -> Path:
    return resolve_config_path(CONFIG.get("scripts", {}).get("dir", "scripts"))


def runner_path() -> Path:
    return resolve_config_path(CONFIG.get("scripts", {}).get("runner", "scripts/run_all.py"))


def system_intro_path() -> Path:
    default = DEFAULT_CONFIG["docs"]["systemIntro"]
    value = CONFIG.get("docs", {}).get("systemIntro", default)
    return resolve_config_path(value)


def automation_config() -> Dict[str, Any]:
    auto = CONFIG.get("automation") or {}
    merged = dict(DEFAULT_CONFIG["automation"])
    if isinstance(auto, dict):
        merged.update(auto)
    return merged


def automation_interval_days() -> Optional[int]:
    value = automation_config().get("dailyIntervalDays")
    if value is None:
        return None
    try:
        interval = int(value)
    except (TypeError, ValueError):
        return None
    if interval < 1:
        return None
    return interval


def automation_scan_days() -> int:
    value = automation_config().get("dailyScanDays", 2)
    try:
        scan = int(value)
    except (TypeError, ValueError):
        scan = 2
    return max(1, scan)


def automation_run_hour() -> int:
    value = automation_config().get("dailyRunAtHour", 9)
    try:
        hour = int(value)
    except (TypeError, ValueError):
        hour = 9
    return max(0, min(23, hour))


def save_automation_settings(
    interval_days: Optional[int] = None,
    scan_days: Optional[int] = None,
    run_hour: Optional[int] = None,
    ask_on_first_use: Optional[bool] = None,
) -> Path:
    """Merge automation settings into the saved config without touching other fields."""
    on_disk: Dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            on_disk = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            on_disk = {}
    if not isinstance(on_disk, dict):
        on_disk = {}
    auto = on_disk.get("automation")
    if not isinstance(auto, dict):
        auto = {}
    if interval_days is not None:
        auto["dailyIntervalDays"] = int(interval_days)
    if scan_days is not None:
        auto["dailyScanDays"] = int(scan_days)
    if run_hour is not None:
        auto["dailyRunAtHour"] = int(run_hour)
    if ask_on_first_use is not None:
        auto["askOnFirstUse"] = bool(ask_on_first_use)
    on_disk["automation"] = auto
    CONFIG_PATH.write_text(json.dumps(on_disk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Refresh in-memory config so subsequent calls in this process see the update.
    globals()["CONFIG"] = load_config()
    return CONFIG_PATH


def render_system_intro(interval_days: Optional[int] = None) -> str:
    """Render the '📚 知识迭代系统说明.md' body based on the current config + optional interval override."""
    interval = interval_days if interval_days is not None else automation_interval_days()
    scan_days = automation_scan_days()
    run_hour = automation_run_hour()
    if interval is None:
        automation_line = "未开启自动定时（需手动跑 `python3 scripts/run_all.py --only daily`）"
    elif interval == 1:
        automation_line = f"每天 {run_hour:02d}:00 自动跑每日蒸馏（每次扫描最近 {scan_days} 天）"
    else:
        automation_line = f"每 {interval} 天 {run_hour:02d}:00 自动跑每日蒸馏（每次扫描最近 {scan_days} 天）"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# 📚 知识迭代系统说明",
        "",
        "> 基于 Karpathy 知识库理念打造的四层知识蒸馏系统（由 knowledge-iteration-system skill 一键生成）。",
        "",
        "## 四层架构",
        "",
        "```",
        "📁 第一层：输入层 (Inbox)",
        "├── 📁 想法/灵感集      ← 随手丢、不整理",
        "└── 📁 Clippings         ← 外部抓取内容（小红书/B站/微信等）",
        "",
        "📁 第二层：蒸馏层 (Distilled)",
        "├── 📁 每日蒸馏            ← daily_distill.py",
        "├── 📁 每周复盘            ← weekly_review.py",
        "├── 📁 想法追踪           ← idea_tracker.py",
        "├── 📁 Clippings提炼      ← clipping_refiner.py（含卡片化提炼）",
        "└── 📁 结构性链接建议   ← link_suggester.py",
        "",
        "📁 第三层：技能层 (Skills)   ← skill_detector.py + 人工升级",
        "",
        "📁 第四层：输出层 (Output)   ← feedback_loop.py",
        "```",
        "",
        "## 日常使用节奏",
        "",
        "1. 有想法就丢进 《想法/灵感集》，不需要整理。",
        "2. 看到好内容就存入《Clippings》（小红书拓展、Obsidian Web Clipper 等）。",
        "3. 自动化定时跑每日蒸馏，手动跑 `run_all.py` 做入号蒸馏。",
        "4. 花 10 分钟看蒸馏报告，标记重点，沉淀到想法追踪或 Skill 候选。",
        "5. 每周看一次每周复盘，定下周方向。",
        "",
        "## 自动化已配置",
        "",
        f"- 自动运行设置：**{automation_line}**",
        f"- 扫描窗口：最近 **{scan_days}** 天新增内容",
        "- 自动化安装入口：`scripts/install_automation.sh`（macOS）/ `install_automation.ps1`（Windows）/ `install_automation_linux.sh`（Linux）",
        "- 修改自动化间隔：`python3 scripts/setup_preflight.py --set-daily-interval N` 后重新跑安装脚本",
        "",
        "## 核心脚本一览",
        "",
        "| 脚本 | 功能 | 常用命令 |",
        "|------|------|----------|",
        "| `scripts/setup_preflight.py` | 首次安装预检 / 创建四层目录 / 配置自动化间隔 | `python3 scripts/setup_preflight.py --create-missing` |",
        "| `scripts/daily_distill.py` | 每日知识蒸馏 | `python3 scripts/daily_distill.py --days 2` |",
        "| `scripts/weekly_review.py` | 每周知识复盘 | `python3 scripts/weekly_review.py` |",
        "| `scripts/idea_tracker.py` | 想法成熟度追踪 | `python3 scripts/idea_tracker.py` |",
        "| `scripts/clipping_refiner.py` | Clippings 提炼 + 卡片 | `python3 scripts/clipping_refiner.py` |",
        "| `scripts/skill_detector.py` | Skill 候选检测 | `python3 scripts/skill_detector.py` |",
        "| `scripts/link_suggester.py` | 结构性双链建议 | `python3 scripts/link_suggester.py` |",
        "| `scripts/feedback_loop.py` | 输出反馈回流 | `python3 scripts/feedback_loop.py` |",
        "| `scripts/quarterly_audit.py` | 季度知识健康审计 | `python3 scripts/quarterly_audit.py` |",
        "| `scripts/run_all.py` | 一键全量跑 | `python3 scripts/run_all.py --dry-run --preflight` |",
        "",
        "## 想法成熟度模型",
        "",
        "| 阶段 | 标记 | 特征 |",
        "|------|------|------|",
        "| 种子想法 | 🌱 | 只有一个点子，几句话描述 |",
        "| 发芽想法 | 🌿 | 有框架，关联了相关资料 |",
        "| 成熟想法 | 🌳 | 完整实施方案，可落地 |",
        "| 已落地 | ✅ | 已产出成果，回流到知识库 |",
        "",
        "## 第一次使用建议",
        "",
        "1. 跑 `python3 scripts/setup_preflight.py --create-missing` 初始化四层。",
        "2. 带 `--days 30` 跑一次 `daily_distill.py` 蒸馏历史内容。",
        "3. 跑 `python3 scripts/clipping_refiner.py` 把已有 Clippings 提炼为卡片。",
        "4. 跑 `python3 scripts/skill_detector.py` 看看有哪些内容可以沉淀为 Skill 草稿。",
        "5. 选时间间隔后，跑 `bash scripts/install_automation.sh` 安装自动化。",
        "",
        f"*本文件由系统在 {now} 自动生成，修改自动化配置后会重新写入。*",
        "",
    ]
    return "\n".join(lines)


def write_system_intro(interval_days: Optional[int] = None, overwrite: bool = True) -> Path:
    path = system_intro_path()
    if path.exists() and not overwrite:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_system_intro(interval_days=interval_days), encoding="utf-8")
    return path


def ensure_dirs(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def is_writable(path: Path) -> bool:
    if not path.exists():
        return os.access(path.parent if path.parent.exists() else VAULT, os.W_OK)
    return os.access(path, os.W_OK)


def candidate_layer_path(key: str) -> Path | None:
    configured = layer_path(key)
    if configured.exists():
        return configured
    for alias in LAYER_ALIASES.get(key, ()):  # one-level scan only; do not crawl the whole disk
        candidate = VAULT / alias
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def preflight() -> PreflightResult:
    layers: Dict[str, Dict[str, str]] = {}
    subfolders: Dict[str, Dict[str, str]] = {}
    missing: List[Path] = []

    for key in ("inbox", "distilled", "skills", "output"):
        configured = layer_path(key)
        found = candidate_layer_path(key)
        if found:
            status = "已找到" if found == configured else "待确认"
            layers[key] = {"status": status, "path": str(found)}
        else:
            layers[key] = {"status": "缺失", "path": str(configured)}
            missing.append(configured)

    for key in ("ideas", "clippings", "dailyDistill", "weeklyReview", "ideaTracking", "clippingRefine", "linkSuggestions"):
        path = subfolder_path(key)
        if path.exists():
            subfolders[key] = {"status": "已找到", "path": str(path)}
        else:
            subfolders[key] = {"status": "缺失", "path": str(path)}
            missing.append(path)

    layer_statuses = {v["status"] for v in layers.values()}
    if all(v["status"] == "已找到" for v in layers.values()) and not missing:
        state = "完整标准结构"
    elif all(v["status"] == "缺失" for v in layers.values()):
        state = "无四层结构"
    elif "待确认" in layer_statuses:
        state = "已有类似结构需映射"
    else:
        state = "部分缺失"

    return PreflightResult(
        root=VAULT,
        config_exists=CONFIG_PATH.exists(),
        readable=os.access(VAULT, os.R_OK),
        writable=is_writable(VAULT),
        layer_status=layers,
        subfolder_status=subfolders,
        missing_paths=missing,
        state=state,
    )


def write_default_config(overwrite: bool = False) -> Path:
    if CONFIG_PATH.exists() and not overwrite:
        return CONFIG_PATH
    CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return CONFIG_PATH


def create_missing_structure(dry_run: bool = False) -> List[Path]:
    result = preflight()
    unique_missing = []
    seen = set()
    for path in result.missing_paths:
        if path in seen:
            continue
        seen.add(path)
        unique_missing.append(path)
    if not dry_run:
        ensure_dirs(unique_missing)
        write_default_config(overwrite=False)
    return unique_missing


def print_preflight_report(result: PreflightResult | None = None) -> None:
    result = result or preflight()
    print("# 四层知识系统检查结果")
    print()
    print("## 1. 知识库路径")
    print(f"- 根路径：{result.root}")
    print(f"- 是否存在：{'是' if result.root.exists() else '否'}")
    print(f"- 是否可读：{'是' if result.readable else '否'}")
    print(f"- 是否可写：{'是' if result.writable else '否'}")
    print(f"- 配置文件：{'已找到' if result.config_exists else '未找到'}")
    print()
    print("## 2. 四层映射")
    labels = {"inbox": "输入层 Inbox", "distilled": "蒸馏层 Distilled", "skills": "技能层 Skills", "output": "输出层 Output"}
    for key, label in labels.items():
        item = result.layer_status[key]
        print(f"- {label}：{item['status']} → {item['path']}")
    print()
    print("## 3. 子文件夹检查")
    for key, item in result.subfolder_status.items():
        print(f"- {key}：{item['status']} → {item['path']}")
    print()
    print("## 4. 检查结论")
    print(f"- 当前状态：{result.state}")
    if result.missing_paths:
        print("- 缺失项：")
        for path in result.missing_paths:
            print(f"  - {path}")
    else:
        print("- 缺失项：无")


if __name__ == "__main__":
    print_preflight_report()
