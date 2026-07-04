# 📚 Knowledge Iteration System

> 🇬🇧 English version: [README.en.md](./README.en.md)

> 基于 Karpathy 知识库理念打造的**四层知识蒸馏系统** —— 帮你从"信息焦虑收藏党"变成"能沉淀方法论的产出者"。

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg) ![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg) ![Platform: macOS | Linux | Windows](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)

## 🧠 它做什么

把你散落在 Obsidian（或任何 markdown 知识库）里的四类内容自动流水线化：

1. **输入层**：想法碎片 + Clippings（小红书、B 站、微信文章…）
2. **蒸馏层**：AI 帮你做**每日蒸馏、每周复盘、Clipping 提炼、想法追踪、结构性链接建议、输出回流分析、季度审计**
3. **技能层**：从 clippings 自动检测出**可复用的 Skill 候选**，出评估卡（🔴 强烈建议做 / 🟡 部分适合 / 🟢 不建议单独做），并给出 Level 0-5 升级路线
4. **输出层**：跟踪你发出去的内容，回流反馈到方法论

## ✨ 特性

- 🤖 **可选 LLM 兜底**：默认关闭，配了 API key 就自动上（智谱 GLM / OpenAI / DeepSeek 任选）
- 🌍 **三平台自动化**：macOS LaunchAgent / Linux cron / Windows Task Scheduler，一键安装
- 🔒 **隐私优先**：所有分析本地跑，只有明确配置了才调外部 API
- 📊 **9 步全量流水线**：`run_all.py` 一条命令跑完所有蒸馏
- 🛡 **只写产物、不改原文**：结构性链接建议默认给"待勾选清单"，人工确认才写回
- 💾 **诚实标注**：AI 补的字段全部标"AI 分析结果"，正则抽的标"原文抽取"，没答案就"待补充"

## 🚀 快速开始

### 前置要求

- Python 3.9+
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

## 📅 定时自动化（可选）

### macOS

```bash
bash scripts/install_automation.sh                # 每天 10:00 自动跑
bash scripts/install_automation.sh --interval 3   # 每 3 天跑一次
bash scripts/install_automation.sh --dry-run      # 预演
bash scripts/install_automation.sh --uninstall    # 卸载
```

### Linux

```bash
bash scripts/install_automation_linux.sh
```

### Windows（PowerShell）

```powershell
.\scripts\install_automation.ps1
.\scripts\install_automation.ps1 -Interval 3
.\scripts\install_automation.ps1 -DryRun
.\scripts\install_automation.ps1 -Uninstall
```

自动化间隔调整：修改 `.knowledge-iteration-system.json` 里的 `automation.dailyIntervalDays`，然后重跑安装脚本。

## 🗂 目录结构

安装后你的 Vault 会长这样：

```
Your Vault/
├── scripts/                          ← 从本仓库复制
├── .env                              ← 你的 LLM 配置（.gitignore 已排）
├── .knowledge-iteration-system.json  ← 系统配置
├── 📚 知识迭代系统说明.md            ← 首页文档
├── 第一层：输入层 (Inbox)/
│   ├── 想法/灵感集/
│   └── Clippings/
├── 第二层：蒸馏层 (Distilled)/
│   ├── 每日蒸馏/                    ← daily_distill.py
│   ├── 每周复盘/                    ← weekly_review.py
│   ├── 想法追踪/                    ← idea_tracker.py
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

**默认关闭**。配置 `.env` 或环境变量之后自动启用：

```bash
KIS_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
KIS_LLM_MODEL=glm-4.5-flash
KIS_LLM_API_KEY=your-key
```

LLM 用途：
- `skill_detector` 里 Section 2（服务谁·用在哪·达到什么效果）和 Section 3（Skill 形态）**全走 AI 分析**
- `feedback_loop` 抽样总结发布内容特点（可关，默认关）

**隐私边界**：
- 只有你明确调 `--llm=auto|api` 才会走 API
- 每篇内容单独发一个 request，不会批量泄露整个 Vault
- 响应缓存在本地 `.kis-cache/`（`.gitignore` 已排）

**换 provider**：改 `.env` 里的 BASE_URL / MODEL / API_KEY 就行，任何 OpenAI 兼容接口都可以。

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
A：能。`skill_detector` 会退化到纯正则模式，其他 8 个脚本本来就不需要 LLM。

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
