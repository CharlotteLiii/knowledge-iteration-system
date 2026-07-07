#!/usr/bin/env python3
"""每日知识蒸馏：扫描新增内容，生成“人工解读版”日报。"""
from __future__ import annotations

import argparse
import hashlib
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from kis_config import iter_markdown_files, is_stopword, subfolder_path
import kis_state
import kis_catalog
from kis_classifier import build_classifier, OTHER

TASK_KEY = "daily_distill"

IDEAS_PATH = subfolder_path("ideas")
CLIPPINGS_PATH = subfolder_path("clippings")
OUTPUT_PATH = subfolder_path("dailyDistill")
SCAN_PATHS = [IDEAS_PATH, CLIPPINGS_PATH]

# 领域专用噪声词（共享停用词已包含中英文高频功能词）。
EXTRA_NOISE = {
    "iframe", "bilibili", "player", "frameborder", "allowfullscreen", "transcript",
    "description", "src", "href", "img", "png", "jpg", "jpeg", "gif",
    "xhs", "xiaohongshu", "webshare", "xsec", "token", "discovery", "item", "pc_web",
    "douyin", "weixin", "weibo",
}

THEME_RULES: Dict[str, Dict[str, object]] = {
    "AI 工具化工作流": {
        "keywords": ["ai", "agent", "codex", "claude", "gpt", "prompt", "提示词", "自动化", "工作流", "obsidian", "智能体"],
        "asset": "工作流 / Prompt 模板 / Skill 候选",
        "next": "提炼成可复用步骤：输入是什么、怎么跑、输出是什么、什么时候不适用。",
    },
    "女性内容 IP 与商业化": {
        "keywords": ["女性", "女性主义", "中女", "女性博主", "内容商业化", "ip变现", "阅读赚钱", "书籍合作"],
        "asset": "账号栏目 / 输出选题 / 内容方法论",
        "next": "拆成栏目：今日概念、个人反思、行动记录、女性成长案例、观点表达。",
    },
    "美业经营与客户资产": {
        "keywords": ["美业", "客户资产", "客户运营", "美业投资", "风险管控", "复购", "私域", "门店"],
        "asset": "商业方法论 / 运营系统 / 案例素材",
        "next": "补充客户分层、复购机制、风险指标和可落地的表格模板。",
    },
    "职业机会与成长": {
        "keywords": ["remote", "远程", "求职", "面试", "职业", "打工人", "ai公司", "成长", "学习路径"],
        "asset": "机会清单 / 学习路径 / 行动计划",
        "next": "整理成机会雷达：岗位、要求、入口、需要补的作品集材料。",
    },
    "创意表达与长期叙事": {
        "keywords": ["街头采访", "30年后的世界", "游戏灵感", "故事", "梦", "蝴蝶", "小猫", "创意", "叙事"],
        "asset": "内容企划 / 视觉概念 / 故事素材",
        "next": "挑一个最有画面感的点，写一句话概念和 3 个样稿标题。",
    },
    "生活空间与秩序感": {
        "keywords": ["家居", "收纳", "一体式收纳", "房间整理"],
        "asset": "设计原则 / 实用清单 / 案例素材",
        "next": "整理成问题-原则-方案-注意事项的设计卡片。",
    },
}


def safe_read(path: Path, max_chars: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception as exc:
        return f"读取失败：{exc}"


def strip_frontmatter(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1 :])
    return content


def clean_text(content: str) -> str:
    content = strip_frontmatter(content)
    content = re.sub(r"<iframe.*?</iframe>", " ", content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r"<[^>]+>", " ", content)
    content = re.sub(r"```.+?```", " ", content, flags=re.DOTALL)
    content = re.sub(r"https?://\S+", " ", content)
    drop_patterns = (
        r"^\s*(?:发布时间|编辑时间|作者|地区|IP属地|点赞|收藏|评论|分享)[：:].*$",
        r"^\s*(?:一、基础数据|三、前\s*\d+\s*条评论|四、点点 AI 回复原文).*$",
        r"^\s*\*\*?(?:Description|Transcript)\*\*?.*$",
    )
    lines = []
    for line in content.splitlines():
        if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in drop_patterns):
            continue
        lines.append(line)
    content = "\n".join(lines)
    content = re.sub(r"\s+", " ", content)
    return content.strip()


def _build_file_entry(fpath: Path) -> Dict[str, object]:
    mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
    category = "想法" if IDEAS_PATH in fpath.parents or fpath.parent == IDEAS_PATH else "Clippings"
    content = safe_read(fpath)
    return {
        "path": fpath,
        "name": fpath.stem,
        "mtime": mtime,
        "category": category,
        "content": content,
        "clean": clean_text(content),
    }


def get_today_files(days_back: int = 1) -> List[Dict[str, object]]:
    """时间窗模式：扫描最近 days_back 天内 mtime 落入窗口的文件（手动覆盖用）。"""
    cutoff = datetime.now() - timedelta(days=days_back)
    files: List[Dict[str, object]] = []
    for base_path in SCAN_PATHS:
        if not base_path.exists():
            continue
        for fpath in iter_markdown_files(base_path):
            mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
            if mtime < cutoff:
                continue
            files.append(_build_file_entry(fpath))
    return sorted(files, key=lambda x: x["mtime"], reverse=True)


def get_files_since(since: datetime) -> List[Dict[str, object]]:
    """时间窗模式：扫描 mtime >= since 的文件（--since 手动覆盖用）。"""
    files: List[Dict[str, object]] = []
    for base_path in SCAN_PATHS:
        if not base_path.exists():
            continue
        for fpath in iter_markdown_files(base_path):
            mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
            if mtime < since:
                continue
            files.append(_build_file_entry(fpath))
    return sorted(files, key=lambda x: x["mtime"], reverse=True)


def get_incremental_files() -> Tuple[List[Dict[str, object]], "kis_state.IncrementalScan"]:
    """Checkpoint 模式（默认）：自上次运行以来新增/内容变化的文件。

    返回 (文件条目列表, scan 对象)。调用方在成功产出后用 scan 提交 checkpoint。
    """
    scan = kis_state.scan_incremental(TASK_KEY, SCAN_PATHS, recursive=True)
    files = [_build_file_entry(p) for p in scan.files if p.exists()]
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return files, scan


def normalize(value: str) -> str:
    return value.lower().replace("｜", " ").replace("_", " ").replace("-", " ")


def extract_preview(content: str, max_chars: int = 220) -> str:
    text = clean_text(content)
    return text[:max_chars] + "..." if len(text) > max_chars else text


def extract_bullets(content: str, limit: int = 5) -> List[str]:
    body = strip_frontmatter(content)
    bullets = re.findall(r"^\s*(?:[-*•]|\d+[.)、])\s+(.+)$", body, flags=re.MULTILINE)
    cleaned = []
    for bullet in bullets:
        bullet = re.sub(r"\s+", " ", bullet).strip()
        if len(bullet) < 6 or bullet in cleaned:
            continue
        cleaned.append(bullet)
        if len(cleaned) >= limit:
            break
    return cleaned


def extract_keywords(files: Iterable[Dict[str, object]], limit: int = 12) -> List[Tuple[str, int]]:
    counter: Counter[str] = Counter()
    for item in files:
        text = normalize(f"{item['name']} {item.get('clean', '')}")
        tokens = re.findall(r"[\u4e00-\u9fa5]{2,6}|[A-Za-z][A-Za-z0-9+.#/-]{1,24}", text)
        for token in tokens:
            token = token.lower().strip("-_/#.。！？!?,，：:；;（）()[]【】《》<>\"'")
            if is_stopword(token) or token in EXTRA_NOISE:
                continue
            counter[token] += 1
    return counter.most_common(limit)


def match_themes(item: Dict[str, object]) -> List[str]:
    text = normalize(f"{item['name']} {item.get('clean', '')}")
    matched = []
    for theme, meta in THEME_RULES.items():
        keywords = [normalize(str(k)) for k in meta["keywords"]]  # type: ignore[index]
        if any(k in text for k in keywords):
            matched.append(theme)
    return matched


def classify_asset(item: Dict[str, object], themes: List[str]) -> str:
    text = normalize(f"{item['name']} {item.get('clean', '')}")
    if any(word in text for word in ["步骤", "流程", "prompt", "提示词", "工作流", "教程", "指南"]):
        return "Skill 候选 / 工作流"
    if "想法" == item["category"] and any(word in text for word in ["账号", "选题", "视频", "栏目", "创意"]):
        return "输出选题 / 内容企划"
    if themes:
        return str(THEME_RULES[themes[0]]["asset"])
    return "暂存观察"


def action_for_item(item: Dict[str, object], themes: List[str]) -> str:
    if themes:
        return str(THEME_RULES[themes[0]]["next"])
    if item["category"] == "想法":
        return "补充：为什么重要、目标受众、下一步动作。"
    return "先判断是否值得提炼：核心观点、可复用方法、是否关联当前项目。"


def generate_distill_report(files: List[Dict[str, object]], target_date: str | None = None) -> Path:
    target_date = target_date or datetime.now().strftime("%Y-%m-%d")
    thoughts = [f for f in files if f["category"] == "想法"]
    clippings = [f for f in files if f["category"] == "Clippings"]
    keywords = extract_keywords(files)

    theme_counter: Counter[str] = Counter()
    for item in files:
        theme_counter.update(match_themes(item))
    top_themes = theme_counter.most_common(5)

    report: List[str] = [
        f"# 📅 每日知识蒸馏 - {target_date}",
        "",
        "> 今日新增输入的价值判断、资产化方向和下一步动作。",
        "",
        "## 📊 今日概览",
        "",
        f"- 新增笔记总数：**{len(files)}** 篇",
        f"- 💡 想法灵感：**{len(thoughts)}** 篇",
        f"- 📑 外部剪藏：**{len(clippings)}** 篇",
        "",
    ]

    report.extend(["## 🧠 今日一句话判断", ""])
    if not files:
        report.append("今天没有新增输入。可以休息，也可以回看昨天的高价值想法。")
    elif top_themes:
        themes_text = " + ".join(theme for theme, _ in top_themes[:3])
        report.append(f"今天的新输入主要落在：**{themes_text}**。重点不是归档，而是把其中能推进的内容转成资产。")
    else:
        report.append("今天的新输入主题较分散，建议先补上下文，再决定是否进入蒸馏或输出。")
    report.append("")

    if top_themes:
        report.extend(["## 🔥 今日主题信号", ""])
        for theme, count in top_themes:
            report.append(f"- **{theme}**：命中 {count} 条；建议：{THEME_RULES[theme]['next']}")
        report.append("")

    if thoughts:
        report.extend(["## 💡 今日灵感想法", ""])
        for item in thoughts:
            themes = match_themes(item)
            report.append(f"### [[{item['name']}]]")
            report.append("")
            report.append(f"- 主题：{', '.join(themes) if themes else '未形成明确主题'}")
            report.append(f"- 资产化判断：{classify_asset(item, themes)}")
            report.append(f"- 下一步：{action_for_item(item, themes)}")
            bullets = extract_bullets(str(item["content"]))
            if bullets:
                report.append("- 原文要点：")
                for bullet in bullets[:3]:
                    report.append(f"  - {bullet}")
            else:
                report.append(f"- 预览：{extract_preview(str(item['content']))}")
            report.append("")

    if clippings:
        report.extend(["## 📑 今日外部剪藏", ""])
        for item in clippings[:20]:
            themes = match_themes(item)
            report.append(f"### [[{item['name']}]]")
            report.append("")
            report.append(f"- 主题：{', '.join(themes) if themes else '待判断'}")
            report.append(f"- 资产化判断：{classify_asset(item, themes)}")
            report.append(f"- 下一步：{action_for_item(item, themes)}")
            report.append(f"- 预览：{extract_preview(str(item['content']), 160)}")
            report.append("")

    report.extend(["## 🎯 明日/下一步建议", ""])
    if top_themes:
        for theme, _ in top_themes[:3]:
            report.append(f"- **{theme}**：{THEME_RULES[theme]['next']}")
    elif thoughts:
        report.append("- 给今天的想法补充“受众、用途、下一步动作”，避免灵感变成孤岛。")
    else:
        report.append("- 暂无强行动项。")
    report.append("")

    if keywords:
        report.extend(["## 🧹 关键词参考（已过滤噪音）", ""])
        report.append("、".join(f"{kw}({count})" for kw, count in keywords))
        report.append("")

    report.extend(["---", "", f"*生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"])

    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_PATH / f"{target_date}_知识蒸馏.md"
    output_file.write_text("\n".join(report), encoding="utf-8")
    return output_file


def classify_input_docs(files: List[Dict[str, object]], mode: str = "keyword") -> Dict[str, int]:
    """对本次增量文档做多标签分类，写入 catalog，疑难件进待审队列。

    非阻塞：不在这里问用户；落入 OTHER 或 LLM 提议新分类的，只写队列，人事后处理。
    返回统计：{'classified':N,'other':M,'proposed':K}。
    """
    classifier = build_classifier(mode)
    catalog = kis_catalog.load_catalog()
    pending = kis_catalog.load_pending()
    stats = {"classified": 0, "other": 0, "proposed": 0}

    for item in files:
        path = item["path"]
        name = str(item["name"])
        content = str(item.get("content", ""))
        content_hash = hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()
        result = classifier.classify(name, content)
        kis_catalog.upsert_doc(catalog, path, name, result.categories, result.source, content_hash)
        stats["classified"] += 1
        if result.fell_back_to_other:
            stats["other"] += 1
            kis_catalog.queue_pending(pending, path, name, "no_match", result.proposals)
        elif result.proposals:
            stats["proposed"] += 1
            kis_catalog.queue_pending(pending, path, name, "llm_proposal", result.proposals)

    kis_catalog.save_catalog(catalog)
    kis_catalog.save_pending(pending)
    doc = kis_catalog.render_catalog_doc(catalog)
    print(f"🗂 分类目录已更新：{doc}")
    print(f"   分类 {stats['classified']} 篇，其中落入「{OTHER}」 {stats['other']} 篇，待审队列新增 {stats['other'] + stats['proposed']} 条")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="每日知识蒸馏")
    parser.add_argument("days_pos", nargs="?", type=int, help="兼容旧用法：扫描天数（手动覆盖，不读写 checkpoint）")
    parser.add_argument("--days", type=int, help="手动覆盖：扫描最近 N 天（不读写 checkpoint）")
    parser.add_argument("--since", type=str, help="手动覆盖：扫描自指定日期起（YYYY-MM-DD，不读写 checkpoint）")
    parser.add_argument("--reset-checkpoint", action="store_true", help="清除本任务 checkpoint 后退出（下次将全量视为增量）。")
    parser.add_argument("--classify", choices=["keyword", "llm", "off"], default="keyword",
                        help="输入层分类后端：keyword（默认、离线）/ llm（opt-in、降级安全）/ off（不分类）。")
    args = parser.parse_args()

    print("=" * 50)
    print("🔬 知识蒸馏系统 - 每日蒸馏")
    print("=" * 50)

    if args.reset_checkpoint:
        removed = kis_state.reset_task(TASK_KEY)
        print(f"{'✅ 已清除' if removed else 'ℹ️ 无'} checkpoint（任务：{TASK_KEY}）")
        return

    # 三种模式：--days / --since 为手动覆盖（时间窗，不动 checkpoint）；
    # 否则默认走 checkpoint 增量（自上次运行以来）。
    manual_days = args.days if args.days is not None else args.days_pos
    scan = None
    if args.since:
        try:
            since_dt = datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            print(f"⚠️ --since 日期格式错误（需 YYYY-MM-DD）：{args.since}")
            return
        print(f"\n📂 [手动] 扫描 {args.since} 起新增内容（不更新 checkpoint）...")
        files = get_files_since(since_dt)
    elif manual_days is not None:
        print(f"\n📂 [手动] 扫描最近 {manual_days} 天新增内容（不更新 checkpoint）...")
        files = get_today_files(manual_days)
    else:
        files, scan = get_incremental_files()
        if scan.last_run_at:
            print(f"\n📂 [增量] 自上次运行（{scan.last_run_at}）以来新增/变化的内容...")
        else:
            print("\n📂 [增量] 首次运行，把当前输入层全部视为新增...")

    if not files:
        print("✅ 没有需要蒸馏的新增内容")
        # 即使无新增，也推进 checkpoint（确认本次扫描）。
        if scan is not None:
            kis_state.commit_scan(TASK_KEY, scan)
        return
    print(f"✅ 找到 {len(files)} 篇新笔记")
    print("\n📝 生成蒸馏报告...")
    output_file = generate_distill_report(files)
    print(f"✅ 报告已生成：{output_file}")

    # 输入层分类目录（非阻塞；默认关键词离线，llm 需 opt-in 且降级安全）。
    if args.classify != "off":
        try:
            classify_input_docs(files, mode=args.classify)
        except Exception as exc:
            # 分类失败不影响蒸馏主流程。
            print(f"⚠️ 分类环节跳过（不影响蒸馏）：{exc}")

    # 报告成功产出后才推进 checkpoint，避免失败丢增量。
    if scan is not None:
        kis_state.commit_scan(TASK_KEY, scan)


if __name__ == "__main__":
    main()
