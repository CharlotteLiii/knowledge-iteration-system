# 本地配置文件规范

## 文件名

在每个用户的知识库根目录保存：

```text
.knowledge-iteration-system.json
```

这个文件是**本地配置**，用于记录当前用户自己的四层路径映射。共享 Skill 包不应该携带某个用户的绝对路径。

## 设计原则

1. **路径无关**：Skill 不硬编码 `/Users/...`、`C:\Users\...` 或任何个人路径。
2. **优先相对路径**：配置内优先保存相对知识库根目录的路径，方便 Vault 搬家、同步和跨平台使用。
3. **角色优先于名称**：即使用户文件夹不叫标准中文名，只要映射到 Inbox / Distilled / Skills / Output 四个角色即可。
4. **只补缺，不覆盖**：初始化时只创建缺失文件夹，不覆盖、不删除、不重命名已有内容。
5. **可读可写检查**：运行脚本或写入文件前，先确认目标目录可读写。

## 推荐配置格式

```json
{
  "version": 1,
  "layers": {
    "inbox": "第一层：输入层 (Inbox)",
    "distilled": "第二层：蒸馏层 (Distilled)",
    "skills": "第三层：技能层 (Skills)",
    "output": "第四层：输出层 (Output)"
  },
  "subfolders": {
    "ideas": "第一层：输入层 (Inbox)/想法/灵感集",
    "clippings": "第一层：输入层 (Inbox)/Clippings",
    "dailyDistill": "第二层：蒸馏层 (Distilled)/每日蒸馏",
    "weeklyReview": "第二层：蒸馏层 (Distilled)/每周复盘",
    "ideaTracking": "第二层：蒸馏层 (Distilled)/想法追踪",
    "clippingRefine": "第二层：蒸馏层 (Distilled)/Clippings提炼",
    "skillDrafts": "第三层：技能层 (Skills)/_drafts",
    "published": "第四层：输出层 (Output)/已发表"
  },
  "scripts": {
    "dir": "scripts",
    "runner": "scripts/run_all.py"
  }
}
```

## 可选绝对路径字段

如果某些运行环境必须记录绝对路径，可以增加 `root` 字段：

```json
{
  "version": 1,
  "root": "/path/to/knowledge-base",
  "layers": {
    "inbox": "第一层：输入层 (Inbox)",
    "distilled": "第二层：蒸馏层 (Distilled)",
    "skills": "第三层：技能层 (Skills)",
    "output": "第四层：输出层 (Output)"
  }
}
```

但默认仍推荐相对路径。绝对路径容易在换电脑、换用户名、换盘符、云盘迁移后失效。

### ⚠️ 云同步目录风险

如果知识库位于 iCloud Drive、OneDrive、Dropbox、Google Drive、百度网盘同步空间、坚果云等**云同步目录**下：

- **永远不要写入 `root` 绝对路径字段**，只保留 `layers` / `subfolders` 相对映射。
- 不同设备上 Vault 的绝对路径几乎必然不同（用户名不同、盘符不同、云盘挂载点不同），写死 `root` 会在换设备后立刻失效。
- `.knowledge-iteration-system.json` 本身也会跟着同步，因此**它必须能在任何一台安装了该云盘的设备上直接可用**。
- 建议在 `.gitignore` 或云盘同步排除列表里评估该文件：多数场景应让它跟随同步，但**绝对不要把它上传到公开仓库或分享 Skill 包**。

## 可选顶层字段

### `docs.systemIntro` — 自动生成的说明文档位置

```json
{
  "docs": {
    "systemIntro": "第二层：蒸馏层 (Distilled)/📚 知识迭代系统说明.md"
  }
}
```

- 用途：`setup_preflight.py` 完成初始化后，会向该路径写入一份“知识迭代系统说明”文档，包含当前四层映射、自动化设置、常用命令。
- 默认值：`第二层：蒸馏层 (Distilled)/📚 知识迭代系统说明.md`
- 幂等：重复跑 preflight 会覆盖同名文件（它属于自动生成产物，以当前配置为源）。如果想保留自己写的介绍，把 `docs.systemIntro` 改为其他路径。
- 可选：不需要自动生成的介绍文档时，可完全删掉 `docs` 顶层字段，`setup_preflight.py` 会跳过这一步。

### `automation` — 自动化运行参数

```json
{
  "automation": {
    "dailyIntervalDays": 2,
    "dailyScanDays": 2,
    "dailyRunAtHour": 9,
    "askOnFirstUse": false
  }
}
```

- `dailyIntervalDays`：自动运行间隔天数。`null` / 未设置 = 不安装自动化。
- `dailyScanDays`：每次自动运行时扫描最近多少天内新增内容。
- `dailyRunAtHour`：本地时区中自动运行的小时（0-23）。
- `askOnFirstUse`：预检时是否交互式询问自动化频率。

安装器脚本（`install_automation.sh` / `.ps1` / `_linux.sh`）会读取这些字段动态生成 LaunchAgent plist / Task Scheduler XML / cron entry。因此 `automation` 字段变更不需要手改系统任务，重新跑安装器即可。

### `subfolders.linkSuggestions` / `.skillDrafts` / `.published`

除了前面列举的 8 个子文件夹角色外，以下三个仍为可选：

- `linkSuggestions`：`link_suggester.py` 写入结构性链接建议报告。
- `skillDrafts`：`skill_detector.py` 写入 Skill 候选评估卡。
- `published`：`feedback_loop.py` 从这里扫描已发表内容。

## 读取配置的推荐逻辑

伪代码：

```python
from pathlib import Path
import json

root = Path(user_provided_root).expanduser().resolve()
config_path = root / ".knowledge-iteration-system.json"

if not config_path.exists():
    # 进入 Setup / Preflight：检查四层结构、请求用户确认映射、必要时补齐文件夹
    pass
else:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    inbox = root / config["layers"]["inbox"]
```

## 初始化状态分类

预检时把用户知识库分成四种状态：

1. **完整标准结构**：四层和关键子文件夹都存在，可直接使用。
2. **无四层结构**：询问是否创建推荐结构。
3. **已有类似结构**：请求用户映射四层角色，不强行重命名。
4. **部分缺失**：列出缺失项，询问是否只补齐缺失文件夹。

## 标准四层角色

| Key | 角色 | 标准名称 |
|---|---|---|
| `inbox` | 输入层 | `第一层：输入层 (Inbox)` |
| `distilled` | 蒸馏层 | `第二层：蒸馏层 (Distilled)` |
| `skills` | 技能层 | `第三层：技能层 (Skills)` |
| `output` | 输出层 | `第四层：输出层 (Output)` |

## 标准子文件夹角色

| Key | 角色 | 标准相对路径 |
|---|---|---|
| `ideas` | 想法/灵感输入 | `第一层：输入层 (Inbox)/想法/灵感集` |
| `clippings` | 外部抓取输入 | `第一层：输入层 (Inbox)/Clippings` |
| `dailyDistill` | 每日蒸馏报告 | `第二层：蒸馏层 (Distilled)/每日蒸馏` |
| `weeklyReview` | 每周复盘报告 | `第二层：蒸馏层 (Distilled)/每周复盘` |
| `ideaTracking` | 想法追踪 | `第二层：蒸馏层 (Distilled)/想法追踪` |
| `clippingRefine` | Clippings 提炼 | `第二层：蒸馏层 (Distilled)/Clippings提炼` |
| `skillDrafts` | Skill 候选草稿（由 `skill_detector.py` 写入） | `第三层：技能层 (Skills)/_drafts` |
| `published` | 已发表内容（由 `feedback_loop.py` 读取） | `第四层：输出层 (Output)/已发表` |

## Windows 注意事项

- 中文路径可用。
- 中文全角冒号 `：` 可用。
- 英文半角冒号 `:` 不能用于文件夹名。
- 建议使用 PowerShell / Windows Terminal。
- Python 命令可能是 `python`，不一定是 `python3`。

## 安全边界

- 不把这个配置文件当成公开模板上传到共享 Skill 包。
- 不在未确认时覆盖用户已有配置。
- 不自动删除无效路径；先报告并让用户确认。
- 不把用户私人绝对路径写进公开文档或共享示例。
