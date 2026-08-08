# 0.9.0 任务追踪功能计划

状态：初始方案，尚未开始功能代码

调研日期：2026-08-03

首选数据源：`https://json.tarkov.dev`

## 目标

在不读取游戏内存、不注入游戏进程、不自动操作游戏的前提下，为 PvE 和 PvP/Regular 分别提供离线可用的任务浏览、手动进度记录和局内物品需求提示。

`0.9.0` 的第一版应解决三个核心问题：

1. 玩家当前有哪些任务可接、进行中或已完成。
2. 每个任务有哪些目标、地图、前置条件和失败分支。
3. 查到一个物品时，它是否仍被进行中的任务需要，以及需要多少、是否要求战局中找到。

## 已验证的数据源结论

### 为什么优先 JSON API

- 项目现有价格与配方更新已经使用 `json.tarkov.dev`，可以复用 HTTP、ETag、缓存和失败保护方式。
- JSON 快照适合在发布时生成紧凑的 `data/tasks.json`，应用运行时不必联网。
- 2026-08-03 实测 JSON 任务端点返回 HTTP 200；同一时段 GraphQL 返回 `GraphQL server unavailable. Try again later.`。
- GraphQL schema 仍可用于理解完整字段语义，但不作为 `0.9.0` 的运行时依赖。

### 快照规模与模式差异

| 模式 | 任务数 | 响应大小 | 有前置任务 | 仅该模式存在 |
|---|---:|---:|---:|---:|
| PvE | 506 | 2,138,704 bytes | 484 | 23 |
| Regular/PvP | 510 | 2,204,259 bytes | 485 | 27 |

两个模式共有 483 个相同任务 ID，但并非同一张任务表，因此任务快照和玩家进度都必须按模式隔离，不能只存一份全局完成状态。

两个模式中均存在：

- `Any`、`BEAR`、`USEC` 阵营限制；
- 前置状态 `active`、`complete`、`failed`；
- 38 个带失败条件的任务；
- 16 个可重启任务；
- 257 个 Kappa 相关任务；
- 7 个 Lightkeeper 相关任务。

### JSON 文档结构

`/{mode}/tasks` 顶层包含 `data` 与 `translations`。`data` 当前包含：

- `tasks`：以任务 ID 为键的对象；
- `questItems`：任务专用物品；
- `achievements`：奖励可能引用的成就；
- `prestige`：声望/重生系统关联数据。

任务本体采用规范化 ID 引用。商人、地图、前置任务、普通物品和奖励物品通常不是展开对象，而是对应资源的 ID。名称和目标说明是翻译键，需要用 `tasks_en`、`tasks_zh` 的 `data` 字典还原。

简化后的真实形态如下：

```json
{
  "data": {
    "tasks": {
      "<task-id>": {
        "id": "<task-id>",
        "name": "<task-name-translation-key>",
        "normalizedName": "first-in-line",
        "gameMode": "pve",
        "trader": "<trader-id>",
        "map": "<map-id-or-null>",
        "minPlayerLevel": 1,
        "factionName": "Any",
        "taskRequirements": [
          {"task": "<prerequisite-task-id>", "status": ["complete"]}
        ],
        "objectives": [
          {
            "id": "<objective-id>",
            "description": "<objective-translation-key>",
            "type": "giveItem",
            "count": 3,
            "items": ["<item-id>"],
            "foundInRaid": true,
            "optional": false
          }
        ],
        "finishRewards": {
          "items": [{"item": "<item-id>", "count": 1}],
          "traderStanding": [
            {"trader": "<trader-id>", "standing": 0.01}
          ]
        }
      }
    }
  }
}
```

不能把 JSON 当成 GraphQL 展开结果直接使用；构建发布快照时需要显式完成 ID 关联与翻译键解析。

### 任务字段

当前任务记录可查询到：

- 身份与显示：`id`、`name`、`normalizedName`、`taskImageLink`、`wikiLink`；
- 分类：`gameMode`、`factionName`、`trader`、`map`；
- 解锁：`minPlayerLevel`、`taskRequirements`、`traderRequirements`、`otherRequirements`、可用延迟范围；
- 过程：`objectives`、`failConditions`、`restartable`、`neededKeys`；
- 奖励/后果：`startRewards`、`finishRewards`、`failureOutcome`、`experience`；
- 长线标记：`kappaRequired`、`lightkeeperRequired`。

### 目标类型

PvE 快照的 506 个任务包含 1,465 个主目标。当前类型及数量为：

| 类型 | 数量 | 第一版处理方式 |
|---|---:|---|
| `giveItem` | 281 | 物品需求与手动数量 |
| `visit` | 210 | 手动完成 |
| `shoot` | 194 | 手动数量；展示武器、距离、部位等限制 |
| `findItem` | 152 | 物品需求与手动数量 |
| `plantItem` | 126 | 物品需求与手动数量 |
| `findQuestItem` | 114 | 展示任务物品与可能位置 |
| `giveQuestItem` | 103 | 手动数量 |
| `mark` | 99 | 展示标记物、地图与所需钥匙 |
| `extract` | 97 | 手动数量；展示撤离状态 |
| `buildWeapon` | 30 | 展示武器与属性条件 |
| `plantQuestItem` | 13 | 手动数量 |
| `traderLevel` | 10 | 根据用户商人等级或手动完成 |
| `skill` | 10 | 根据用户技能等级或手动完成 |
| `taskStatus` | 9 | 根据本地任务状态推导 |
| `useItem` | 8 | 手动数量 |
| `sellItem` | 5 | 物品需求与手动数量 |
| 其他 4 类 | 各 1 | 通用描述与手动完成 |

未知的新类型不得导致整个快照或 UI 加载失败。应用应保留其 `type` 和本地化 `description`，以通用目标行降级显示，同时在开发日志中记录。

## 0.9.0 产品范围

### 纳入第一版

- 新增可选功能 `task_tracking`，默认仍保持关闭。
- PvE 与 Regular/PvP 独立任务进度。
- 按状态、商人、地图、阵营、Kappa/Lightkeeper 和文本搜索过滤。
- 任务详情显示前置条件、目标、失败条件、经验和主要奖励。
- 用户手动设置任务为未接取、进行中、可交付、已完成或失败。
- 对带 `count` 的目标记录当前数量；无数量目标使用完成复选框。
- 基于本地状态推导锁定/可接任务，完整支持 `active`、`complete`、`failed` 前置状态。
- 局内查价命中物品时，显示进行中任务的剩余数量与 `战局中找到` 要求。
- 数据快照、进度文件和 UI 在断网时完全可用。
- 数据与进度均使用临时文件替换，避免异常退出损坏 JSON。

### 暂不纳入第一版

- 读取游戏日志或联网账号来自动同步任务状态；
- OCR 自动识别任务列表或任务详情；
- 地图上的三维区域/路线可视化；
- 多角色/多存档档案管理；
- 向第三方任务追踪服务写入进度；
- 根据查价结果自动增加目标数量。

物品识别只负责提示，不应擅自修改任务进度。

## 建议架构

### 1. 发布快照生成器

新增 `scripts/update_task_data.py`，生成 `data/tasks.json`：

- 拉取 `pve/tasks`、`regular/tasks` 和中英文翻译字典；
- 解析任务名与目标说明，保留稳定任务/目标 ID；
- 为商人和地图补充中英文显示名；
- 保留目标物品 ID、数量、`foundInRaid` 和关键限制；
- 记录生成时间、源 URL、各端点 ETag、schema version 和两种模式计数；
- 使用临时文件原子替换目标文件。

更新器必须失败关闭：

- 任一模式任务数低于 450 时拒绝覆盖；
- 任务 ID 或目标 ID 缺失、重复时拒绝覆盖；
- 翻译覆盖率异常下降时拒绝覆盖；
- 前置任务引用无法解析时拒绝覆盖；
- 对未知目标类型给出警告，但保留通用描述，不因游戏新增类型而停止发布。

### 2. 本地目录与模型

新增 `app/tasks.py`，职责与现有 `RecipeCatalog`、`HideoutTracker` 分开：

- `TaskCatalog`：只读加载随包快照、建立任务/前置/物品反向索引；
- `TaskProgressStore`：加载、迁移、验证并原子保存用户进度；
- 纯函数：状态推导、目标剩余数量、物品需求汇总和过滤；
- UI 不直接解释原始 JSON。

建议进度文件为 `data/task_progress.json`，不要把几百个任务状态塞进 `config.json`：

```json
{
  "schema_version": 1,
  "modes": {
    "pve": {
      "player_level": null,
      "faction": "Any",
      "tasks": {
        "<task-id>": {
          "status": "active",
          "objectives": {
            "<objective-id>": {"current": 2, "completed": false}
          },
          "updated_at": "2026-08-03T00:00:00Z"
        }
      }
    },
    "regular": {
      "player_level": null,
      "faction": "Any",
      "tasks": {}
    }
  }
}
```

状态枚举建议为：

- `not_started`：默认状态；
- `active`：已接取；
- `ready`：目标已完成、等待交付；
- `complete`：已交付；
- `failed`：失败；
- `locked` 与 `available` 为推导视图状态，不写入文件。

刷新任务快照时只按稳定 ID 合并，不重写用户进度。快照中暂时消失的任务应保留为 orphan 记录并显示诊断信息，不能静默删除。

### 3. UI

主窗口新增“任务追踪”页：

- 左侧：状态、商人、地图与长线目标过滤；
- 中间：任务列表，显示名称、商人、等级、状态和完成度；
- 右侧：前置条件、目标、失败条件和奖励详情；
- 顶部：PvE/PvP 模式、玩家等级、阵营与搜索；
- 操作：开始追踪、标记可交付、完成、失败、重置当前任务。

第一版优先使用现有 `QTreeWidget`/`QSplitter` 交互模式并复用主题、字体、列宽记忆和延迟保存机制；若实测 500 个任务下重建卡顿，再改为 model/view，而不是预先扩大重构范围。

### 4. 查价联动

`TaskCatalog` 建立 `item_id -> active objective` 反向索引。价格识别成功后，在现有价格卡片中追加独立“任务需求”区域，例如：

```text
任务需求
医疗物资短缺：2 / 3，仍需 1（要求战局中找到）
另一个任务：0 / 2，仍需 2
进行中任务合计仍需：3
```

只统计进行中且未完成的目标；奖励物品、已完成任务和仅作为所需钥匙的物品不能混入交付数量。

## 实施顺序

### 阶段 A：数据与纯模型

1. 添加紧凑快照生成器和固定小型测试 fixture。
2. 实现 `TaskCatalog`、索引和未知类型降级。
3. 实现 `TaskProgressStore`、原子写入和 schema 迁移。
4. 实现前置状态与目标完成度的纯函数测试。

### 阶段 B：任务页

1. 添加可选功能开关和任务页骨架。
2. 完成模式/状态/商人/地图/文本过滤。
3. 完成任务详情、状态变更和目标进度编辑。
4. 验证 500+ 任务的启动、筛选与切换性能。

### 阶段 C：局内查价联动

1. 添加任务物品反向索引。
2. 在价格结果卡与日志中显示任务需求。
3. 验证 PvE/PvP 切换不会串用任务状态。
4. 确认提示不会自动改变进度，也不会增加 OCR 或网络请求。

### 阶段 D：发布候选验收

1. 完整单元测试与 `compileall`。
2. 无网启动、损坏进度文件和旧进度迁移测试。
3. 真实 UI 验收：搜索、筛选、状态切换、目标计数、重启保存。
4. 真实局内验收：任务物品/非任务物品、FIR 要求和两种游戏模式。
5. 更新 README、CHANGELOG、发布说明与诊断摘要隐私规则。

## 验收标准

- 发布包断网启动时可浏览全部任务并编辑进度。
- PvE 与 PvP 的 23/27 个模式专属任务及所有用户状态互不污染。
- `active`、`complete`、`failed` 三种前置条件均有 fixture 覆盖。
- 所有已知目标类型可显示；未知类型可降级显示而不崩溃。
- 任务进度写入失败时保留旧文件，不产生半写 JSON。
- 查价提示只使用当前模式、进行中任务和未完成目标。
- 任务快照更新后，已有任务/目标 ID 的进度保持不变。
- 不新增游戏内存读取、注入、输入自动化或后台高频网络轮询。

## 分支边界

任务追踪已顺延到 `0.9.0`。应先完成并发布 `0.8.0` 自动更新基线，再从明确的 `v0.8.0` 基线建立 `codex/task-tracking-0.9` 分支或独立 worktree；不要把任务追踪与自动更新首次发布混在同一变更集中。
