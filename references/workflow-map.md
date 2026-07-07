# 自然语言到脚本的映射

## 脚本路径

所有脚本位于知识库根目录下的 `scripts/` 目录。

## 映射表

| 用户请求关键词 | 模式 | 脚本 |
|---------------|------|------|
| 初始化知识系统、检查四层结构、补齐文件夹、配置知识库路径 | Setup / Preflight | 无脚本；执行文件系统检查与配置写入 |
| 今日蒸馏、整理今天、daily distill、跑daily | 每日蒸馏 | `python scripts/daily_distill.py`（默认增量 checkpoint）；`--days N` / `--since YYYY-MM-DD` 手动时间窗（不读写 checkpoint）；`--reset-checkpoint` 清状态；`--classify=keyword|llm|off` 控制输入层分类 |
| 本周复盘、下周方向、weekly review、总结趋势 | 每周复盘 | `python scripts/weekly_review.py`（默认增量 checkpoint，独立于日报 key） |
| 想法成熟度、想法追踪、评估想法 | 想法追踪 | `python scripts/idea_tracker.py`（递归扫描 `想法/` 全树） |
| 提炼clipping、小红书内容分析、clip refine | Clipping 提炼 | `python scripts/clipping_refiner.py` |
| 检测skill、能不能做成skill、skill detect | Skill 检测 | `python scripts/skill_detector.py`（`--llm=off/auto/api/file`） |
| 输入层分类、分类目录、给输入打标签、catalog、这些内容都是什么主题 | 输入层分类目录 | 集成在每日蒸馏：`python scripts/daily_distill.py --classify=keyword`（或 `llm`）；产物 `输入层分类目录.md` + 待审队列。不单独跑，由 kis_classifier/kis_catalog 支撑 |
| 声明自己的分类、自定义领域、onboarding、taxonomy | 分类 onboarding | `python scripts/kis_onboard.py --status`（看现有）/ `--template`（拿模板）/ `--validate`（校验）/ `--write --file X.json`（落盘深合并）。非阻塞：agent 引导问答，脚本只校验+写入 |
| 检查知识关联、知识织网、推荐双链、结构性链接、link suggest | 结构性链接建议 | `python scripts/link_suggester.py`（默认只生成报告）；`--apply-approved` 写回已确认链接；`--similarity tfidf|legacy` 选相似度后端 |
| 反馈回流、发布效果、feedback loop、创作方法论总结 | 反馈回流 | `python scripts/feedback_loop.py`（默认无 LLM）；`--llm=auto` 启用 kis_llm 抽样总结；`--sample N` 控制抽样量 |
| Skill 升级路线、下一步该做什么、EVAL 变 Skill、成熟度报告 | Skill 升级路线图 | `python scripts/skill_upgrader.py`；`--min-yes N` 过滤弱候选 |
| 季度体检、知识库健康度、quarterly audit | 季度审计 | `python scripts/quarterly_audit.py` |
| 全量跑、一键运行、run all | 全量运行 | 优先 `python scripts/run_all.py`；兼容 `bash scripts/run_all.sh` |
| 安装定时任务、自动化安装 | 安装自动化 | macOS: `bash scripts/install_automation.sh`; Windows: `powershell -ExecutionPolicy Bypass -File scripts/install_automation.ps1`; Linux: `bash scripts/install_automation_linux.sh`（cron；systemd 可后续扩展） |

## 安全规则

1. 不默认运行任何脚本，除非用户明确要求。
2. 运行前确认知识库路径。
3. 运行前检查脚本是否存在。
4. 运行前说明会生成或修改哪些文件。
5. 对 `run_all.sh`/`run_all.py` 和所有 `install_automation*` 脚本额外确认。
6. 不做删除、移动、重命名等破坏性操作。
7. `.knowledge-iteration-system.json` 不存在时，先进入 Setup / Preflight，不直接假设标准目录存在。

## Python 命令差异

- macOS/Linux：常见为 `python3 scripts/xxx.py`
- Windows：常见为 `python scripts/xxx.py`
- 跨平台推荐：`python scripts/xxx.py`，并在总入口脚本内使用 `sys.executable`

## 跨平台入口优先级

1. 优先使用 `python scripts/run_all.py`，因为 Python 跨平台能力最好。
2. `bash scripts/run_all.sh` 只作为 macOS/Linux 或 Git Bash/WSL 环境下的兼容入口。
3. 自动化安装按平台选择，不要在 Windows 上运行 macOS LaunchAgents 脚本。
4. Windows 自动化使用 Task Scheduler；macOS 使用 LaunchAgents；Linux 使用 cron 或 systemd timer。

## 运行前说明模板

执行脚本前，用类似格式说明：

```text
将运行：python scripts/daily_distill.py
知识库：<root>
预计读取：Inbox / Clippings
预计写入：第二层：蒸馏层 (Distilled)/每日蒸馏
不会删除、移动或重命名已有文件。
```
