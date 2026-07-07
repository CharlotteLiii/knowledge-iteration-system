# 📚 Knowledge Iteration System

> 🇬🇧 English version: [README.en.md](./README.en.md)

> 基于 Karpathy 知识库理念打造的**四层知识蒸馏系统** —— 帮你从"信息焦虑收藏党"变成"能沉淀方法论的产出者"。

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg) ![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg) ![Platform: macOS | Linux | Windows](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)

## 🧠 它做什么

把你散落在 Obsidian（或任何 markdown 知识库）里的四类内容自动流水线化：

1. **输入层**：想法碎片 + Clippings（小红书、B 站、微信文章…）
2. **蒸馏层**：AI 帮你做**每日蒸馏、每周复盘、Clipping 提炼、想法追踪、结构性链接建议、输出回流分析、季度审计**
3. **技能层**：从 clippings 自动检测出**可复用的 Skill 候选**，出评估卡（🔴 强烈建议做 / 🟡 部分适合 / 🟢 不建议单独做），并给出 Level 0-5 升级路线
4. **输出层**：跟踪你发出去的内容，回流反馈到方法论

## ✨ 特性

- 🤖 **可选 LLM 兜底**：默认关闭，自己声明任意 OpenAI 兼容供应商就自动上（OpenAI / DeepSeek / 智谱 GLM / 通义 / 火山方舟 / 自搭建都行）
- ⏩ **增量 checkpoint**：每日蒸馏 / 每周复盘默认只处理「自上次运行以来新增或改动」的文档；mtime 快筛 + 内容 hash 兜底，云盘刷新时间戳也不会重复处理
- 🗂 **输入层自动分类目录**：给每篇输入内容打多标签（复用你的 taxonomy 分类），生成「按分类看 / 按文档看」双视图目录；关键词零命中归「其他」并进待审队列
- 🧭 **Taxonomy onboarding**：首次使用可声明你自己领域的分类（不声明也能用通用默认）
- 🌍 **三平台自动化**：macOS LaunchAgent / Linux cron / Windows Task Scheduler，一键安装
- 🔒 **隐私优先**：所有分析本地跑，只有明确配置了才调外部 API
- 📊 **9 步全量流水线**：`run_all.py` 一条命令跑完所有蒸馏
- 🛡 **只写产物、不改原文**：结构性链接建议默认给"待勾选清单"，人工确认才写回
- 💾 **诚实标注**：AI 补的字段全部标"AI 分析结果"，正则抽的标"原文抽取"，没答案就"待补充"

## 🚀 快速开始

### 前置要求

- Python 3.10+
- 一个 markdown 知识库（推荐 Obsidian，但任何 `.md` 目录都行）
- （可选）任意 OpenAI 兼容的 LLM API key

### 安装步骤

```bash
# 1. clone 到本地临时位置
git clone https://github.com/<你的用户名>/knowledge-iteration-system.git
cd knowledge-iteration-system

# 2. 把 scripts/ 复制到你的 Vault 根目录
cp -R scripts /path/to/your/vault/

# 3. 复制 .env.example 到 Vault 根，改名 .env 并填 API key（可选，不填也能跑）
cp .env.example /path/to/your/vault/.env
# 编辑 .env 填入你的 LLM API key

# 4. 进入 Vault 目录做首次预检
cd /path/to/your/vault
python3 scripts/setup_preflight.py --create-missing
```

`setup_preflight` 会：
- 检测你现有目录结构，看能否映射到四层
- 缺少的四层子目录**只创建缺失的**（不覆盖你的已有目录）
- 生成 `.knowledge-iteration-system.json` 记录配置
- 生成 `📚 知识迭代系统说明.md` 放到 Vault 根

### 一键全量跑

```bash
cd /path/to/your/vault
python3 scripts/run_all.py
```

9 步流水线依次跑完：
```
[1/9] daily_distill      每日蒸馏
[2/9] weekly_review      每周复盘
[3/9] idea_tracker       想法成熟度追踪
[4/9] clipping_refiner   Clippings 卡片化提炼
[5/9] skill_detector     Skill 候选检测（AI 兜底）
[6/9] link_suggester     结构性链接建议
[7/9] skill_upgrader     Skill 升级路线图
[8/9] feedback_loop      输出反馈回流
[9/9] quarterly_audit    季度资产审计
```

## ⏩ 增量扫描与输入层分类

### 增量 checkpoint（默认）

`daily_distill` / `weekly_review` 默认只处理**自上次运行以来新增或内容变化**的文档，状态存在 `<vault>/.kis_state.json`（日报与周报各自独立 key）。

- 判据：mtime 快筛 + 内容 hash 兑底 —— 云盘同步刷新 mtime **不会**把未改内容的文件误当新增。
- 漏跑自动补扫；连跑不重叠（报告成功后才推进 checkpoint）。

```bash
# 默认：自上次以来的增量
python3 scripts/daily_distill.py

# 手动覆盖（不读写 checkpoint）
python3 scripts/daily_distill.py --days 7            # 最近 7 天
python3 scripts/daily_distill.py --since 2026-07-01  # 指定日期起

# 清除本任务 checkpoint（下次全量视为增量）
python3 scripts/daily_distill.py --reset-checkpoint
```

> 想法扫描根为`第一层：输入层 (Inbox)/想法`，**递归包括所有子目录**（如 `想法/灵感集/`）。daily / weekly / idea_tracker 三者口径一致。

### 输入层分类目录

每日蒸馏时会对增量文档做**多标签分类**（一篇可属多个分类，复用你的 taxonomy 分类 key），并渲染出蒸馏层的 `输入层分类目录.md`（按分类看 / 按文档看 双视图）。

```bash
python3 scripts/daily_distill.py --classify keyword  # 默认，离线关键词
python3 scripts/daily_distill.py --classify llm      # opt-in，LLM 语义分类（无网/未配置自动降级）
python3 scripts/daily_distill.py --classify off      # 不分类
```

- 关键词零命中 → 归「其他」，并写入待审队列 `.kis_pending_categories.json`，由你事后异步处理 —— **脚本不会卡住问你**。
- LLM 后端只能**提议**新分类（写队列），无权直接改 taxonomy。

### 声明你自己的分类（onboarding）

首次使用无 `taxonomy.json` 时，系统用通用默认分类；你可以声明自己领域的分类：

```bash
python3 scripts/kis_onboard.py --status     # 看当前生效的分类
python3 scripts/kis_onboard.py --template   # 拿一份可填写的模板
# 把填好的 JSON 写入 taxonomy.json（与默认深合并）
python3 scripts/kis_onboard.py --write --file my_cats.json
```

不声明也能正常使用；声明后下次分类/链接/蒸馏自动生效。

## 📅 定时自动化（可选，v0.2+ per-task 调度）

从 v0.2 开始，自动化不再只处理“每日蒸馏”，而是为 **9 个任务**分别注册独立调度。默认时间：

| 任务 | 默认触发时间 |
|------|-------------|
| 每日知识蒸馏 `daily_distill` | 每天 21:00 |
| 想法成熟度追踪 `idea_tracker` | 每天 21:05 |
| Clippings 提炼 `clipping_refiner` | 每天 21:10 |
| Skill 候选检测 `skill_detector` | 每天 21:15 |
| 结构性链接建议 `link_suggester` | 每天 21:20 |
| Skill 升级路线图 `skill_upgrader` | 每天 21:25 |
| 输出反馈回流 `feedback_loop` | 每天 21:30 |
| 每周知识复盘 `weekly_review` | 每周日 14:00 |
| 季度知识健康审计 `quarterly_audit` | 季度最后一天 12:00 |

日常每日任务错开 5 分钟，避免 LLM API 扎堆、日志也更容易看。

### 交互式安装（首次推荐）

```bash
python3 scripts/setup_preflight.py --ask-tasks
```

会弹一个类似下面的选单：

```
【自动化任务清单】
| 任务 | 触发时间 | 启用 |
|------|----------|------|
| 每日知识蒸馏 | 每天 21:00 | ✅ |
...
选项：
  Y  按上表默认时间全部安装（推荐）
  e  逐项编辑（可禁用/改时间）
  n  不安装任何自动化任务
```

选完后跑对应平台的安装器，把配置处理成真实的系统定时任务：

```bash
# macOS
bash scripts/install_automation.sh              # 预览：--dry-run；卸载：--uninstall

# Linux
bash scripts/install_automation_linux.sh

# Windows (PowerShell)
.\scripts\install_automation.ps1                # 预览：-DryRun；卸载：-Uninstall
```

### 还可以直接用 CLI 标志改任务（不交互）

```bash
# 把每日蒸馏改到 22:30 触发
python3 scripts/setup_preflight.py --set-task daily_distill=22:30

# 禁用反馈回流 & Skill 检测
python3 scripts/setup_preflight.py --disable-task feedback_loop --disable-task skill_detector

# 把每周复盘改到周一 15:00
python3 scripts/setup_preflight.py --set-task-dow weekly_review=1 --set-task weekly_review=15:00

# 看当前所有任务的时间
python3 scripts/setup_preflight.py --list-tasks
```

改完后重跑一次 `install_automation.*`，新时间就会生效（安装器会先 bootout 旧任务、再重建）。

### 日志位置

- macOS / Linux：`scripts/logs/<task_key>.log` + `<task_key>.error.log`
- Windows：同上。

### 旧 v0.1 接口（向后兼容）

`--set-daily-interval 1/2/3/4` 仍可用且会写入 `dailyIntervalDays` 字段，但新 installer 优先读取 `automation.tasks`。建议新安装均改用 per-task 接口。

## 🗂 目录结构

安装后你的 Vault 会长这样：

```
Your Vault/
├── scripts/                          ← 从本仓库复制
├── .env                              ← 你的 LLM 配置（.gitignore 已排）
├── .knowledge-iteration-system.json  ← 系统配置
├── taxonomy.json                     ← （可选）你自定义的分类，不建就用通用默认
├── catalog.json                      ← 输入层分类数据源（自动生成，.gitignore 已排）
├── .kis_state.json                   ← 增量 checkpoint 状态（自动生成，.gitignore 已排）
├── .kis_pending_categories.json      ← 待确认分类队列（自动生成，.gitignore 已排）
├── 📚 知识迭代系统说明.md            ← 首页文档
├── 第一层：输入层 (Inbox)/
│   ├── 想法/                          ← 想法根目录，递归扫描包括子目录（如 想法/灵感集/）
│   └── Clippings/
├── 第二层：蒸馏层 (Distilled)/
│   ├── 每日蒸馏/                    ← daily_distill.py
│   ├── 每周复盘/                    ← weekly_review.py
│   ├── 想法追踪/                    ← idea_tracker.py
│   ├── 输入层分类目录.md            ← kis_catalog.py（分类双视图）
│   ├── Clippings提炼/               ← clipping_refiner.py
│   ├── 结构性链接建议/              ← link_suggester.py
│   ├── 输出回流分析.md              ← feedback_loop.py
│   ├── 输出回流建议.md
│   └── Q3_YYYY_知识资产审计.md      ← quarterly_audit.py
├── 第三层：技能层 (Skills)/
│   ├── 待整理/EVAL_*.md              ← skill_detector.py（Skill 候选评估卡）
│   ├── Skill 升级路线图.md          ← skill_upgrader.py
│   └── _drafts/                     ← 你手工写的 Skill 草稿
└── 第四层：输出层 (Output)/
    └── 已发表/                      ← 记录你发到各平台的内容
```

## 🤖 LLM 兜底说明

**默认关闭。不预设任何供应商，需要你自己声明。**

向你选定的 LLM 供应商拿以下 3 项（供应商必须提供 OpenAI 兼容的 `/chat/completions` 接口）：

| 字段 | 含义 | 示例 |
|---|---|---|
| `KIS_LLM_BASE_URL` | API 根地址（一般以 `/v1`、`/v3`、`/paas/v4` 结尾） | `https://api.openai.com/v1` |
| `KIS_LLM_MODEL` | 模型名，必须是该供应商列表里的一个 | `gpt-4o-mini` |
| `KIS_LLM_API_KEY` | 供应商颁发的 API Key | `sk-...` |

把它们写进 Vault 根目录的 `.env`（拷贝 `.env.example` 改名即可）：

```bash
KIS_LLM_BASE_URL=<你的供应商 base url>
KIS_LLM_MODEL=<模型名>
KIS_LLM_API_KEY=<你的 key>
```

验证配置：`python3 scripts/kis_llm.py`（会打印 `READY` 或 `DEGRADED`）。

### 兼容开关（选填）

部分供应商不支持 `response_format={"type":"json_object"}`（如火山方舟 Ark plan endpoint 的 `ark-code-latest`），会报 `InvalidParameter` / `BadRequest`。遇到时在 `.env` 里加一行：

```bash
KIS_LLM_DISABLE_JSON_MODE=1
```

prompt 里已经明确要求 JSON，脚本仍能正常解析。

### LLM 用途：
- `skill_detector` 里 Section 2（服务谁·用在哪·达到什么效果）和 Section 3（Skill 形态）**全走 AI 分析**
- `feedback_loop` 抽样总结发布内容特点（可关，默认关）

**隐私边界**：
- 只有你明确调 `--llm=auto|api` 才会走 API
- 每篇内容单独发一个 request，不会批量泄露整个 Vault
- 响应缓存在本地 `.kis-cache/`（`.gitignore` 已排）

**换 provider**：改 `.env` 里的 BASE_URL / MODEL / API_KEY 就行，任何 OpenAI 兼容接口都可以。完整可选供应商示例（OpenAI / DeepSeek / 智谱 / 火山方舟 Ark 等）见 `.env.example`。

## 📖 深入了解

- [`SKILL.md`](./SKILL.md) — Skill 使用契约、AI 行为约定
- [`references/architecture.md`](./references/architecture.md) — 四层架构详细设计
- [`references/config-schema.md`](./references/config-schema.md) — 配置文件格式
- [`references/workflow-map.md`](./references/workflow-map.md) — 每个脚本干什么、什么时候跑
- [`references/maturity-model.md`](./references/maturity-model.md) — Skill 成熟度 Level 0-5
- [`references/scoring-rubric.md`](./references/scoring-rubric.md) — 内容价值评分标准
- [`references/cross-platform.md`](./references/cross-platform.md) — 跨平台注意事项
- [`templates/`](./templates/) — 所有报告的 markdown 模板

## 🌐 云同步注意事项

如果你的 Vault 在 iCloud Drive / OneDrive / Dropbox / Google Drive / 百度网盘同步空间 / 坚果云等云同步目录下：

- 首次跑 `run_all.py` 时确认云同步没在锁文件
- 定时任务跑之前建议先让同步稳定
- 详见 `references/cross-platform.md` 里的云同步警告章节

## 🛠 常见问题

**Q：不配 LLM 能跑吗？**
A：能。默认全部离线：`skill_detector` 退化到纯正则，输入层分类退化到关键词，其余脚本本来就不需要 LLM。仅当你显式开启（`--llm=auto|api` 或 `--classify llm`）时才会调外部 API。

**Q：跑一次要多久？**
A：不用 LLM 通常 < 30 秒；用 LLM 且候选 ≥ 30 篇时约 10-15 分钟（受 API 速率限制）。

**Q：脚本会改我的原文件吗？**
A：不会。所有产物都在**新文件**里。唯一例外是 `link_suggester.py --apply-approved` 会往你勾选的 clipping 末尾追加一段受管理的"相关链接"块（用注释包裹，下次重跑会替换而不重复）。

**Q：怎么卸载？**
A：跑对应平台的 `install_automation.* --uninstall`。手动删 `scripts/` 目录也可以，不会残留后台进程。

## 📝 License

[MIT](./LICENSE)

## 🙏 致谢

设计灵感来自 Andrej Karpathy 关于"个人知识库如何避免变成信息坟场"的思考。

---

**贡献 & 反馈**：欢迎提 issue 讨论新脚本、新模板、新平台适配！
