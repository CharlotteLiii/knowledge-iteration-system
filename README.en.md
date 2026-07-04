# 📚 Knowledge Iteration System

> 🇨🇳 中文版：[README.md](./README.md)

> A **four-layer knowledge distillation system** inspired by Karpathy's take on personal knowledge bases — turning you from an "info-hoarding bookmark addict" into someone who actually distills reusable methods.

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg) ![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg) ![Platform: macOS | Linux | Windows](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)

## 🧠 What it does

It runs an automated pipeline over the four kinds of content scattered across your Obsidian (or any markdown-based) knowledge base:

1. **Inbox layer** — random ideas + clippings (Xiaohongshu, Bilibili, WeChat articles, etc.)
2. **Distilled layer** — AI-assisted **daily distillation, weekly review, clipping refinement, idea tracking, structural link suggestions, output feedback analysis, quarterly audits**
3. **Skills layer** — detects **reusable Skill candidates** from your clippings, produces evaluation cards (🔴 strongly recommended / 🟡 partially suitable / 🟢 not recommended standalone), and generates a Level 0–5 upgrade roadmap
4. **Output layer** — tracks what you publish and feeds the reactions back into your methodology

## ✨ Features

- 🤖 **Optional LLM fallback** — off by default. Declare any OpenAI-compatible provider yourself and it kicks in automatically (OpenAI / DeepSeek / Zhipu GLM / Tongyi / Volcengine Ark / self-hosted — anything works)
- 🌍 **Cross-platform automation** — one-command installers for macOS LaunchAgent / Linux cron / Windows Task Scheduler
- 🔒 **Privacy-first** — every analysis runs locally; external APIs are only called when you explicitly configure one
- 📊 **9-step full pipeline** — a single `run_all.py` runs the whole distillation flow
- 🛡 **Write only, never mutate** — structural link suggestions ship as a checklist; nothing gets written back until you tick it
- 💾 **Honest tagging** — AI-inferred fields are labeled "AI 分析结果" (AI analysis), regex-extracted fields are labeled "原文抽取" (from source); if we don't know, we just say "待补充" (to fill in)

## 🚀 Quick start

### Requirements

- Python 3.10+
- A markdown-based knowledge base (Obsidian recommended, but any folder of `.md` files works)
- (Optional) Any OpenAI-compatible LLM API key

### Installation

```bash
# 1. Clone somewhere temporary
git clone https://github.com/<your-username>/knowledge-iteration-system.git
cd knowledge-iteration-system

# 2. Copy scripts/ into your Vault root
cp -R scripts /path/to/your/vault/

# 3. Copy .env.example to the Vault root, rename to .env, fill in your API key (optional — works without one)
cp .env.example /path/to/your/vault/.env
# Edit .env and drop in your LLM API key

# 4. Enter the Vault and run the first-time preflight
cd /path/to/your/vault
python3 scripts/setup_preflight.py --create-missing
```

`setup_preflight` will:
- Inspect your existing directory structure and map it to the four layers
- **Only create missing four-layer sub-folders** (never overwrites your existing folders)
- Write `.knowledge-iteration-system.json` to record the config
- Generate `📚 知识迭代系统说明.md` at your Vault root as the landing doc

### One-shot full run

```bash
cd /path/to/your/vault
python3 scripts/run_all.py
```

The 9-step pipeline runs in order:
```
[1/9] daily_distill      Daily distillation
[2/9] weekly_review      Weekly review
[3/9] idea_tracker       Idea maturity tracking
[4/9] clipping_refiner   Clipping refinement + cards
[5/9] skill_detector     Skill candidate detection (with AI fallback)
[6/9] link_suggester     Structural link suggestions
[7/9] skill_upgrader     Skill upgrade roadmap
[8/9] feedback_loop      Output feedback loop
[9/9] quarterly_audit    Quarterly asset audit
```

## 📅 Scheduled automation (optional)

### macOS

```bash
bash scripts/install_automation.sh                # run daily at 10:00
bash scripts/install_automation.sh --interval 3   # run every 3 days
bash scripts/install_automation.sh --dry-run      # preview only
bash scripts/install_automation.sh --uninstall    # uninstall
```

### Linux

```bash
bash scripts/install_automation_linux.sh
```

### Windows (PowerShell)

```powershell
.\scripts\install_automation.ps1
.\scripts\install_automation.ps1 -Interval 3
.\scripts\install_automation.ps1 -DryRun
.\scripts\install_automation.ps1 -Uninstall
```

To change the automation cadence: edit `automation.dailyIntervalDays` in `.knowledge-iteration-system.json`, then re-run the install script.

## 🗂 Directory layout

After installation your Vault looks like this:

```
Your Vault/
├── scripts/                          ← copied from this repo
├── .env                              ← your LLM config (already in .gitignore)
├── .knowledge-iteration-system.json  ← system config
├── 📚 知识迭代系统说明.md            ← landing doc
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
│   ├── 待整理/EVAL_*.md              ← skill_detector.py (Skill candidate cards)
│   ├── Skill 升级路线图.md          ← skill_upgrader.py
│   └── _drafts/                     ← your hand-written Skill drafts
└── 第四层：输出层 (Output)/
    └── 已发表/                      ← what you've published on each platform
```

## 🤖 LLM fallback

**Off by default. No provider is preset — you declare your own.**

Get the following 3 fields from your chosen LLM provider (the provider must expose an OpenAI-compatible `/chat/completions` endpoint):

| Field | Meaning | Example |
|---|---|---|
| `KIS_LLM_BASE_URL` | API base URL (usually ends in `/v1`, `/v3`, `/paas/v4`) | `https://api.openai.com/v1` |
| `KIS_LLM_MODEL` | A model name in that provider's catalog | `gpt-4o-mini` |
| `KIS_LLM_API_KEY` | API key issued by the provider | `sk-...` |

Put them in `.env` at your Vault root (copy `.env.example` and rename):

```bash
KIS_LLM_BASE_URL=<your provider base url>
KIS_LLM_MODEL=<model name>
KIS_LLM_API_KEY=<your key>
```

Verify: `python3 scripts/kis_llm.py` (prints `READY` or `DEGRADED`).

### Compatibility switch (optional)

Some providers reject `response_format={"type":"json_object"}` (e.g. Volcengine Ark's plan endpoint with `ark-code-latest`) and return `InvalidParameter` / `BadRequest`. When you hit that, add one line to `.env`:

```bash
KIS_LLM_DISABLE_JSON_MODE=1
```

The prompts still explicitly ask for JSON and the scripts parse the response fine.

### Where the LLM is used:
- `skill_detector` — Section 2 (who / where / expected outcome) and Section 3 (Skill form factor) go **fully through AI analysis**
- `feedback_loop` — samples published content for pattern summaries (togglable, off by default)

**Privacy boundary:**
- The API is only called when you explicitly run with `--llm=auto|api`
- One request per document — the whole Vault is never dumped in bulk
- Responses cache locally under `.kis-cache/` (already in `.gitignore`)

**Switching providers:** just change `BASE_URL` / `MODEL` / `API_KEY` in `.env`. Any OpenAI-compatible endpoint works. See `.env.example` for ready-to-use provider blocks (OpenAI / DeepSeek / Zhipu / Volcengine Ark, etc.).

## 📖 Learn more

- [`SKILL.md`](./SKILL.md) — Skill usage contract & AI behavior conventions
- [`references/architecture.md`](./references/architecture.md) — Four-layer architecture in depth
- [`references/config-schema.md`](./references/config-schema.md) — Config file format
- [`references/workflow-map.md`](./references/workflow-map.md) — What each script does & when to run it
- [`references/maturity-model.md`](./references/maturity-model.md) — Skill maturity Level 0–5
- [`references/scoring-rubric.md`](./references/scoring-rubric.md) — Content value scoring
- [`references/cross-platform.md`](./references/cross-platform.md) — Cross-platform notes
- [`templates/`](./templates/) — Markdown templates for every report

## 🌐 Cloud-sync caveats

If your Vault lives inside iCloud Drive / OneDrive / Dropbox / Google Drive / Baidu Netdisk / Nutstore or similar:

- Make sure the sync client isn't locking files before you first run `run_all.py`
- Let sync settle before the scheduled job kicks in
- See the cloud-sync warning in `references/cross-platform.md`

## 🛠 FAQ

**Q: Can I run it without configuring an LLM?**
A: Yes. `skill_detector` falls back to pure regex; the other 8 scripts don't need an LLM at all.

**Q: How long does a full run take?**
A: Usually < 30 seconds without an LLM. With LLM enabled and 30+ candidates, expect ~10–15 minutes (bounded by API rate limits).

**Q: Do the scripts modify my original files?**
A: No. Every output lands in **new files**. The only exception is `link_suggester.py --apply-approved`, which appends a managed "related links" block to the clippings you ticked — the block sits between HTML comment markers, so re-running replaces it without duplication.

**Q: How do I uninstall?**
A: Run the platform-specific `install_automation.* --uninstall`. Deleting the `scripts/` directory also works; no daemons are left behind.

## 📝 License

[MIT](./LICENSE)

## 🙏 Acknowledgements

Design inspired by Andrej Karpathy's musings on how personal knowledge bases can avoid becoming information graveyards.

---

**Contributions & feedback**: issues welcome — new scripts, new templates, new platform adapters, all fair game!
