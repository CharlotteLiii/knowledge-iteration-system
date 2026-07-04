---
name: knowledge-iteration-system
description: "四层知识蒸馏系统：捕获 Inbox、蒸馏知识、识别 Skill 候选、输出回流与知识库体检。用于想法记录、每日/每周复盘、Clipping 提炼、Skill 检测、反馈回流和跨平台知识库初始化。"
version: 0.3.5
phase: 3
---

# Knowledge Iteration System

小夏四层知识蒸馏系统 —— 总控 Skill。

## Phase Status

**当前版本：v0.3.4（Phase 3 — 输出回流 + Skill 升级路径 + LLM 批量统一 + per-task 自动化）**

| Phase | 交付内容 | 状态 |
|---|---|---|
| Phase 1 | SKILL.md、references、templates、路径无关规范、Setup/Preflight 契约 | ✅ 已交付 |
| Phase 2 | `scripts/` 目录下的自动化脚本（`kis_config.py`、`setup_preflight.py`、workflow 脚本、`run_all.py`、跨平台安装器） | ✅ 已交付 |
| Phase 3 | 输出层反馈闭环 `feedback_loop.py` 实现落盘、`kis_llm` batch API、`skill_detector --llm=<off\|auto\|api\|file>` 统一四种模式、`skill_upgrader.py` Skill 升级路径工具 | ✅ 已交付 |
| v0.2+ | 自动化改为 **per-task 独立调度**（9 个 LaunchAgent / cron / Task Scheduler），支持 `--list-tasks` / `--set-task` / `--enable-task` / `--disable-task` 精细控制 | ✅ 已交付 |

> **安装提示**：本 Skill 的 `scripts/*.py` 与安装脚本均已随仓库发行（位于仓库的 `scripts/` 目录）。新安装参考 [`README.md`](../../README.md)：将 `scripts/` 复制到 Vault 根，可选配置 `.env`（LLM key），然后跑 `python3 scripts/setup_preflight.py --create-missing` 完成预检。

## Core Philosophy

```
粗放输入 → AI 蒸馏 → 可复用资产 → 输出回流 → 再迭代
```

不是把笔记放整齐，而是把信息炼成知识资产、方法论、Skill 和可发布输出。

## Four Layers

1. **Inbox（输入层）** — 随手丢，不整理。想法、灵感、Clippings。
2. **Distilled（蒸馏层）** — AI 提炼：日报、周报、想法追踪、Clippings 提炼。
3. **Skills（技能层）** — 可复用方法论、工作流、Prompt 系统、Skill 候选（`skill_detector` 生成 EVAL 卡，`skill_upgrader` 出升级路线图）。
4. **Output（输出层）** — 发布内容 + 反馈数据回流。

## Setup / Preflight Requirement

This Skill is shareable and **must be path-agnostic**. Do not assume the user's computer has 小夏's local path or exact folder structure.

Before writing to a knowledge base or running scripts, resolve the user's local setup:

1. Ask for or receive the knowledge base root path.
2. Check whether the four layer roles exist: Inbox, Distilled, Skills, Output.
3. If no four-layer structure exists, offer to create the recommended structure under the specified root.
4. If a similar structure exists, ask the user to map existing folders to the four roles.
5. If part of the structure is missing, offer to create only the missing folders.
6. Save the resolved mapping to `.knowledge-iteration-system.json` in the knowledge base root.
7. Use the saved mapping for future captures, distillations, script execution, and outputs.

Never hardcode an absolute path such as `/Users/...` or `C:\Users\...` into shared Skill behavior. User-specific paths belong in the local config file only.

See `references/config-schema.md` and `templates/setup-preflight-report.md`.

## Design Principles

- **不打扰输入**：Inbox 阶段不分类、不补标签、不写完整标题。输入时不整理，整理时不输入。
- **蒸馏优先于归档**：每次处理都问：核心观点？可迁移原则？可做概念卡？可做方法论？可做输出？可做 Skill？
- **Skills 是第三层，不是普通笔记**：只有可重复使用、有明确输入输出、有步骤、有判断标准的内容才进入 Skill 候选。
- **输出层是回流入口**：发布后的反馈要回流到方法论、Skill 和输出策略。

## Mode Selection

从用户请求推断模式：

| 用户说 | 模式 | 对应脚本 |
|--------|------|----------|
| 初始化知识系统 / 检查四层结构 / 补齐文件夹 / 配置知识库路径 | Setup / Preflight | `setup_preflight.py` + `kis_config.py` |
| 查看/修改自动化任务 / 改定时时间 / 启用禁用某任务 | Task 表管理 | `setup_preflight.py --list-tasks` / `--set-task NAME=HH:MM` / `--enable-task NAME` / `--disable-task NAME` |
| 先记下 / 丢进知识库 / 这是一个灵感 | Inbox 捕获 | 无（手动写入） |
| 今日蒸馏 / 整理今天 / 跑 daily | 每日蒸馏 | `daily_distill.py` |
| 本周复盘 / 下周方向 / 总结趋势 | 每周复盘 | `weekly_review.py` |
| 这个想法成熟吗 / 想法追踪 | 想法追踪 | `idea_tracker.py` |
| 提炼这篇 / 小红书内容分析 | Clipping 提炼 | `clipping_refiner.py` |
| 检测 Skill 候选 / 自动 Skill 沉淀 / 生成 EVAL 卡 | Skill 候选检测 | `skill_detector.py`（可选 `--llm=<off\|auto\|api\|file>`） |
| 检查知识关联 / 知识织网 / 推荐双链 / 结构性链接 | 结构性链接建议 | `link_suggester.py` |
| Skill 升级路径 / 下一步该做什么 / EVAL 卡变 Skill / 成熟度报告 | Skill 升级路线 | `skill_upgrader.py` |
| 这篇效果怎么样 / 发布反馈 / 创作方法论总结 | 反馈回流 | `feedback_loop.py`（可选 `--llm=<off\|auto\|api>` 启用抽样 LLM 总结） |
| 季度体检 / 知识库健康度 | 季度审计 | `quarterly_audit.py` |
| 全量跑一遍 | 全量运行 | 优先 `run_all.py`；兼容 `run_all.sh` |

## Mode Details

### Setup / Preflight
首次使用、分享给别人安装、迁移电脑、路径变化、或用户要求“检查/补齐/初始化”时使用。输出包含：根路径读写状态、四层映射、子文件夹检查、缺失项、建议动作、将要创建的文件夹。模板见 `templates/setup-preflight-report.md`。

如果 `.knowledge-iteration-system.json` 不存在，先进行预检和映射确认；不要直接假设标准中文目录已经存在。

### Inbox 捕获
快速记录，不打断思路。输出包含：原始内容、来源、时间、初步标签、后续处理建议。模板见 `templates/inbox-entry.md`。

### 每日蒸馏
扫描近期新增，生成日报：新增统计、高频关键词、核心观点、可沉淀资产、明日建议。模板见 `templates/daily-distill-report.md`。

### 每周复盘
汇总一周趋势、主题聚类、最有潜力想法、下周方向。模板见 `templates/weekly-review-report.md`。

### 想法追踪
评估想法成熟度：🌱种子 → 🌿发芽 → 🌳成熟 → ✅已落地。补充判断：继续投入价值（高/中/低）。模板见 `templates/idea-maturity-report.md`。

### Clipping 提炼
对外部内容打分（0-10）、提炼金句、打标签、去重、判断转化价值。模板见 `templates/clipping-refine-report.md`。

### 结构性链接建议
生成 Clipping、想法、Skill 草稿、提炼卡之间的链接建议。默认只输出带复选框的报告，不自动改原文。用户在报告中把确认采用的 `- [ ]` 改成 `- [x]` 后，才可运行 `link_suggester.py --apply-approved` 写回已确认链接。建议优先用于“知识织网”而不是自动批量双链。

### 反馈回流
分析发布表现数据、用户反馈，沉淀标题/选题/视觉/表达/平台经验。模板见 `templates/output-feedback-report.md`。

### 季度审计
知识库健康度诊断：活跃主题、孤立节点、冷知识、需合并/升级/归档内容、知识资产化率。模板见 `templates/quarterly-audit-report.md`。

## Core Script Files

The automation scripts live in the knowledge base root under `scripts/`. Treat these as part of the Skill runtime contract.

### Configuration / Preflight Core

- `scripts/kis_config.py` — shared configuration, path resolution, default four-layer schema, folder alias detection, preflight checks, and safe creation of missing folders. All other Python scripts should use this module instead of hardcoding paths.
- `scripts/setup_preflight.py` — setup/installation preflight entrypoint. Use it to inspect a user's knowledge base, show missing folders, write `.knowledge-iteration-system.json`, and optionally create only missing folders.
- `scripts/kis_llm.py` — **[可选]** optional LLM 兜底模块：默认关闭，仅当环境变量/配置/`.env` 满足时启用。具体行为、隐私边界和关闭方法见上方“LLM 兜底调用（可选）”章节。

Recommended commands:

```bash
python scripts/setup_preflight.py
python scripts/setup_preflight.py --create-missing --dry-run
python scripts/setup_preflight.py --create-missing
```

### Workflow Scripts

- `scripts/daily_distill.py` — daily distillation; reads Inbox ideas and Clippings; writes to daily distill folder.
- `scripts/weekly_review.py` — weekly review; summarizes recent ideas and Clippings.
- `scripts/idea_tracker.py` — idea maturity tracking.
- `scripts/clipping_refiner.py` — Clippings quality scoring, tagging, quote extraction, and refinement cards.
- `scripts/skill_detector.py` — scans Inbox for reusable Skill candidates; writes drafts to the Skills layer.
- `scripts/link_suggester.py` — generates checkbox-based structural link suggestions across Clippings, ideas, Skill drafts, and refined cards; `--apply-approved` writes back only checked suggestions.
- `scripts/skill_upgrader.py` — **[Phase 3]** 读取 `技能层/待整理/EVAL_*.md`，根据 Skill 成熟度模型 Level 0-5 生成升级路线图，产物落 `技能层/Skill 升级路线图.md`。支持 `--min-yes N` 过滤、`--dry-run` 预览。
- `scripts/feedback_loop.py` — **[Phase 3 实现]** 扫描 `输出层/已发表`，本地统计（平台/月度/高频词）+ 可选 LLM 抽样总结（默认关闭），产出 `蒸馏层/输出回流分析.md` + `蒸馏层/输出回流建议.md`。支持 `--llm=<off|auto|api>`、`--sample N`、`--dry-run`。**不直接写 Skills 层**，回流建议供人工勾选后手动搬运。
- `scripts/quarterly_audit.py` — knowledge base health audit.

### Runners and Automation Installers

- `scripts/run_all.py` — cross-platform main runner. Prefer this over shell-specific wrappers.
- `scripts/run_all.sh` — macOS/Linux compatibility wrapper that delegates to `run_all.py`.
- `scripts/install_automation.sh` — macOS LaunchAgents installer; supports `--dry-run` and `--uninstall`.
- `scripts/install_automation.ps1` — Windows Task Scheduler installer; supports `-DryRun` and `-Uninstall`.
- `scripts/install_automation_linux.sh` — Linux cron installer; supports `--dry-run` and `--uninstall`.

> **LaunchAgent 命名说明（v0.2+ per-task）**：macOS 自动化为每个启用的任务生成一个独立 LaunchAgent，label 格式 `com.knowledge-iteration.<task_key>`，共 9 个：`daily_distill` / `idea_tracker` / `clipping_refiner` / `skill_detector` / `link_suggester` / `skill_upgrader` / `feedback_loop` / `weekly_review` / `quarterly_audit`。
>
> 旧 label 会在新安装时被自动 bootout 并清理旧 plist：
> - `com.karpathy.knowledge.distiller`（更早的历史命名）
> - `com.knowledge-iteration.distiller`（v0.1 单任务命名）
>
> **plist 是生成产物**：`install_automation.sh` 会从 `.knowledge-iteration-system.json` 的 `automation.tasks` 表动态生成包含绝对路径的 plist。**不要把生成后的 plist 提交到共享仓库或分发 Skill 包**，它包含本机绝对路径；仓库/Skill 包内应只保留生成器脚本。

Recommended cross-platform commands:

```bash
# 全量 / 单步
python scripts/run_all.py --dry-run --preflight
python scripts/run_all.py --only daily --days 2
python scripts/run_all.py --only weekly
python scripts/run_all.py --only clipping
python scripts/run_all.py --only skill        # skill_detector
python scripts/run_all.py --only link
python scripts/run_all.py --only upgrader     # skill_upgrader
python scripts/run_all.py --only feedback
python scripts/run_all.py --only audit
python scripts/run_all.py                     # 依次跑全部 9 步

# 结构性链接：先看再改（写用户源文件，强制先 dry-run）
python scripts/link_suggester.py --apply-approved --dry-run
python scripts/link_suggester.py --apply-approved

# skill_detector LLM 路由
python scripts/skill_detector.py                          # 纯正则
python scripts/skill_detector.py --llm=auto               # kis_llm 可用则 batch API，否则降级文件桥
python scripts/skill_detector.py --llm=api                # 强制走 kis_llm batch API
python scripts/skill_detector.py --llm=file               # 强制走文件桥（手动拷贴到其他 AI 工具）

# feedback_loop LLM 抽样
python scripts/feedback_loop.py                           # 纯本地统计
python scripts/feedback_loop.py --llm --sample 30         # 抽样 30 篇让 LLM 归纳规律

# per-task 自动化管理
python scripts/setup_preflight.py --list-tasks
python scripts/setup_preflight.py --set-task daily_distill=09:00
python scripts/setup_preflight.py --disable-task feedback_loop
python scripts/setup_preflight.py --ask-tasks             # 交互式重配
bash scripts/install_automation.sh --dry-run              # 预览会安装的 9 个 plist
bash scripts/install_automation.sh                        # 实际安装
bash scripts/install_automation.sh --uninstall            # 全部卸载
```

Script rule: when adding or modifying workflow scripts, import `kis_config.py` helpers (`layer_path`, `subfolder_path`, `preflight`) instead of duplicating path/config logic.

## LLM 兜底调用（可选）

Phase 2 引入 `scripts/kis_llm.py` 作为可选的 LLM 兜底层。目前直接使用它的是 `skill_detector.py`（五维度诊断 + 使用情境抽取 + Skill 形态推断，均支持批量 API）和 `feedback_loop.py`（`call_json` 抽样归纳）。

### 默认行为

**默认关闭。** 仅当以下任一条件满足时启用：

- 环境变量 `KIS_LLM_API_KEY` 或 `OPENAI_API_KEY` 已设置
- `.knowledge-iteration-system.json` 里配了 `llm.enabled: true` + `base_url` + `model` + `api_key_env`
- 项目根目录 `.env` 里存在对应 KEY=xxx

任何缺失、超时、HTTP 错误或 JSON 解析失败→ 抛 `LLMUnavailable` → 上层写入"LLM 不可用，使用正则结果"，**不阻断主流程**。

### ⚠️ 隐私边界（重要）

启用 LLM 兜底后，**Clipping / 想法的原文内容会被切片后发送到你配置的 LLM 端点**（OpenAI 或兼容端点）。具体行为：

- 每个候选单独调用，单次 ≤ 8000 字符（`MAX_INPUT_CHARS`）
- 内容级缓存写到 `.kis-cache/skill_eval/*.json`，重复跑不重复调
- 传输内容：Clipping/想法的原文 + 提示词。**不会**传输完整知识库、文件名、日历、个人信息

如果知识库含敏感内容（健康记录、客户数据、未公开创作、密码/登录凭证等）：

- **不要**设置 `KIS_LLM_API_KEY` / `OPENAI_API_KEY`
- **不要**在配置里写 `llm.enabled: true`
- 保持默认关闭即可完全本地运行

### 两套 LLM 桥已在 v0.3 统一进 `--llm=<mode>`

`skill_detector.py` 历史上实现了一套 **文件桥**机制（写 `.llm_prompt.txt`、等外部填 `.llm_result.json`）；`kis_llm.py` 后来加入了直接 API 调用。v0.3 起两者已统一由 `--llm=<mode>` 控制（下文详述），共存问题解决。

选择机制：

| 场景 | 推荐机制 | 命令 |
|---|---|---|
| 有 API key、允许自动发外部 | `kis_llm.py`（直调） | `--llm=api` |
| 有 key 但想让脚本自动兜底 | 自动选路 | `--llm=auto` |
| 无 API key、手动拷贴到其他 AI 工具 | 文件桥 | `--llm=file` |
| 完全不想用 LLM | 纯正则 | `--llm=off`（默认） |

内部 API（Phase 3 稳定接口）：

- `kis_llm.probe() -> (ok, message)` 不调用外部服务，只检查配置完整性
- `kis_llm.call_section1(content)` 单候选五维度诊断
- `kis_llm.call_section2(content)` 单候选使用情境抽取
- `kis_llm.call_section3(content)` 单候选 Skill 形态推断（Phase 3.1 新增）
- `kis_llm.call_section1_batch(items)` **批量** 五维度诊断
- `kis_llm.call_section2_batch(items)` **批量** 使用情境抽取
- `kis_llm.call_section3_batch(items)` **批量** Skill 形态推断（Phase 3.1 新增）
- `kis_llm.call_json(system, user, cache_purpose=...)` 自定义 JSON 总结（供 feedback_loop 使用）
- `kis_llm.LLMUnavailable` 统一异常类型

所有其他 workflow 脚本（daily / weekly / clipping / idea / link / audit）**完全不调 LLM**，只靠本地规则与词频，保证无网环境、无 API 也能跑。`feedback_loop` 默认不调 LLM，用户显式 `--llm` 时才启用。

### Section 2 与 Section 3 AI 兜底（Phase 3.1 交付）

EVAL 卡的「服务谁/用在哪/达到什么效果」（Section 2）与「建议的 Skill 形态」（Section 3）里的子项目，若正则抽不到，将自动调 kis_llm 推断并标记为【原文未明确，AI 分析结果】。真正抽不到的字段仍保留【待补充】，避免脑补。

Section 3 新增字段：inputs / outputs / tools_required / not_required；形态与关键动作数仍走正则抽取。

run_all 中 skill_detector 默认使用 `--llm=auto`：
- kis_llm 配置就绪 → 直接走批量 API（每批 8 项、timeout 90s、429 自动指数退避重试 3 次）
- kis_llm 未配置 → 降级为文件桥 / 纯正则，不阻塞

### 两套 LLM 桥现已统一进 `--llm=<mode>`

`skill_detector.py --llm` 支持四种模式：

- `off`（默认）：完全不调 LLM，仅用正则
- `auto`（不传参时默认）：kis_llm 可用则走 batch API，否则降级文件桥
- `api`：强制使用 kis_llm batch API
- `file`：强制使用文件桥（写 `.llm_prompt.txt`、手动拷贴到其他 AI 工具、把结果填回 `.llm_result.json`）

### `feedback_loop.py` 当前状态（Phase 3 · γ 方案）

**已从骨架升级为实现**：
- 扫描 `第四层：输出层 (Output)/已发表/` 目录
- 本地统计（平台分布 / 月度分布 / 高频词），产出 `第二层：蒸馏层 (Distilled)/输出回流分析.md`
- 独立建议清单 `第二层：蒸馏层 (Distilled)/输出回流建议.md`（供人工审阅后决定是否手搬到 Skills 层）
- 可选 LLM 抽样总结：`--llm=<off|auto|api>` + `--sample N`（默认 20），未启用时纯本地统计
- **不静默改 Skills 层**：只输出建议，用户勾选后自行搬运

## Script Execution Rules

**脚本不是默认自动执行。** 规则：

1. 用户只说"分析/总结/给方案" → 用推理和文件检查完成，不跑脚本。
2. 用户明确说"运行脚本/跑一下/执行自动化" → 才调用对应脚本。
3. 用户说"全量跑一遍" → 才运行 `run_all.sh` 或 `run_all.py`。
4. 用户说"安装定时任务" → 才考虑 `install_automation.sh`。

执行前检查：
- 确认知识库路径（优先读取 `.knowledge-iteration-system.json`；不存在则进入 Setup / Preflight）。
- 检查脚本是否存在。
- 说明将会生成或修改哪些文件。
- 对 `run_all.sh`、`run_all.py`、`install_automation.sh`、`install_automation.ps1`、`install_automation_linux.sh` 等全量/自动化入口额外确认。
- 不做删除、移动、重命名等破坏性操作。

**Dry-run 通用规则（强制）：**

凡是会 **写入用户源文件**、**修改系统级配置**、**或具有潜在破坏性**的命令，**必须先跑一次 `--dry-run`（或对应 `-DryRun`）并把差异展示给用户，得到明确确认后才可实执行**：

- `--create-missing`（`setup_preflight.py`）→ 创建目录与写配置
- `--apply-approved`（`link_suggester.py`）→ 回写用户源文件
- `--uninstall` / `-Uninstall`（`install_automation*` 脚本）→ 卸载系统任务
- 任何未来新增的写回、删除、移动、重命名类参数

**不强制需要 dry-run 的情况**：幂等覆盖写入固定产物的常规报告命令（daily / weekly / idea / clipping / skill_detector / feedback_loop / quarterly_audit）——它们只写入自己输出目录下的报告文件，不碰用户源文件，重复跑只会更新自己的产物。但它们仍推荐实现 `--dry-run` 作为预览开关（非强制）：作为“跑之前想看看会执行什么”的方便手段。

没有 `--dry-run` 支持的写操作，如果它写用户源文件或系统配置，等同于需要用户逐条列出会写入哪些文件后再确认。

## Asset Type Judgment

每次蒸馏后判断知识适合变成什么资产：
- 想法追踪条目 / 设计原则 / Prompt 模板 / 工作流 / Skill 候选 / 输出选题 / 案例素材 / 暂存或归档

## Standard Output Format

处理任何内容时优先使用此结构：
1. 输入判断（类型、来源、当前层级、推荐模式）
2. 核心蒸馏（一句话总结、关键词、核心观点、反直觉点）
3. 知识关联（相关主题、关联旧知识、可能冲突）
4. 资产化判断（推荐类型、存放位置、资产价值）
5. Skill/Output 可能性
6. 下一步行动

## References

- `references/architecture.md` — 四层架构详细说明
- `references/maturity-model.md` — 想法成熟度与 Skill 成熟度模型
- `references/scoring-rubric.md` — Clipping 评分、Skill 候选评分、知识健康度评分
- `references/workflow-map.md` — 自然语言到脚本的映射关系
- `references/cross-platform.md` — 跨平台兼容性说明
- `references/config-schema.md` — 本地配置文件与四层路径映射规范

## Templates

- `templates/inbox-entry.md`
- `templates/setup-preflight-report.md`
- `templates/daily-distill-report.md`
- `templates/weekly-review-report.md`
- `templates/idea-maturity-report.md`
- `templates/clipping-refine-report.md`
- `templates/skill-candidate-report.md`
- `templates/output-feedback-report.md`
- `templates/quarterly-audit-report.md`

## Skill Boundaries

**应该做：** 选择正确工作流、解释脚本产物、判断知识资产价值、生成模板化报告、辅助识别 Skill 候选、辅助输出层搭建、辅助季度体检。

**不应该做：** 每次都自动跑全量脚本、把所有内容都做成 Skill、把 Inbox 变成精细分类系统、过度追求标签完整性、无授权改写大量知识库文件。
