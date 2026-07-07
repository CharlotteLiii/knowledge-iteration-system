#!/usr/bin/env python3
"""运行状态 / 增量 checkpoint（Knowledge Iteration System 专用）。

解决三个真实问题：
1. **网盘同步刷新 mtime** → 单看 mtime 会把没改内容的旧文件误判为新增。
   对策：mtime 只做快筛，最终以 **内容 hash** 判定是否真的变化。
2. **漏跑不补扫** → 记录"上次处理到哪"，隔几天没跑，下次自动覆盖这几天的全部增量。
3. **连跑重叠** → 处理完推进 checkpoint，第二次跑没有新文件就是空。

设计原则（对齐本项目其它模块）：
- 纯标准库，无第三方依赖。
- 状态文件 `<vault>/.kis_state.json`，每个任务独立 key（daily / weekly 互不干扰）。
- 任何异常都降级为"当作全部是增量"，绝不阻塞脚本。
- 手动 `--days/--since` 覆盖走时间窗，不读也不写 checkpoint。

状态结构：
{
  "version": 1,
  "tasks": {
    "daily_distill": {
      "last_run_at": "2026-07-07T21:00:00",
      "files": { "<abs_path>": { "mtime": 1720358400.0, "hash": "<md5>" } }
    }
  }
}
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from kis_config import VAULT, iter_markdown_files

STATE_NAME = ".kis_state.json"
STATE_PATH = VAULT / STATE_NAME
STATE_VERSION = 1


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _file_hash(path: Path, max_bytes: int = 1_000_000) -> str:
    """内容 MD5（截断到前 max_bytes，兼顾大文件性能与判重可靠性）。"""
    h = hashlib.md5()
    try:
        with path.open("rb") as fh:
            h.update(fh.read(max_bytes))
    except Exception:
        # 读失败时用路径+mtime 兜底，保证有稳定 key，不抛异常。
        try:
            h.update(f"{path}|{path.stat().st_mtime}".encode("utf-8"))
        except Exception:
            h.update(str(path).encode("utf-8"))
    return h.hexdigest()


def load_state() -> Dict:
    if not STATE_PATH.exists():
        return {"version": STATE_VERSION, "tasks": {}}
    try:
        obj = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return {"version": STATE_VERSION, "tasks": {}}
        obj.setdefault("version", STATE_VERSION)
        obj.setdefault("tasks", {})
        if not isinstance(obj["tasks"], dict):
            obj["tasks"] = {}
        return obj
    except Exception:
        # 状态文件损坏 → 视为无状态（全部当增量），不阻塞。
        return {"version": STATE_VERSION, "tasks": {}}


def save_state(state: Dict) -> None:
    try:
        STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        pass  # 状态写入是 best-effort，失败不影响主流程。


def task_last_run(task_key: str) -> Optional[str]:
    task = load_state().get("tasks", {}).get(task_key)
    if isinstance(task, dict):
        return task.get("last_run_at")
    return None


@dataclass
class IncrementalScan:
    files: List[Path]                 # 判定为"新增/变化"的文件
    total_scanned: int                # 本次扫描到的 md 文件总数
    last_run_at: Optional[str]        # 上次运行时间（None=首次）
    # 内部：本次扫描到的全部文件指纹，供 commit 时写回。
    _fingerprints: Dict[str, Dict]


def scan_incremental(task_key: str, roots: Iterable[Path], recursive: bool = True) -> IncrementalScan:
    """基于 checkpoint 的增量扫描。

    判定逻辑（逐文件）：
      - 不在已处理记录 → 增量（新文件）
      - mtime 未变（<= 记录 mtime）→ 跳过，不必 hash（快筛）
      - mtime 变了 → 算 hash：hash 与记录相同 → 内容没变（网盘刷 mtime），
        跳过但更新记录 mtime；hash 不同 → 增量（内容真的改了）

    返回 IncrementalScan；处理完后调用 commit_scan() 推进 checkpoint。
    """
    state = load_state()
    task = state.get("tasks", {}).get(task_key, {})
    known: Dict[str, Dict] = task.get("files", {}) if isinstance(task, dict) else {}
    last_run_at = task.get("last_run_at") if isinstance(task, dict) else None

    incremental: List[Path] = []
    fingerprints: Dict[str, Dict] = {}
    total = 0

    for root in roots:
        for path in iter_markdown_files(root, recursive=recursive):
            total += 1
            key = str(path.resolve())
            try:
                mtime = path.stat().st_mtime
            except Exception:
                mtime = 0.0
            prev = known.get(key)

            if prev is None:
                # 新文件
                fingerprints[key] = {"mtime": mtime, "hash": _file_hash(path)}
                incremental.append(path)
                continue

            prev_mtime = prev.get("mtime", 0.0)
            if mtime <= prev_mtime:
                # 快筛：mtime 没往后走 → 内容不可能变，沿用旧指纹
                fingerprints[key] = prev
                continue

            # mtime 变了 → 用 hash 定夺（对抗网盘刷 mtime）
            new_hash = _file_hash(path)
            if new_hash == prev.get("hash"):
                # 内容没变，只是 mtime 漂移 → 不算增量，但更新 mtime
                fingerprints[key] = {"mtime": mtime, "hash": new_hash}
            else:
                fingerprints[key] = {"mtime": mtime, "hash": new_hash}
                incremental.append(path)

    return IncrementalScan(
        files=sorted(incremental, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True),
        total_scanned=total,
        last_run_at=last_run_at,
        _fingerprints=fingerprints,
    )


def commit_scan(task_key: str, scan: IncrementalScan) -> None:
    """把本次扫描的指纹与运行时间写回 checkpoint。

    注意：写回的是"本次扫描看到的全部文件指纹"（scan._fingerprints），
    而不是只有增量文件——这样下次快筛才准确。已消失的文件自然从记录中移除。
    """
    state = load_state()
    tasks = state.setdefault("tasks", {})
    tasks[task_key] = {
        "last_run_at": _now_iso(),
        "files": scan._fingerprints,
    }
    save_state(state)


def reset_task(task_key: str) -> bool:
    """清除某任务的 checkpoint（下次运行将把所有文件当增量）。"""
    state = load_state()
    tasks = state.get("tasks", {})
    if task_key in tasks:
        del tasks[task_key]
        save_state(state)
        return True
    return False
