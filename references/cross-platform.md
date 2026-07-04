# 跨平台兼容性说明

## 总体结论

四层知识结构和 Skill 逻辑跨平台可用。脚本层和自动化安装层需要适配。

## 平台支持矩阵

| 功能 | macOS | Windows | Linux |
|------|-------|---------|-------|
| 四层文件夹结构 | ✅ | ✅ | ✅ |
| Markdown 笔记 | ✅ | ✅ | ✅ |
| Python 脚本核心逻辑 | ✅ | ✅ | ✅ |
| `run_all.sh` | ✅ | ❌ 需 Git Bash/WSL | ❌ 需 Bash |
| `run_all.py`（新增） | ✅ | ✅ | ✅ |
| `install_automation.sh` | ✅ LaunchAgents | ❌ | ❌ |
| `install_automation.ps1` | ❌ | ✅ Task Scheduler | ❌ |
| `install_automation_linux.sh` | ❌ | ❌ | ✅ cron |

## 路径处理

- 使用 `pathlib.Path` 替代手动拼接路径字符串
- 配置文件使用相对路径，便于 Vault 迁移
- Windows 注意：中文全角冒号 `：` 可用，英文半角冒号 `:` 不可用作文件夹名

## Python 命令

- macOS/Linux 常用 `python3`，Windows 常用 `python`
- 跨平台脚本使用 `sys.executable` 自动检测


## Shareable Skill 改造重点

要让这个 Skill 在不同电脑上稳定使用，需要做到：

1. 首次使用先进入 Setup / Preflight，不默认写入。
2. 通过 `.knowledge-iteration-system.json` 保存本地路径映射。
3. 配置中优先保存相对路径，而不是绝对路径。
4. 脚本读取配置后再定位四层目录。
5. `run_all.py` 作为跨平台主入口，`.sh` / `.ps1` 只处理平台专属自动化。
6. 自动化安装必须按平台分流：macOS LaunchAgents、Windows Task Scheduler、Linux cron/systemd。
7. 所有写入操作只补缺，不覆盖；所有破坏性操作必须另行确认。
