#!/usr/bin/env python3
"""Taxonomy onboarding 助手（Knowledge Iteration System 专用）。

目标：引导用户声明自己的知识库分类（写入 <vault>/taxonomy.json）。若用户不声明，
系统继续用 taxonomy.default.json 的通用默认分类。

**非阻塞设计**：脚本本身不 input() 问用户。真正的引导问答由上层 agent 完成，
agent 把用户声明的分类整理好后，用 --write 把结构化 JSON 落盘。脚本只负责：
- status：报告是否已有 taxonomy.json、当前生效的分类清单、是否首次使用。
- template：打印一份可填写的 taxonomy.json 模板（含默认分类做参考）。
- write：从 --file / stdin 读取用户分类 JSON，校验后合并写入 taxonomy.json。
- validate：校验一个候选 taxonomy.json 是否合法。

用法：
    python scripts/kis_onboard.py --status
    python scripts/kis_onboard.py --template
    python scripts/kis_onboard.py --write --file my_cats.json
    echo '{"contentTypes":{...}}' | python scripts/kis_onboard.py --write
    python scripts/kis_onboard.py --validate --file candidate.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from kis_config import (
    TAXONOMY_DEFAULT_PATH,
    TAXONOMY_USER_PATH,
    _merge_dict,
    content_types,
)


def _ask_on_first_use() -> bool:
    """首次使用（无 taxonomy.json）时是否应提示 onboarding。"""
    return not TAXONOMY_USER_PATH.exists()


def cmd_status() -> None:
    exists = TAXONOMY_USER_PATH.exists()
    print("=" * 44)
    print("🧭 Taxonomy Onboarding 状态")
    print("=" * 44)
    print(f"- 用户分类文件：{TAXONOMY_USER_PATH}")
    print(f"- 是否已声明自定义分类：{'是' if exists else '否（使用通用默认分类）'}")
    cats = list(content_types().keys())
    print(f"- 当前生效分类（{len(cats)}）：{'、'.join(cats)}")
    if not exists:
        print("\n💡 首次使用：可运行 `--template` 拿到模板，声明你自己的领域分类；")
        print("   不声明也能用，系统会套用上面的通用默认分类。")


def _template() -> Dict[str, Any]:
    """基于当前默认分类生成一份可填写模板。"""
    example = {
        "contentTypes": {
            "我的分类A（改成你的领域）": {
                "keywords": ["关键词1", "关键词2", "关键词3"],
                "asset": "这类内容适合沉淀成什么（如：方法论/清单/案例）",
                "priority": 2.0,
            },
            "我的分类B": {
                "keywords": ["关键词1", "关键词2"],
                "asset": "……",
                "priority": 1.5,
            },
        }
    }
    return example


def cmd_template() -> None:
    tmpl = _template()
    current = list(content_types().keys())
    print("// 把下面内容保存为 <vault>/taxonomy.json 并按你的领域修改。")
    print("// 只写想改/新增的分类即可，未写的分类会保留系统默认。")
    print(f"// 当前默认分类供参考：{'、'.join(current)}")
    print(json.dumps(tmpl, ensure_ascii=False, indent=2))


def _validate_taxonomy(obj: Any) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if not isinstance(obj, dict):
        return False, ["顶层必须是 JSON object"]
    ct = obj.get("contentTypes")
    if ct is not None:
        if not isinstance(ct, dict):
            errors.append("contentTypes 必须是 object")
        else:
            for name, meta in ct.items():
                if not isinstance(meta, dict):
                    errors.append(f"contentTypes.{name} 必须是 object")
                    continue
                kws = meta.get("keywords")
                if not isinstance(kws, list) or not all(isinstance(k, str) for k in kws):
                    errors.append(f"contentTypes.{name}.keywords 必须是字符串数组")
                if "priority" in meta and not isinstance(meta["priority"], (int, float)):
                    errors.append(f"contentTypes.{name}.priority 必须是数字")
    for list_key in ("themes", "tagRules", "bridges"):
        val = obj.get(list_key)
        if val is not None and not isinstance(val, dict):
            errors.append(f"{list_key} 必须是 object")
    return (len(errors) == 0), errors


def _read_input(file: str | None) -> Any:
    raw = Path(file).read_text(encoding="utf-8") if file else sys.stdin.read()
    return json.loads(raw)


def cmd_validate(file: str | None) -> int:
    try:
        obj = _read_input(file)
    except Exception as exc:
        print(f"❌ 读取/解析失败：{exc}")
        return 1
    ok, errors = _validate_taxonomy(obj)
    if ok:
        print("✅ taxonomy 校验通过")
        return 0
    print("❌ taxonomy 校验失败：")
    for e in errors:
        print(f"   - {e}")
    return 1


def cmd_write(file: str | None, merge: bool = True) -> int:
    try:
        incoming = _read_input(file)
    except Exception as exc:
        print(f"❌ 读取/解析失败：{exc}")
        return 1
    ok, errors = _validate_taxonomy(incoming)
    if not ok:
        print("❌ 拒绝写入，taxonomy 校验失败：")
        for e in errors:
            print(f"   - {e}")
        return 1

    if merge and TAXONOMY_USER_PATH.exists():
        try:
            existing = json.loads(TAXONOMY_USER_PATH.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                incoming = _merge_dict(existing, incoming)
        except Exception:
            pass  # 旧文件损坏则直接以新内容为准

    TAXONOMY_USER_PATH.write_text(
        json.dumps(incoming, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"✅ 已写入用户分类：{TAXONOMY_USER_PATH}")
    print("   下次运行分类/链接/蒸馏时生效（与默认分类深合并）。")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Taxonomy onboarding 助手（非阻塞）")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="报告当前分类声明状态")
    g.add_argument("--template", action="store_true", help="打印可填写的 taxonomy.json 模板")
    g.add_argument("--write", action="store_true", help="从 --file / stdin 写入 taxonomy.json")
    g.add_argument("--validate", action="store_true", help="校验候选 taxonomy JSON")
    parser.add_argument("--file", type=str, help="输入 JSON 文件路径（write/validate 用）")
    parser.add_argument("--no-merge", action="store_true", help="write 时不与现有文件合并，直接覆盖")
    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.template:
        cmd_template()
    elif args.validate:
        sys.exit(cmd_validate(args.file))
    elif args.write:
        sys.exit(cmd_write(args.file, merge=not args.no_merge))


if __name__ == "__main__":
    main()
