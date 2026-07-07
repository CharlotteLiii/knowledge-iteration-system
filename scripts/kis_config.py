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
        "ideas": "第一层：输入层 (Inbox)/想法",
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
        # 旧字段，保留兼容 v0.1.x 行为。新安装将依据 `tasks` 字段。
        "dailyIntervalDays": None,
        "dailyScanDays": 2,
        "dailyRunAtHour": 9,
        "askOnFirstUse": True,
        # v0.2+：多任务调度表。每个任务独立 schedule / 时间。
        # schedule 支持：
        #   daily              → hour, minute
        #   weekly             → dayOfWeek(0=Sun..6=Sat), hour, minute
        #   quarterly-last-day → hour, minute（在 3/31 6/30 9/30 12/31 触发）
        # 默认时间与用户声明一致：
        #   每日知识蒸馏          21:00
        #   想法成熟度追踪           21:05（错开 5min，避免同时启动 & LLM 扎堆）
        #   Clippings 提炼 + 卡片   21:10
        #   Skill 候选检测           21:15
        #   结构性双链建议         21:20
        #   Skill 升级路线图         21:25（紧跟 link_suggester 后 5min）
        #   输出反馈回流           21:30
        #   每周知识复盘           周日 14:00
        #   季度知识健康审计       季度最后一天 12:00
        "tasks": {
            "daily_distill": {
                "label": "每日知识蒸馏",
                "script": "daily_distill.py",
                "args": [],
                "schedule": "daily",
                "hour": 21,
                "minute": 0,
                "enabled": True,
            },
            "idea_tracker": {
                "label": "想法成熟度追踪",
                "script": "idea_tracker.py",
                "args": [],
                "schedule": "daily",
                "hour": 21,
                "minute": 5,
                "enabled": True,
            },
            "clipping_refiner": {
                "label": "Clippings 提炼 + 卡片",
                "script": "clipping_refiner.py",
                "args": [],
                "schedule": "daily",
                "hour": 21,
                "minute": 10,
                "enabled": True,
            },
            "skill_detector": {
                "label": "Skill 候选检测",
                "script": "skill_detector.py",
                "args": ["--llm=auto"],
                "schedule": "daily",
                "hour": 21,
                "minute": 15,
                "enabled": True,
            },
            "link_suggester": {
                "label": "结构性双链建议",
                "script": "link_suggester.py",
                "args": [],
                "schedule": "daily",
                "hour": 21,
                "minute": 20,
                "enabled": True,
            },
            "skill_upgrader": {
                "label": "Skill 升级路线图",
                "script": "skill_upgrader.py",
                "args": [],
                "schedule": "daily",
                "hour": 21,
                "minute": 25,
                "enabled": True,
            },
            "feedback_loop": {
                "label": "输出反馈回流",
                "script": "feedback_loop.py",
                "args": [],
                "schedule": "daily",
                "hour": 21,
                "minute": 30,
                "enabled": True,
            },
            "weekly_review": {
                "label": "每周知识复盘",
                "script": "weekly_review.py",
                "args": [],
                "schedule": "weekly",
                "dayOfWeek": 0,  # Sunday
                "hour": 14,
                "minute": 0,
                "enabled": True,
            },
            "quarterly_audit": {
                "label": "季度知识健康审计",
                "script": "quarterly_audit.py",
                "args": [],
                "schedule": "quarterly-last-day",
                "hour": 12,
                "minute": 0,
                "enabled": True,
            },
        },
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


# ---------------------------------------------------------------------------
# Taxonomy（知识分类 / 主题 / 桥接规则）可配置来源
#
# 默认值来自 scripts/taxonomy.default.json（与历史硬编码逐字节一致）。
# 用户可在知识库根目录放 taxonomy.json 做深合并覆盖（缺省字段回落 default）。
# link_suggester.py 与 clipping_refiner.py 都从这里读取，消除三套关键词表
# 各自维护、互相漂移的老问题。
# ---------------------------------------------------------------------------

TAXONOMY_DEFAULT_PATH = SCRIPT_DIR / "taxonomy.default.json"
TAXONOMY_USER_NAME = "taxonomy.json"
TAXONOMY_USER_PATH = VAULT / TAXONOMY_USER_NAME


def load_taxonomy() -> Dict[str, Any]:
    """Load taxonomy defaults, then deep-merge an optional user override.

    Default source: scripts/taxonomy.default.json (ships with the Skill).
    User override: <vault>/taxonomy.json (optional). Missing keys fall back
    to defaults via the same deep-merge used for the main config.
    """
    if not TAXONOMY_DEFAULT_PATH.exists():
        raise SystemExit(f"分类配置缺失：{TAXONOMY_DEFAULT_PATH}")
    try:
        base = json.loads(TAXONOMY_DEFAULT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"分类默认配置 JSON 解析失败：{TAXONOMY_DEFAULT_PATH}\n{exc}") from exc
    if not isinstance(base, dict):
        raise SystemExit(f"分类默认配置格式错误：{TAXONOMY_DEFAULT_PATH} 顶层必须是 JSON object")

    if TAXONOMY_USER_PATH.exists():
        try:
            user = json.loads(TAXONOMY_USER_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"分类用户配置 JSON 解析失败：{TAXONOMY_USER_PATH}\n{exc}") from exc
        if not isinstance(user, dict):
            raise SystemExit(f"分类用户配置格式错误：{TAXONOMY_USER_PATH} 顶层必须是 JSON object")
        # `_replace`: 列出的段做整段替换而非深合并（用于用户完全重定义分类/主题时不残留默认旧项）。
        # 不写 `_replace` 时保持原深合并行为，向后兼容。
        replace_sections = user.get("_replace") or []
        if not isinstance(replace_sections, list):
            raise SystemExit(f"分类用户配置错误：`_replace` 必须是字符串数组：{TAXONOMY_USER_PATH}")
        user_clean = {k: v for k, v in user.items() if k != "_replace"}
        merged = _merge_dict(base, user_clean)
        for section in replace_sections:
            if section in user_clean:
                merged[section] = user_clean[section]
        base = merged
    return base


TAXONOMY = load_taxonomy()


def content_types() -> Dict[str, Dict[str, Any]]:
    """{ctype: {keywords: [...], asset: str, priority: float}}"""
    return TAXONOMY.get("contentTypes", {})


def type_shortcuts() -> List[Dict[str, Any]]:
    """Ordered hard-short-circuit rules for content-type detection."""
    return TAXONOMY.get("typeShortcuts", [])


def tag_rules() -> Dict[str, List[str]]:
    """{tag: [keyword, ...]} for auto_tags."""
    return TAXONOMY.get("tagRules", {})


def themes() -> Dict[str, List[str]]:
    """{theme: [keyword, ...]} for structural-link theme matching."""
    return TAXONOMY.get("themes", {})


def bridges() -> Dict[str, List[str]]:
    """{content_type: [theme, ...]} bridge rules for clipping<->idea linking."""
    return TAXONOMY.get("bridges", {})


def domain_rules() -> List[Dict[str, Any]]:
    """Ordered domain heuristics for clipping<->idea bridge scoring."""
    return TAXONOMY.get("domainRules", [])


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


# ---------------------------------------------------------------------------
# v0.2+: per-task automation table helpers
# ---------------------------------------------------------------------------

VALID_SCHEDULES: Tuple[str, ...] = ("daily", "weekly", "quarterly-last-day")

# Task key order is the recommended run order (used by installers when preserving
# task order for logs / summaries). Do not sort alphabetically.
TASK_ORDER: Tuple[str, ...] = (
    "daily_distill",
    "idea_tracker",
    "clipping_refiner",
    "skill_detector",
    "link_suggester",
    "skill_upgrader",
    "feedback_loop",
    "weekly_review",
    "quarterly_audit",
)


def _default_tasks() -> Dict[str, Dict[str, Any]]:
    return json.loads(json.dumps(DEFAULT_CONFIG["automation"]["tasks"]))  # deep copy


def automation_tasks() -> Dict[str, Dict[str, Any]]:
    """Return the merged per-task automation table.

    Merges user overrides in `.knowledge-iteration-system.json` over the defaults
    from `DEFAULT_CONFIG`. Unknown task keys from user config are preserved (so
    users can add custom tasks); unknown fields on known tasks are also preserved.
    """
    defaults = _default_tasks()
    user_tasks = automation_config().get("tasks")
    if not isinstance(user_tasks, dict):
        return defaults
    merged = dict(defaults)
    for key, override in user_tasks.items():
        if not isinstance(override, dict):
            continue
        base = dict(merged.get(key, {}))
        base.update(override)
        merged[key] = base
    return merged


def ordered_task_items() -> List[Tuple[str, Dict[str, Any]]]:
    """Return tasks in canonical order; unknown user tasks appended at the end."""
    tasks = automation_tasks()
    seen = set()
    result: List[Tuple[str, Dict[str, Any]]] = []
    for key in TASK_ORDER:
        if key in tasks:
            result.append((key, tasks[key]))
            seen.add(key)
    for key, cfg in tasks.items():
        if key not in seen:
            result.append((key, cfg))
    return result


def validate_task(key: str, task: Dict[str, Any]) -> List[str]:
    """Return a list of validation error messages for a task config. Empty = valid."""
    errors: List[str] = []
    schedule = task.get("schedule")
    if schedule not in VALID_SCHEDULES:
        errors.append(f"[{key}] schedule '{schedule}' 无效，需为 {VALID_SCHEDULES}")
    hour = task.get("hour", 9)
    minute = task.get("minute", 0)
    try:
        if not (0 <= int(hour) <= 23):
            errors.append(f"[{key}] hour {hour} 越界 (0-23)")
    except (TypeError, ValueError):
        errors.append(f"[{key}] hour {hour!r} 不是整数")
    try:
        if not (0 <= int(minute) <= 59):
            errors.append(f"[{key}] minute {minute} 越界 (0-59)")
    except (TypeError, ValueError):
        errors.append(f"[{key}] minute {minute!r} 不是整数")
    if schedule == "weekly":
        dow = task.get("dayOfWeek", 0)
        try:
            if not (0 <= int(dow) <= 6):
                errors.append(f"[{key}] dayOfWeek {dow} 越界 (0=Sun..6=Sat)")
        except (TypeError, ValueError):
            errors.append(f"[{key}] dayOfWeek {dow!r} 不是整数")
    script = task.get("script")
    if not isinstance(script, str) or not script.strip():
        errors.append(f"[{key}] script 必须是非空字符串")
    return errors


def parse_hhmm(value: str) -> Tuple[int, int]:
    """Parse 'HH:MM' or 'H:M' into (hour, minute). Raises ValueError on bad input."""
    text = value.strip()
    if ":" not in text:
        raise ValueError(f"时间格式无效：{value!r}，需为 HH:MM")
    hh, mm = text.split(":", 1)
    hour = int(hh)
    minute = int(mm)
    if not (0 <= hour <= 23):
        raise ValueError(f"小时越界：{hour}")
    if not (0 <= minute <= 59):
        raise ValueError(f"分钟越界：{minute}")
    return hour, minute


def save_task_settings(
    updates: Dict[str, Dict[str, Any]],
) -> Path:
    """Merge per-task overrides into config['automation']['tasks'].

    updates: {task_key: {field: value, ...}, ...}
    Only the fields present in each update are touched; other fields keep their
    current effective value (defaults + previously saved user overrides).
    """
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
    tasks = auto.get("tasks")
    if not isinstance(tasks, dict):
        tasks = {}
    for key, patch in updates.items():
        existing = tasks.get(key)
        if not isinstance(existing, dict):
            existing = {}
        existing.update(patch)
        tasks[key] = existing
    auto["tasks"] = tasks
    on_disk["automation"] = auto
    CONFIG_PATH.write_text(json.dumps(on_disk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    globals()["CONFIG"] = load_config()
    return CONFIG_PATH


def render_system_intro(interval_days: Optional[int] = None) -> str:
    """Render the '📚 知识迭代系统说明.md' body based on the current config + optional interval override.

    interval_days is legacy: 若显式传入，则覆盖 daily_distill 的展示信息；
    per-task 表始终按 automation_tasks() 真实值渲染。
    """
    scan_days = automation_scan_days()
    tasks = automation_tasks()
    dow_labels = ("周日", "周一", "周二", "周三", "周四", "周五", "周六")

    def _fmt_when(cfg: Dict[str, Any]) -> str:
        sched = cfg.get("schedule", "daily")
        hh = int(cfg.get("hour", 9))
        mm = int(cfg.get("minute", 0))
        hhmm = f"{hh:02d}:{mm:02d}"
        if sched == "daily":
            return f"每天 {hhmm}"
        if sched == "weekly":
            dow = int(cfg.get("dayOfWeek", 0))
            return f"每周{dow_labels[dow]} {hhmm}"
        if sched == "quarterly-last-day":
            return f"季度最后一天 {hhmm}"
        return f"{sched} {hhmm}"

    def _local_ordered():
        seen = set()
        out = []
        for k in TASK_ORDER:
            if k in tasks:
                out.append((k, tasks[k])); seen.add(k)
        for k, c in tasks.items():
            if k not in seen:
                out.append((k, c))
        return out

    enabled_tasks = [(k, c) for k, c in _local_ordered() if c.get("enabled", True)]
    if enabled_tasks:
        automation_line = f"per-task 自动化表已启用 {len(enabled_tasks)} 个任务（详见下表），跑 `bash scripts/install_automation.sh` 安装成本机定时任务"
    else:
        automation_line = "所有自动化任务当前禁用（需手动跑 `python3 scripts/run_all.py`）"

    # Interval override 兼容 legacy：只影响 daily_distill 那一行的展示
    if interval_days is not None and "daily_distill" in tasks:
        dd = dict(tasks["daily_distill"])
        if interval_days >= 1:
            dd["_legacy_interval_note"] = f"（legacy interval={interval_days} 天）"
        tasks["daily_distill"] = dd

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
        "├── 📁 结构性链接建议   ← link_suggester.py",
        "└── 📄 输出回流分析.md   ← feedback_loop.py",
        "",
        "📁 第三层：技能层 (Skills)",
        "├── 📁 待整理/EVAL_*.md    ← skill_detector.py 生成候选卡",
        "└── 📄 Skill 升级路线图.md ← skill_upgrader.py 生成升级建议",
        "",
        "📁 第四层：输出层 (Output)",
        "└── 📁 已发表               ← feedback_loop.py 扫描并总结发布反馈",
        "```",
        "",
        "## 日常使用节奏",
        "",
        "1. 有想法就丢进《想法/灵感集》，不需要整理。",
        "2. 看到好内容就存入《Clippings》（小红书拓展、Obsidian Web Clipper 等）。",
        "3. 自动化按 per-task 表定时跑（默认覆盖每日蒸馏 / 想法追踪 / Clipping 提炼 / Skill 检测 / 链接建议 / 反馈回流 / 每周复盘 / 季度审计）；想补历史或手动全量跑就 `python3 scripts/run_all.py`。",
        "4. 花 10 分钟看蒸馏报告，标记重点，沉淀到想法追踪或 Skill 候选。",
        "5. 每周看一次每周复盘，定下周方向。",
        "",
        "## 自动化已配置",
        "",
        f"- 状态：**{automation_line}**",
        f"- 每日蒸馏扫描窗口：最近 **{scan_days}** 天新增内容",
        "- 安装入口：`bash scripts/install_automation.sh`（macOS 9 个 LaunchAgent）/ `install_automation.ps1`（Windows Task Scheduler）/ `install_automation_linux.sh`（Linux cron）",
        "- 查看/修改任务：`python3 scripts/setup_preflight.py --list-tasks` / `--set-task NAME=HH:MM` / `--enable-task NAME` / `--disable-task NAME` / `--ask-tasks`（交互向导）",
        "- Legacy 兼容：`--set-daily-interval N` 仍可用，仅改 daily_distill 的间隔展示；建议直接用 per-task 命令",
        "",
        "### 当前任务表",
        "",
        "| 任务 | 脚本 | 触发时间 | 启用 |",
        "|------|------|----------|------|",
    ]
    for key, cfg in _local_ordered():
        label = cfg.get("label", key)
        script = cfg.get("script", "")
        when = _fmt_when(cfg)
        note = cfg.get("_legacy_interval_note", "")
        enabled = "✅" if cfg.get("enabled", True) else "⏸️"
        lines.append(f"| {label} (`{key}`) | `scripts/{script}` | {when}{note} | {enabled} |")

    lines.extend([
        "",
        "## 核心脚本一览",
        "",
        "| 脚本 | 功能 | 常用命令 |",
        "|------|------|----------|",
        "| `scripts/setup_preflight.py` | 首次安装预检 / 创建四层目录 / 管理自动化任务表 | `python3 scripts/setup_preflight.py --create-missing` |",
        "| `scripts/daily_distill.py` | 每日知识蒸馏 | `python3 scripts/daily_distill.py --days 2` |",
        "| `scripts/weekly_review.py` | 每周知识复盘 | `python3 scripts/weekly_review.py` |",
        "| `scripts/idea_tracker.py` | 想法成熟度追踪 | `python3 scripts/idea_tracker.py` |",
        "| `scripts/clipping_refiner.py` | Clippings 提炼 + 卡片 | `python3 scripts/clipping_refiner.py` |",
        "| `scripts/skill_detector.py` | Skill 候选检测（支持 `--llm=off/auto/api/file`） | `python3 scripts/skill_detector.py --llm=auto` |",
        "| `scripts/link_suggester.py` | 结构性双链建议（`--apply-approved` 写回勾选项） | `python3 scripts/link_suggester.py` |",
        "| `scripts/skill_upgrader.py` | 读取 EVAL 卡生成 Skill 升级路线图 | `python3 scripts/skill_upgrader.py` |",
        "| `scripts/feedback_loop.py` | 输出反馈回流（可选 `--llm --sample N`） | `python3 scripts/feedback_loop.py` |",
        "| `scripts/quarterly_audit.py` | 季度知识健康审计 | `python3 scripts/quarterly_audit.py` |",
        "| `scripts/run_all.py` | 一键全量跑 9 步 | `python3 scripts/run_all.py`（先预览可加 `--dry-run --preflight`） |",
        "",
        "## LLM 兜底（默认关闭）",
        "",
        "- 只有 `skill_detector.py` 和 `feedback_loop.py` 会调 LLM，其它脚本纯本地。",
        "- 启用条件：设置 `KIS_LLM_API_KEY` / `OPENAI_API_KEY`，或在 `.env` / 配置里填 `llm.enabled: true`。",
        "- 隐私边界：启用后 Clipping / 想法原文会切片发到你配置的端点；敏感内容请保持默认关闭。",
        "- `skill_detector.py --llm=<off|auto|api|file>` 四种模式，`file` 模式走本地文件桥手动拷贴。",
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
        "5. 用 `python3 scripts/setup_preflight.py --list-tasks` 查看默认时间，必要时 `--set-task NAME=HH:MM` 调整，然后跑 `bash scripts/install_automation.sh` 安装自动化。",
        "",
        f"*本文件由系统在 {now} 自动生成，修改自动化配置后会重新写入。*",
        "",
    ])
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
