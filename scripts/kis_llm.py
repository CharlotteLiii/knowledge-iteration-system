#!/usr/bin/env python3
"""LLM 兜底调用助手（Knowledge Iteration System 专用）。

设计原则（对齐 v2 优化方案）：
- **默认关闭**：只有配置齐全（api key + base_url + model）才启用。
- **单次批量调用**：Section 1 一次、Section 2 一次，不做逐字段调用。
- **强制 JSON 输出**：prompt 明确要求返回 JSON，解析失败即降级。
- **降级安全**：任何异常（缺 key / 超时 / HTTP 4xx-5xx / JSON 解析失败）
  → 抛 `LLMUnavailable`，上层写"LLM 不可用"，绝不阻塞脚本。
- **内容级缓存**：结果按 (clipping md5, model, prompt version) 缓存到
  `.kis-cache/skill_eval/*.json`，重复跑不重复调。

依赖：仅使用 Python 标准库（urllib + json）。零第三方包。

配置来源（按优先级）：
  1. 环境变量：`KIS_LLM_API_KEY` / `KIS_LLM_BASE_URL` / `KIS_LLM_MODEL`
  2. 环境变量：`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`
  3. `.knowledge-iteration-system.json` 里的 `llm` 键：
       {
         "llm": {
           "enabled": true,
           "base_url": "https://api.openai.com/v1",
           "model": "gpt-4o-mini",
           "api_key_env": "OPENAI_API_KEY",
           "timeout_seconds": 20,
           "temperature": 0
         }
       }
  4. 项目根 `.env`（KEY=VALUE 一行一条）会被自动加载到 os.environ。

Prompt 版本随代码演进：修改 `PROMPT_VERSION` 会自动使旧缓存失效。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from kis_config import CONFIG, VAULT

PROMPT_VERSION = "2"
BATCH_PROMPT_VERSION = "2"  # 独立于单候选版本，避免旧缓存失效。
CACHE_DIR_NAME = ".kis-cache/skill_eval"
DEFAULT_TIMEOUT = 90
DEFAULT_TEMPERATURE = 0
MAX_INPUT_CHARS = 8000  # keep prompts cheap; clippings are usually shorter
MAX_BATCH_ITEMS = 8     # single API call 上限；超过则分批（从 20 降到 8，避免单次 timeout）
MAX_BATCH_TOTAL_CHARS = 12000  # 单 batch prompt 总长，预防模型截断


class LLMUnavailable(RuntimeError):
    """LLM 不可用（未配置 / 网络 / 解析失败）。上层应写「⚠️ AI 分析结果：LLM 不可用」。"""


def _build_ssl_context() -> ssl.SSLContext:
    """优先用 certifi 的 CA bundle，否则用系统默认。解决 macOS Python.org 官方版没装证书的经典坑。"""
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


# ── .env autoload ──────────────────────────────────────────────────

def _load_dotenv() -> None:
    """Best-effort .env autoload.

    Search order: vault root, script dir, ~/.openclaw/workspace. Silent no-op
    if the file is missing or malformed.
    """
    candidates = [
        VAULT / ".env",
        Path(__file__).resolve().parent / ".env",
        Path.home() / ".openclaw" / "workspace" / ".env",
    ]
    for p in candidates:
        try:
            if not p.is_file():
                continue
            for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        except Exception:
            continue


_load_dotenv()


# ── Config resolution ──────────────────────────────────────────────

@dataclass
class LLMConfig:
    enabled: bool = False
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    timeout: int = DEFAULT_TIMEOUT
    temperature: float = DEFAULT_TEMPERATURE

    def usable(self) -> bool:
        return bool(self.enabled and self.api_key and self.base_url and self.model)


def _first_env(*names: str) -> Optional[str]:
    for n in names:
        val = os.environ.get(n)
        if val:
            return val.strip()
    return None


def resolve_llm_config() -> LLMConfig:
    """Merge config-file settings with env vars. Env wins if present."""
    file_cfg = (CONFIG.get("llm") or {}) if isinstance(CONFIG.get("llm"), dict) else {}

    # api_key: env preferred; also honor file-provided api_key_env indirection.
    api_key = _first_env("KIS_LLM_API_KEY", "OPENAI_API_KEY")
    if not api_key:
        env_name = file_cfg.get("api_key_env")
        if env_name:
            api_key = _first_env(env_name)

    base_url = _first_env("KIS_LLM_BASE_URL", "OPENAI_BASE_URL") or file_cfg.get("base_url")
    model = _first_env("KIS_LLM_MODEL", "OPENAI_MODEL") or file_cfg.get("model")

    timeout_raw = file_cfg.get("timeout_seconds", DEFAULT_TIMEOUT)
    try:
        timeout = int(timeout_raw)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT

    temperature_raw = file_cfg.get("temperature", DEFAULT_TEMPERATURE)
    try:
        temperature = float(temperature_raw)
    except (TypeError, ValueError):
        temperature = DEFAULT_TEMPERATURE

    enabled_hint = file_cfg.get("enabled")
    if enabled_hint is None:
        enabled = bool(api_key and base_url and model)
    else:
        enabled = bool(enabled_hint)

    return LLMConfig(
        enabled=enabled,
        api_key=api_key,
        base_url=(base_url or "").rstrip("/") or None,
        model=model,
        timeout=timeout,
        temperature=temperature,
    )


# ── Cache ──────────────────────────────────────────────────────────

def _cache_dir() -> Path:
    return VAULT / CACHE_DIR_NAME


def _cache_key(content: str, purpose: str, cfg: LLMConfig) -> str:
    h = hashlib.md5()
    h.update(purpose.encode("utf-8"))
    h.update(b"|v")
    h.update(PROMPT_VERSION.encode("utf-8"))
    h.update(b"|m")
    h.update((cfg.model or "").encode("utf-8"))
    h.update(b"|c")
    h.update(content.encode("utf-8"))
    return h.hexdigest()


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    path = _cache_dir() / f"{key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_put(key: str, value: Dict[str, Any]) -> None:
    d = _cache_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass  # cache write is best-effort


# ── HTTP call (OpenAI-compatible chat/completions) ─────────────────

def _post_chat(cfg: LLMConfig, messages: List[Dict[str, str]]) -> str:
    if not cfg.usable():
        raise LLMUnavailable("LLM 未启用或配置不完整")

    url = f"{cfg.base_url}/chat/completions"
    payload: Dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
    }
    # 部分 OpenAI 兼容供应商拒绝 response_format=json_object（如火山方舟 Ark plan endpoint 的 ark-code-latest）。
    # 环境变量 KIS_LLM_DISABLE_JSON_MODE=1 时关闭；prompt 已明确要求 JSON，_extract_json 也能兼容纯文本。
    if os.environ.get("KIS_LLM_DISABLE_JSON_MODE", "").strip().lower() not in ("1", "true", "yes"):
        payload["response_format"] = {"type": "json_object"}
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
    )
    ctx = _build_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise LLMUnavailable(f"HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMUnavailable(f"网络错误: {e}") from e

    try:
        obj = json.loads(raw)
        content = obj["choices"][0]["message"]["content"]
    except Exception as e:
        raise LLMUnavailable(f"响应解析失败: {e}; raw[:200]={raw[:200]!r}") from e

    if not isinstance(content, str) or not content.strip():
        raise LLMUnavailable("响应为空")
    return content


def _post_chat_with_retry(cfg: LLMConfig, messages: List[Dict[str, str]],
                          max_retries: int = 3) -> str:
    """包装 _post_chat，消化 429 频率限制：遇到 429 指数退避后重试。"""
    delay = 3.0
    last_exc: Optional[LLMUnavailable] = None
    for attempt in range(max_retries + 1):
        try:
            return _post_chat(cfg, messages)
        except LLMUnavailable as exc:
            msg = str(exc)
            last_exc = exc
            # 只对频率限制重试，其他错误直接抛
            if "429" not in msg and "频率" not in msg and "rate" not in msg.lower():
                raise
            if attempt == max_retries:
                break
            print(f"   ⏳ 429 频率限制，{delay:.0f}s 后重试（{attempt + 1}/{max_retries}）…")
            time.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc


def _extract_json(text: str) -> Dict[str, Any]:
    """Best-effort JSON extraction. Some providers ignore response_format."""
    text = text.strip()
    # Fast path
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Strip code fences
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence:
        try:
            obj = json.loads(fence.group(1))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    # Greedy braces
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    raise LLMUnavailable("模型没有返回可解析的 JSON")


# ── Public API ─────────────────────────────────────────────────────

SECTION1_SYSTEM = (
    "你是一个严格的知识资产诊断助手。你的任务是判断一段被剪藏的原文是否值得沉淀为可复用的 Skill。"
    "只依据原文事实做判断，不要脑补也不要发挥。"
    "证据不足的维度必须标 ⚠️，不能强行判 ✅ 或 ❌。"
    "所有回答必须是合法 JSON，不要加解释性文字。"
)

SECTION1_USER_TEMPLATE = """请对下面这篇剪藏内容做「Skill 可行性诊断」。5 个维度，每个只能是 "✅"/"⚠️"/"❌" 之一，并给一句 20 字以内的中文理由。

维度定义：
- reusable：内容是否可复用（面向多人 / 通用方法 → ✅；仅个人经验/情绪 → ❌）
- input_stable：输入是否稳定（有明确材料/参数 → ✅；主观模糊 → ⚠️）
- steps_clear：步骤是否清晰（有 ≥3 个明确步骤 → ✅；只有观点 → ❌）
- output_verifiable：输出是否可验证（能被检查/复现 → ✅；只有感受 → ❌）
- has_case：是否有真实案例（含具体数字/结果/名字 → ✅；纯理论 → ❌）

严格返回 JSON，形如：
{{"reusable":{{"verdict":"✅","reason":"…"}},"input_stable":{{"verdict":"⚠️","reason":"…"}},"steps_clear":{{"verdict":"❌","reason":"…"}},"output_verifiable":{{"verdict":"⚠️","reason":"…"}},"has_case":{{"verdict":"✅","reason":"…"}}}}

原文（可能被截断）：
<<<
{content}
>>>
"""

SECTION2_SYSTEM = (
    "你是一个从剪藏原文中抽取「Skill 使用情境」的助手。"
    "只抽原文明确表达或强烈暗示的内容，抽不到就返回 null。绝不脑补。"
    "所有回答必须是合法 JSON。"
)

SECTION2_USER_TEMPLATE = """从下面这段剪藏原文中抽取 5 个字段。原文里没有明显信息的字段一律返回 null，不要猜测。

严格返回 JSON，形如：
{{"target_user":"…或null","trigger_scenario":"…或null","pain_point":"…或null","expected_outcome":"…或null","unfit_scenario":"…或null"}}

字段说明：
- target_user：这个方法/内容适合谁用（1 句话，20 字以内）
- trigger_scenario：什么时候想用它（1 句话）
- pain_point：作者提到的用户痛点（1 句话）
- expected_outcome：用后能得到什么可验证的结果（1 句话，尽量含数字/产出）
- unfit_scenario：什么情况下不适合用（1 句话）

原文（可能被截断）：
<<<
{content}
>>>
"""


SECTION3_SYSTEM = (
    "你是一个根据剪藏原文推断「Skill 形态」的助手。"
    "你只根据原文描述的具体环境推导合理的专业推测，抽不到返回 null，允许少量合理推断。"
    "推断必须强耶扮原文相关。所有回答必须是合法 JSON。"
)

SECTION3_USER_TEMPLATE = """阅读下面这段剪藏原文，全面推断 Skill 形态相关信息。请不要留空，基于原文上下文 + 常识做合理推断。

严格返回 JSON，形如：
{{"skill_type":"…","inputs":"…","outputs":"…","step_count":整数或0,"tools_required":"…","not_required":"…"}}

字段说明：
- skill_type：形态分类，从以下选一：工具调用型 / 工作流型 / 判断诊断型 / 内容生成型 / 知识梳理型
- inputs：用这个 Skill 需要什么输入（材料 / 参数 / 初始条件），20-40 字
- outputs：产出形式（文章 / 代码 / 图片 / 列表 / 分析报告 …），20-40 字
- step_count：预计关键动作数（整数），真不确定写 0
- tools_required：必须用到的具体工具/平台/API/账号
- not_required：这个 Skill **不依赖**什么（避免误解的反面清单）

原文（可能被截断）：
<<<
{content}
>>>
"""


def _prep_content(raw: str) -> str:
    text = raw or ""
    if len(text) > MAX_INPUT_CHARS:
        head = text[: MAX_INPUT_CHARS - 200]
        tail = text[-180:]
        text = head + "\n…（省略）…\n" + tail
    return text


def call_section1(content: str, cfg: Optional[LLMConfig] = None) -> Dict[str, Dict[str, str]]:
    """5 维度诊断。返回 {dim: {verdict, reason}}. 失败抛 LLMUnavailable。"""
    cfg = cfg or resolve_llm_config()
    prepped = _prep_content(content)
    key = _cache_key(prepped, "section1", cfg)
    cached = _cache_get(key)
    if cached:
        return cached
    txt = _post_chat(
        cfg,
        [
            {"role": "system", "content": SECTION1_SYSTEM},
            {"role": "user", "content": SECTION1_USER_TEMPLATE.format(content=prepped)},
        ],
    )
    obj = _extract_json(txt)
    _cache_put(key, obj)
    return obj


def call_section2(content: str, cfg: Optional[LLMConfig] = None) -> Dict[str, Optional[str]]:
    """使用情境抽取。返回 5 字段，抽不到给 None。失败抛 LLMUnavailable。"""
    cfg = cfg or resolve_llm_config()
    prepped = _prep_content(content)
    key = _cache_key(prepped, "section2", cfg)
    cached = _cache_get(key)
    if cached:
        return cached
    txt = _post_chat(
        cfg,
        [
            {"role": "system", "content": SECTION2_SYSTEM},
            {"role": "user", "content": SECTION2_USER_TEMPLATE.format(content=prepped)},
        ],
    )
    obj = _extract_json(txt)
    _cache_put(key, obj)
    return obj


def call_section3(content: str, cfg: Optional[LLMConfig] = None) -> Dict[str, Optional[str]]:
    """Section 3 Skill 形态推断。返回 4 字段（inputs/outputs/tools_required/not_required），抽不到给 None。失败抛 LLMUnavailable。"""
    cfg = cfg or resolve_llm_config()
    prepped = _prep_content(content)
    key = _cache_key(prepped, "section3", cfg)
    cached = _cache_get(key)
    if cached:
        return cached
    txt = _post_chat(
        cfg,
        [
            {"role": "system", "content": SECTION3_SYSTEM},
            {"role": "user", "content": SECTION3_USER_TEMPLATE.format(content=prepped)},
        ],
    )
    obj = _extract_json(txt)
    _cache_put(key, obj)
    return obj


# ── Batch API ──────────────────────────────────────────
#
# 多候选一次调用。不同于单候选 API：
#  - 逐项读缓存，只把未命中候选拼成一次 API 调用
#  - 自动分批（按数量 + 总字符双阈值）
#  - 返回以 name 为键，未命中项 fallback 为 None

def _batch_cache_key(content: str, purpose: str, cfg: LLMConfig) -> str:
    h = hashlib.md5()
    h.update(purpose.encode("utf-8"))
    h.update(b"|bv")
    h.update(BATCH_PROMPT_VERSION.encode("utf-8"))
    h.update(b"|m")
    h.update((cfg.model or "").encode("utf-8"))
    h.update(b"|c")
    h.update(content.encode("utf-8"))
    return h.hexdigest()


SECTION1_BATCH_SYSTEM = SECTION1_SYSTEM + "\n你一次处理多个候选；返回形式为以 name 为键的 dict，不要额外包裹。"
SECTION2_BATCH_SYSTEM = SECTION2_SYSTEM + "\n你一次处理多个候选；返回形式为以 name 为键的 dict，不要额外包裹。"
SECTION3_BATCH_SYSTEM = SECTION3_SYSTEM + "\n你一次处理多个候选；返回形式为以 name 为键的 dict，不要额外包裹。"

SECTION1_BATCH_USER = """对以下 {count} 个候选逐一做 Skill 可行性五维度诊断。每个维度只能为 "✅"/"⚠️"/"❌" 之一，附一句 20 字以内中文理由。

维度定义同单候选 API：reusable / input_stable / steps_clear / output_verifiable / has_case。

返回严格的 JSON，形如：
{{"<name1>":{{"reusable":{{"verdict":"✅","reason":"..."}},...}}, "<name2>":{{...}}}}

候选列表（每个候选以 name + content 块提供）：
{blocks}
"""

SECTION2_BATCH_USER = """从以下 {count} 个候选中抽取 Skill 使用情境。抽不到一律返回 null，不得脑补。

字段同单候选 API：target_user / trigger_scenario / pain_point / expected_outcome / unfit_scenario，每字段 1 句内 20 字以下。

返回严格的 JSON，形如：
{{"<name1>":{{"target_user":"...或null",...}}, "<name2>":{{...}}}}

候选列表（每个候选以 name + content 块提供）：
{blocks}
"""

SECTION3_BATCH_USER = """从以下 {count} 个候选中全面推断 Skill 形态。请不要留空，基于原文上下文做合理推断。

字段同单候选 API：skill_type / inputs / outputs / step_count(int) / tools_required / not_required。

skill_type 只能为下列之一：工具调用型 / 工作流型 / 判断诊断型 / 内容生成型 / 知识梳理型。
step_count 为整数（真不确定写 0）。其余字段 20-40 字。

返回严格的 JSON，形如：
{{"<name1>":{{"skill_type":"...","inputs":"...","outputs":"...","step_count":0,"tools_required":"...","not_required":"..."}}, "<name2>":{{...}}}}

候选列表（每个候选以 name + content 块提供）：
{blocks}
"""


def _format_batch_blocks(items: List[Dict[str, str]]) -> str:
    blocks = []
    for item in items:
        name = str(item.get("name", "")).strip() or "(无名)"
        content = _prep_content(str(item.get("content", "")))
        blocks.append(f"### name: {name}\n<<<\n{content}\n>>>")
    return "\n\n".join(blocks)


def _split_batches(items: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    """根据 MAX_BATCH_ITEMS + 总字符阈值将 items 切成若干批次。"""
    batches: List[List[Dict[str, str]]] = []
    current: List[Dict[str, str]] = []
    current_chars = 0
    for item in items:
        content = _prep_content(str(item.get("content", "")))
        item_chars = len(content) + 64  # 包括 name / 分隔符开销
        if current and (len(current) >= MAX_BATCH_ITEMS or current_chars + item_chars > MAX_BATCH_TOTAL_CHARS):
            batches.append(current)
            current = []
            current_chars = 0
        current.append({"name": item.get("name", ""), "content": content})
        current_chars += item_chars
    if current:
        batches.append(current)
    return batches


def _call_batch(purpose: str, items: List[Dict[str, str]], cfg: Optional[LLMConfig] = None) -> Dict[str, Any]:
    """通用批处理入口。purpose='section1'|'section2'|'section3'。

    行为：
      1. 逐项查缓存（按 purpose+content 命中无关批次），命中直接返回。
      2. 未命中项按 MAX_BATCH_ITEMS / MAX_BATCH_TOTAL_CHARS 分批。
      3. 每批一次 HTTP 调用，返回后写回单项缓存 + batch 缓存。
      4. 任何单个批次失败（LLMUnavailable）一律向上抛，不部分返回。

    返回：{name: <同单候选结果结构>}. 若 name 在模型输出里缺失，则不入 dict。
    """
    if purpose not in ("section1", "section2", "section3"):
        raise ValueError(f"unknown purpose: {purpose}")
    if not items:
        return {}
    cfg = cfg or resolve_llm_config()

    out: Dict[str, Any] = {}
    misses: List[Dict[str, str]] = []

    for item in items:
        name = str(item.get("name", "")).strip()
        content = _prep_content(str(item.get("content", "")))
        if not name or not content:
            continue
        key = _cache_key(content, purpose, cfg)
        cached = _cache_get(key)
        if cached:
            out[name] = cached
            continue
        misses.append({"name": name, "content": content, "_key": key})

    if not misses:
        return out

    system_prompt = {
        "section1": SECTION1_BATCH_SYSTEM,
        "section2": SECTION2_BATCH_SYSTEM,
        "section3": SECTION3_BATCH_SYSTEM,
    }[purpose]
    user_template = {
        "section1": SECTION1_BATCH_USER,
        "section2": SECTION2_BATCH_USER,
        "section3": SECTION3_BATCH_USER,
    }[purpose]

    for batch in _split_batches([{"name": m["name"], "content": m["content"]} for m in misses]):
        blocks = _format_batch_blocks(batch)
        user_prompt = user_template.format(count=len(batch), blocks=blocks)
        # 小休息避免触发 429（部分供应商频率限制严）
        time.sleep(1.5)
        txt = _post_chat_with_retry(
            cfg,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        obj = _extract_json(txt)
        if not isinstance(obj, dict):
            raise LLMUnavailable("批量响应不是以 name 为键的 JSON")
        for m in misses:
            if m["name"] not in batch and m["name"] not in [b["name"] for b in batch]:
                continue
            # 仅写回本批包含的 name
        batch_names = {b["name"] for b in batch}
        for name in batch_names:
            payload = obj.get(name)
            if not isinstance(payload, dict):
                continue
            out[name] = payload
            # 以单候选 cache key 写回，后续单候选 / 批量 API 均可命中
            miss_key = next((m["_key"] for m in misses if m["name"] == name), None)
            if miss_key:
                _cache_put(miss_key, payload)

    return out


def call_section1_batch(items: List[Dict[str, str]], cfg: Optional[LLMConfig] = None) -> Dict[str, Dict[str, Dict[str, str]]]:
    """批量五维度诊断。items = [{name, content}]。

    返回：{name: {dim: {verdict, reason}}}. name 在模型输出里缺失则不入 dict。
    """
    return _call_batch("section1", items, cfg)


def call_section2_batch(items: List[Dict[str, str]], cfg: Optional[LLMConfig] = None) -> Dict[str, Dict[str, Optional[str]]]:
    """批量使用情境抽取。items = [{name, content}]。

    返回：{name: {field: value_or_null}}. name 在模型输出里缺失则不入 dict。
    """
    return _call_batch("section2", items, cfg)


def call_section3_batch(items: List[Dict[str, str]], cfg: Optional[LLMConfig] = None) -> Dict[str, Dict[str, Optional[str]]]:
    """批量 Section 3 Skill 形态推断。items = [{name, content}]。

    返回：{name: {inputs/outputs/tools_required/not_required: value_or_null}}。
    """
    return _call_batch("section3", items, cfg)


# ── Free-form summarization batch (供 feedback_loop 等使用) ────────────────

def call_json(system_prompt: str, user_prompt: str, cache_purpose: Optional[str] = None,
              cfg: Optional[LLMConfig] = None) -> Dict[str, Any]:
    """通用入口：给定 system + user、返回 JSON dict。失败抛 LLMUnavailable。

    适合 feedback_loop 等需要自定义提示词、一次总结多条内容的场景。
    自动以 (system+user, cache_purpose) 为键写入单项缓存（每次调用不会重复发送）。
    """
    cfg = cfg or resolve_llm_config()
    purpose = cache_purpose or "call_json"
    key_content = system_prompt + "\n===\n" + user_prompt
    key = _cache_key(key_content, purpose, cfg)
    cached = _cache_get(key)
    if cached:
        return cached
    txt = _post_chat(
        cfg,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    obj = _extract_json(txt)
    _cache_put(key, obj)
    return obj


# ── Convenience for scripts ────────────────────────────────────────

def probe() -> Tuple[bool, str]:
    """返回 (是否配置齐全, 描述)。给脚本启动时的自检用。"""
    cfg = resolve_llm_config()
    if not cfg.enabled:
        return False, "LLM 未启用（默认关闭）"
    missing = [k for k, v in {"api_key": cfg.api_key, "base_url": cfg.base_url, "model": cfg.model}.items() if not v]
    if missing:
        return False, f"缺少配置: {', '.join(missing)}"
    return True, f"model={cfg.model}, base_url={cfg.base_url}"


if __name__ == "__main__":
    ok, msg = probe()
    print(f"[kis_llm] {'READY' if ok else 'DEGRADED'}: {msg}")
