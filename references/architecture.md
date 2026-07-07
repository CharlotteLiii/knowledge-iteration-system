# 四层架构详细说明

## 概述

基于 Karpathy 知识库理念打造的四层知识蒸馏系统。

```
第一层：输入层 (Inbox)      ← 粗放输入，不整理
第二层：蒸馏层 (Distilled)   ← AI 自动提炼
第三层：技能层 (Skills)      ← 可复用方法论和工作流
第四层：输出层 (Output)      ← 发布 + 回流
```

## 第一层：输入层 (Inbox)

**原则：输入时不整理，整理时不输入。**

```
📁 第一层：输入层 (Inbox)
 ├── 想法/灵感集      ← 随机想法、梦境、灵感
 └── Clippings/       ← 外部抓取（小红书、文章、视频）
     └── 小红书笔记抓取
```

- 有想法就丢进去，不管格式
- 看到好内容就存入 Clippings，不用整理
- 不需要分类、不需要标签
- 后续由蒸馏层自动处理

## 第二层：蒸馏层 (Distilled)

**原则：蒸馏优先于归档。把信息炼出来，不是放整齐。**

```
📁 第二层：蒸馏层 (Distilled)
 ├── 每日蒸馏/         ← daily_distill.py 产出（增量 checkpoint）
 ├── 每周复盘/         ← weekly_review.py 产出（增量 checkpoint）
 ├── 想法追踪/         ← idea_tracker.py 产出
 ├── Clippings提炼/    ← clipping_refiner.py 产出
 ├── 结构性链接建议/  ← link_suggester.py 产出
 ├── 输入层分类目录.md ← kis_catalog.py 产出（多标签分类双视图）
 └── 输出回流分析.md  ← feedback_loop.py 产出
```

每次蒸馏都应该回答：
- 真正有价值的观点是什么？
- 有没有可迁移的原则？
- 能不能变成方法论？
- 能不能变成输出选题？
- 能不能变成 Skill？

## 第三层：技能层 (Skills)

**原则：Skills 不是普通笔记，不能什么都收。**

准入标准（全部满足才进入候选）：
- 可重复使用
- 有明确输入和输出
- 有步骤
- 有判断标准
- 能服务未来任务
- 不只是一次性观点

Skill 类型分类：
- A. 工具型：调用工具或 API
- B. 工作流型：完成重复流程
- C. 判断型：评估、打分、诊断、选择
- D. 创作型：生成某类内容或设计结果
- E. 知识型：处理某个知识领域或方法论

## 第四层：输出层 (Output)

**原则：输出不是终点，是回流入口。**

```
📁 第四层：输出层 (Output)
 └── 已发表/           ← 发布到各平台的内容
```

回流闭环：
```
发布内容 → 反馈分析 → 经验总结 → 方法论更新 → 新 Skill / 新输出策略
```

## 横切子系统（v0.4）

除四层外，v0.4 引入三个横切能力，由辅助模块支撑（不单独运行，被工作流脚本调用）。

### 配置化 taxonomy（`kis_config.py` + `taxonomy.default.json`）

分类维度、类型简写、标签规则、主题、桥接规则等全部外置到 taxonomy：
- 默认取 `scripts/taxonomy.default.json`；用户可在 `<vault>/taxonomy.json` 覆盖。
- 合并策略：默认**深合并**；顶层 `_replace:[段名]` 列出的段做**整段替换**（用于彻底重定义分类、不残留默认旧类）。
- 消费方：`clipping_refiner`（类型/标签）、`link_suggester`（主题/桥接）、`kis_classifier`（分类 key）。
- onboarding：`kis_onboard.py` 非阻塞引导用户声明分类，校验后深合并落盘。

### 增量 checkpoint（`kis_state.py`）

`daily_distill` / `weekly_review` 默认只处理增量：
- 状态存 `<vault>/.kis_state.json`，日/周各自独立 task key。
- 判据：mtime 快筛 + 内容 hash 兜底（对抗云盘刷新 mtime 的误判）。
- 漏跑自动补扫、连跑不重叠（成功后才推进 checkpoint）；任何异常降级为「全部当增量」，绝不阻塞。
- `--days/--since` 手动时间窗覆盖（不读写 checkpoint）；`--reset-checkpoint` 清状态。

### 输入层分类目录（`kis_classifier.py` + `kis_catalog.py`）

每日蒸馏时对输入层内容做**多标签分类**：
- 复用 `taxonomy.contentTypes` 的 key，不另造分类表；一篇可属多类。
- 后端：KeywordClassifier（默认、离线）/ LLMClassifier（opt-in、降级安全、只能提议不能改 taxonomy）。
- 精准阈值：命中 ≥ `taxonomy.classify.minKeywordHits` 才打标签；无分类达阈取最强单类兜底。
- 数据源 `catalog.json`（唯一真相，累积全量）→ 渲染 `输入层分类目录.md`（按分类看 / 按文档看双视图）。
- 零命中或 LLM 提议新类 → 写待审队列 `.kis_pending_categories.json`，由 agent 异步处理，**脚本不阻塞问用户**。


发布后统一记录：标题、平台、时间、来源知识资产、表现数据、用户反馈、可复用经验。
