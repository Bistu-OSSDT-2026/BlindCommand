# BlindCommand 团队分工与协作流程

> **版本**: v1.0  
> **团队规模**: 5 人  
> **开发模式**: Vibe Coding（AI 辅助生成 + 人工审核）  
> **架构原则**: 底层数据层 → 战斗逻辑层 → UI 表现层，事件总线通信，互不侵入  
> **最后更新**: 2026-07-07

---

## 目录

1. [总体架构](#1-总体架构)
2. [Phase 0：接口契约联合定义（全员参与，并行前必做）](#2-phase-0接口契约联合定义)
3. [五人角色与职责](#3-五人角色与职责)
4. [并行任务表](#4-并行任务表)
5. [代码隔离规则](#5-代码隔离规则)
6. [集成节奏与 Checkpoint](#6-集成节奏与-checkpoint)
7. [自动化测试要求](#7-自动化测试要求)
8. [开发时间线](#8-开发时间线)
9. [风险清单与应急预案](#9-风险清单与应急预案)

---

## 1. 总体架构

### 1.1 三层隔离模型

```
┌─────────────────────────────────────────────────┐
│              UI 表现层（#4 负责）                  │
│  地图渲染 · 标记拖拽 · 战报面板 · 迷雾视觉效果     │
│                     ↕                            │
│          只通过事件总线监听，不读写游戏数据          │
└──────────────────────┬──────────────────────────┘
                       │  事件总线（EventBus）
┌──────────────────────┴──────────────────────────┐
│           战斗业务层（#3 负责）                    │
│  兵种子类 · 对战结算 · 指令系统 · 通信延迟         │
│                     ↕                            │
│         只调用底层接口，不修改底层源码               │
└──────────────────────┬──────────────────────────┘
                       │  接口调用
┌──────────────────────┴──────────────────────────┐
│           底层数据层（#2 负责）                    │
│  主循环 · 地图管理 · Unit基类 · 范围检索 · 迷雾计算  │
└─────────────────────────────────────────────────┘
```

### 1.2 事件总线通信模式

```
#3 业务层（事件生产者）          #4 UI层（事件消费者）
┌──────────────┐               ┌──────────────┐
│ 战斗结算完成  │ ──广播──▶     │ 战报面板更新  │
│ 单位阵亡     │ ──广播──▶     │ 阵亡提示显示  │
│ 遭遇敌军     │ ──广播──▶     │ 遇敌文本打印  │
│ 占领指挥所   │ ──广播──▶     │ 胜利画面切换  │
│ 指令已发出   │ ──广播──▶     │ 指令状态提示  │
│ 位置汇报     │ ──广播──▶     │ 迷雾区域更新  │
└──────────────┘               └──────────────┘
```

---

## 2. Phase 0：接口契约联合定义

> **⚠️ 这是并行开发的前提条件，必须五人在编码开始前共同完成。**

### 2.1 目标

产出一份**共享骨架代码**，作为所有开发人员的唯一事实来源。此后任何人修改接口文件，必须全员知晓并同步更新。

### 2.2 产出物

| 文件 | 内容 | 负责人 |
|------|------|:------:|
| `src/core/types.py` | 公共类型定义：坐标、阵营枚举、兵种枚举、地形枚举 | #1 起草 → 全员确认 |
| `src/core/events.py` | 所有事件枚举 + 事件数据类（payload 格式） | #1 起草 → #2 #3 #4 补充 |
| `src/core/interfaces.py` | 所有抽象基类：Unit 接口、Map 接口、Commander 接口 | #1 起草 → #2 #3 确认 |
| `data/unit_config.json` | 兵种数值配置（血量、攻击、防御、速度、射程、视野） | #1 产出 |
| `data/map_01.json` | 第一张测试地图数据 | #1 产出 |
| `pyproject.toml` | 项目配置：依赖、格式化规则（black/isort）、Python 版本 | #5 产出 |
| `.pre-commit-config.yaml` | pre-commit hook：自动格式化 + 基础 lint | #5 产出 |
| `.gitignore` | Git 忽略规则 | #5 产出 |

### 2.3 关键接口契约

#### 2.3.1 范围检索接口（#2 对外暴露，#3 调用）

```python
# src/core/interfaces.py

def get_units_in_range(
    center_x: int,
    center_y: int,
    radius: int,
    faction: Faction | None = None
) -> list[Unit]:
    """
    以 (center_x, center_y) 为中心，radius 为半径，检索范围内的单位。
    
    Args:
        center_x, center_y: 检索中心坐标
        radius: 检索半径（格数），1 表示八邻域
        faction: 若指定，只返回该阵营的单位；若为 None，返回全部单位
    
    Returns:
        范围内的单位列表（按距离排序）
    """
    ...
```

> **注意**：原方案中的"八邻域检索"已改为通用的"范围检索"，以支持炮兵（攻击范围 3）和侦察兵（视野 6）。

#### 2.3.2 迷雾可见性接口（#2 对外暴露，#4 调用）

```python
def is_visible_to_faction(unit: Unit, faction: Faction) -> bool:
    """
    判断 unit 是否对 faction 阵营可见。
    若 unit 在 faction 任一单位的视野范围内，则返回 True。
    """
    ...
```

> **注意**：迷雾**计算逻辑**归属 #2（底层数据层），#4（UI 层）只负责调用接口获取可见性，然后决定"怎么显示"。

#### 2.3.3 事件定义（#3 广播，#4 监听）

```python
# src/core/events.py

from dataclasses import dataclass
from enum import Enum, auto

class GameEventType(Enum):
    """游戏事件类型枚举"""
    BATTLE_RESULT   = auto()   # 战斗结算
    UNIT_KILLED     = auto()   # 单位阵亡
    ENEMY_SPOTTED   = auto()   # 发现敌军
    HQ_CAPTURED     = auto()   # 指挥所被占领
    COMMAND_SENT    = auto()   # 指令已发出
    POSITION_REPORT = auto()   # 友军位置汇报
    GAME_OVER       = auto()   # 游戏结束
    TURN_START      = auto()   # 回合开始

@dataclass
class BattleResultEvent:
    """战斗结算事件"""
    turn: int
    attacker_name: str
    defender_name: str
    attacker_hp_after: int
    defender_hp_after: int
    attacker_killed: bool
    defender_killed: bool
    location: tuple[int, int]

@dataclass
class UnitKilledEvent:
    """单位阵亡事件"""
    turn: int
    unit_name: str
    faction: str              # "FRIENDLY" | "ENEMY"
    approximate_location: tuple[int, int]
    killer_name: str

@dataclass
class EnemySpottedEvent:
    """发现敌军事件"""
    turn: int
    reporter_name: str
    enemy_type: str
    enemy_count: int
    location: tuple[int, int]

@dataclass
class HqCapturedEvent:
    """指挥所被占领事件"""
    turn: int
    capturer_name: str
    capturer_faction: str
    hq_location: tuple[int, int]

@dataclass
class PositionReportEvent:
    """友军位置汇报事件（带误差）"""
    turn: int
    unit_name: str
    reported_x: int           # 汇报坐标（有误差）
    reported_y: int
    actual_x: int             # 真实坐标（仅用于调试，UI 不可见）
    actual_y: int

@dataclass
class GameOverEvent:
    """游戏结束事件"""
    turn: int
    result: str               # "VICTORY" | "DEFEAT" | "DRAW"
    reason: str               # "全歼敌军" | "占领指挥所" | "全军覆没" | "指挥所沦陷" | "回合上限"
```

---

## 3. 五人角色与职责

### #1：总策划 & 规则总负责人

| 职责 | 产出物 |
|------|--------|
| 定义二维地图数组结构、坐标规则、地形编码 | `data/map_01.json` |
| 设计 Unit 基类属性、兵种差异化数值 | `data/unit_config.json` |
| 定稿玩家预设指令集（7 条），写明每条执行逻辑 | 指令规则文档 |
| 制定迷雾规则：大致方位汇报、标记类型区分 | 迷雾规则文档 |
| 枚举所有战报事件：文本模板 + 触发条件 | 战报事件清单 |
| 统一代码规范、类结构、命名格式 | `STYLE_GUIDE.md` |
| 制作全队统一 Vibe Coding Prompt 模板 | `PROMPTS.md` |
| **Phase 0 骨架代码起草** | `types.py` `events.py` `interfaces.py` |
| 迭代需求整理为自然语言描述，下发给开发人员 | 需求 Issue |

### #2：底层架构 Vibe 程序员

| 模块 | 具体内容 | 对外接口 |
|------|----------|----------|
| 游戏主循环 | 8 阶段时序框架：地图更新 → 敌情检测 → 战斗结算 → UI 刷新 | `GameLoop.run()` |
| 地图管理 | 二维数组读写、格子占用、越界判断、指挥所标记 | `Map.get_terrain()` `Map.is_occupied()` |
| Unit 基类 | 血量、攻击力、坐标、受伤、销毁、虚函数 | `Unit` 抽象基类 |
| 范围检索 | 任意半径范围内单位检索（替代八邻域） | `get_units_in_range()` |
| 迷雾计算 | 视野判定、可见性查询 | `is_visible_to_faction()` |
| 事件总线 | 全局事件注册、广播、订阅 | `EventBus.subscribe()` `EventBus.emit()` |

**约束**：只对外暴露接口，禁止上层修改底层源码。

### #3：战斗业务 Vibe 程序员

| 模块 | 具体内容 | 依赖 |
|------|----------|:----:|
| 兵种子类 | 基于 Unit 继承：Infantry、Cavalry、Artillery、Scout、HQ | #2 Unit 基类 |
| 单位实例管理 | 创建、销毁、属性查询、坐标绑定 | #2 Unit 基类 |
| 对战结算 | 伤害公式：`max(1, atk - def) × 克制倍率`，胜者保留、败者销毁 | #2 get_units_in_range() |
| 指令系统 | MOVE/ATTACK/HOLD/SCOUT/RETREAT/CAPTURE/PATROL 解析与执行 | #2 Map 接口 |
| 通信延迟 | 指令传达队列，1~3 回合延迟后分配给友军 | — |
| 事件广播 | 战斗/阵亡/遇敌/占领/胜利时调用 EventBus.emit() | #2 EventBus |
| 测试实例 | 批量生成对局初始兵力配置 | — |

**约束**：只调用 #2 接口，只向 EventBus 广播事件，不修改底层源码，不直接操作 UI。

### #4：UI 与可视化 Vibe 程序员

| 模块 | 具体内容 | 依赖 |
|------|----------|:----:|
| 地图渲染 | 根据二维数组渲染地形图片 + 单位方块 | #2 Map 接口 |
| 标记系统 | 鼠标拖动方块、吸附格子、友军/敌军两种样式、放置/删除 | — |
| 战报面板 | 左侧滚动文本框、追加消息、自动滚动、历史保留 | #2 EventBus |
| 迷雾视觉 | 调用 #2 可见性接口，模糊显示不可见区域 | #2 is_visible_to_faction() |
| 指令面板 | 底部指令选择 UI、参数输入、执行按钮 | — |
| 事件监听 | 订阅 EventBus，事件到达时更新 UI | #2 EventBus |

**约束**：只订阅 EventBus + 调用 #2 可见性查询，完全不修改游戏数据，不直接操作 Unit 实例。

### #5：工程整合 & 资源全栈专员

| 阶段 | 具体内容 |
|------|----------|
| Phase 0 | 搭建 Git 仓库、目录结构、`pyproject.toml`、`.gitignore`、pre-commit hook |
| 开发中 | 每 2 天一次集成 Checkpoint，合并 #2 #3 #4 代码 |
| 开发中 | AI 自动格式化、精简冗余代码、解决简单合并冲突 |
| 开发中 | 美术素材规范化：批量裁剪、重命名、格式转换 |
| 开发中 | 持续维护 CI 脚本（格式化检查 + 基础测试） |
| 收尾 | 一键启动脚本、一键打包脚本 |
| 收尾 | 整体联调：打通 底层→业务→UI 全数据流 |
| 收尾 | 收集工程报错，配合 AI 定位修复 |

---

## 4. 并行任务表

> 以下任务在 Phase 0 骨架代码产出后，可以**同步开展**。

| 时间段 | #1 策划 | #2 底层 | #3 业务 | #4 UI | #5 工程 |
|:------:|---------|---------|---------|-------|---------|
| **Phase 0** (Day 1-2) | 起草骨架代码 + 数值表 | 参与接口确认 | 参与接口确认 | 参与事件定义 | 搭工程环境 |
| **Sprint 1** (Day 3-7) | 完善指令细则 + Prompt 模板 | 主循环 + Map + Unit基类 + 范围检索 | 兵种子类 + 对战结算 | 战报面板 + 地图渲染 | 资源规范 + pre-commit |
| **Checkpoint 1** (Day 8) | 验收规则实现 | 提交底层 SDK v0.1 | 提交业务层 v0.1 | 提交 UI 原型 | **整合 + 跑通流程** |
| **Sprint 2** (Day 9-14) | 边界规则补充 + 战报文本定稿 | 事件总线 + 迷雾计算 | 指令系统 + 通信延迟 + 事件广播 | 标记拖拽 + 迷雾视觉 + 指令面板 | 素材处理 + CI 脚本 |
| **Checkpoint 2** (Day 15) | 验收 | 提交 SDK v0.2 | 提交业务层 v0.2 | 提交 UI v0.2 | **整合 + 跑通完整对局** |
| **Sprint 3** (Day 16-20) | 数值平衡调优 | Bug 修复 + 性能优化 | Bug 修复 + AI 增强 | Bug 修复 + 视觉打磨 | 打包脚本 + 文档 |
| **发布** (Day 21) | 发布说明 | — | — | — | **v1.0 打包发布** |

---

## 5. 代码隔离规则

### 5.1 分层隔离

```
规则 1: #2 底层代码只对外暴露接口（interfaces.py 中定义），内部实现可自由修改
规则 2: #3 业务层只调用 #2 的公开接口，禁止 import 底层私有模块
规则 3: #4 UI 层只订阅 EventBus 和调用 #2 的查询接口，禁止读写任何游戏数据
规则 4: 三方代码中若出现跨层 import，pre-commit hook 直接拦截
```

### 5.2 依赖方向

```
#4 UI 层 ──依赖──▶ EventBus + 可见性查询接口
                        ▲
#3 业务层 ──依赖──▶ #2 公开接口 + EventBus（生产者）
                        ▲
#2 底层 ──无依赖──▶ （独立）
```

**依赖是单向的，循环依赖绝对禁止。**

### 5.3 目录结构约束

```
src/
├── core/                        # 仅 #2 有写入权限
│   ├── __init__.py
│   ├── types.py                 # Phase 0 产出，全员只读
│   ├── events.py                # Phase 0 产出，全员只读
│   ├── interfaces.py            # Phase 0 产出，全员只读
│   ├── game_loop.py             # #2 负责
│   ├── map.py                   # #2 负责
│   ├── unit_base.py             # #2 负责
│   ├── range_utils.py           # #2 负责
│   ├── fog_of_war.py            # #2 负责（迷雾计算逻辑）
│   └── event_bus.py             # #2 负责
│
├── battle/                      # 仅 #3 有写入权限
│   ├── __init__.py
│   ├── units.py                 # 兵种子类
│   ├── unit_manager.py          # 实例管理
│   ├── battle_system.py         # 对战结算
│   ├── commander.py             # 指令解析
│   ├── command_queue.py         # 通信延迟队列
│   └── ai.py                    # 敌军 AI
│
├── ui/                          # 仅 #4 有写入权限
│   ├── __init__.py
│   ├── main_window.py
│   ├── map_widget.py
│   ├── battle_log.py
│   ├── command_panel.py
│   ├── marker.py
│   └── assets/                  # 仅 #5 有写入权限
│
└── main.py                      # #5 整合组装
```

---

## 6. 集成节奏与 Checkpoint

### 6.1 集成原则

> **❌ 错误做法**：所有人开发完 → 最后一次性拼装 → 必然炸裂  
> **✅ 正确做法**：每 2 天一次小集成 → 早发现问题 → 早修复

### 6.2 Checkpoint 清单

| Checkpoint | 时间 | 集成内容 | 验收标准 |
|:----------:|:----:|----------|----------|
| **CP-0** | Day 2 | 骨架代码 + 工程环境 | `python -c "from src.core.types import Faction"` 不报错 |
| **CP-1** | Day 8 | 底层 SDK + 业务层 + UI 原型 | 命令行跑通一轮：创建地图 → 创建单位 → 战斗结算 → 事件广播 |
| **CP-2** | Day 15 | 完整游戏逻辑 + UI | GUI 跑通完整对局：指令下达 → 延迟到达 → 单位移动 → 遇敌战斗 → 胜利 |
| **CP-3** | Day 20 | 打磨版本 | 无阻断性 bug，性能正常，资源完整 |
| **Release** | Day 21 | 发布版本 | `python main.py` 即可运行，打包产物可分发 |

### 6.3 集成日流程

```
09:00  #2 #3 #4 提交各自代码到分支
10:00  #5 拉取所有分支，合并到 integration 分支
10:30  运行自动化检查（格式化 + 基础测试）
11:00  若检查失败 → 回退 + 通知对应开发修
14:00  若检查通过 → 手动跑一遍完整流程
16:00  锁定当前版本，打 checkpoint tag
17:00  全队同步当前状态，更新各自分支
```

---

## 7. 自动化测试要求

### 7.1 分工自测

| 角色 | 测试内容 | 最少覆盖 |
|:----:|----------|:--------:|
| #2 | 地图读写、越界判断、范围检索正确性、EventBus 广播/订阅 | 5 条 |
| #3 | 对战伤害计算、兵种克制倍率、指令解析、通信延迟队列入队出队 | 8 条 |
| #4 | 无自动化要求（UI 人工验收） | — |
| #5 | 端到端冒烟测试：初始化 → 一回合 → 战斗 → 结束 | 3 条 |

### 7.2 测试文件约定

```
tests/
├── core/                    # #2 负责
│   ├── test_map.py
│   ├── test_range.py
│   └── test_event_bus.py
├── battle/                  # #3 负责
│   ├── test_battle.py
│   ├── test_units.py
│   └── test_commander.py
└── integration/             # #5 负责
    └── test_smoke.py
```

### 7.3 CI 配置（#5 维护）

```yaml
# .github/workflows/check.yml （示例）
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: black --check src/ tests/       # 格式化检查
      - run: isort --check-only src/ tests/  # import 顺序检查
      - run: pytest tests/ -v                 # 运行所有测试
```

---

## 8. 开发时间线

```
Day 1  ████ Phase 0: 接口契约定义 ████
Day 2  ████ Phase 0: 接口契约定义 ████  ← CP-0
Day 3  ▓▓▓▓ Sprint 1: 并行开发 ▓▓▓▓
Day 4  ▓▓▓▓ Sprint 1: 并行开发 ▓▓▓▓
Day 5  ▓▓▓▓ Sprint 1: 并行开发 ▓▓▓▓
Day 6  ▓▓▓▓ Sprint 1: 并行开发 ▓▓▓▓
Day 7  ▓▓▓▓ Sprint 1: 并行开发 ▓▓▓▓
Day 8  ▓▓▓▓ CP-1: 第一次集成 ▓▓▓▓      ← 里程碑：命令行可玩
Day 9  ░░░░ Sprint 2: 并行开发 ░░░░
Day 10 ░░░░ Sprint 2: 并行开发 ░░░░
Day 11 ░░░░ Sprint 2: 并行开发 ░░░░
Day 12 ░░░░ Sprint 2: 并行开发 ░░░░
Day 13 ░░░░ Sprint 2: 并行开发 ░░░░
Day 14 ░░░░ Sprint 2: 并行开发 ░░░░
Day 15 ░░░░ CP-2: 第二次集成 ░░░░      ← 里程碑：GUI 完整可玩
Day 16 ▒▒▒▒ Sprint 3: 打磨优化 ▒▒▒▒
Day 17 ▒▒▒▒ Sprint 3: 打磨优化 ▒▒▒▒
Day 18 ▒▒▒▒ Sprint 3: 打磨优化 ▒▒▒▒
Day 19 ▒▒▒▒ Sprint 3: 打磨优化 ▒▒▒▒
Day 20 ▒▒▒▒ CP-3: 最终检查 ▒▒▒▒
Day 21 ████ v1.0 发布 ████
```

---

## 9. 风险清单与应急预案

| # | 风险 | 概率 | 影响 | 应对措施 |
|:--:|------|:----:|:----:|----------|
| R1 | Phase 0 接口定义不充分，开发中发现遗漏 | 高 | 中 | 接口文件纳入 Git，修改必须 PR + 全员 Review |
| R2 | #5 一次性整合失败，冲突量巨大 | 高 | 高 | **已修复**：改为每 2 天增量集成 |
| R3 | 八邻域范围不够，远程兵种无法实现 | 高 | 高 | **已修复**：改为通用范围检索接口 |
| R4 | 迷雾计算逻辑归属不明，无人负责 | 中 | 高 | **已修复**：明确分配给 #2，接口定义为 `is_visible_to_faction()` |
| R5 | AI 生成代码风格不统一，#5 格式化工作量大 | 高 | 中 | **已修复**：Phase 0 产出 pre-commit hook + black/isort |
| R6 | 通信延迟特色机制无人认领 | 中 | 中 | **已修复**：明确分配给 #3，作为 Commander 子模块 |
| R7 | #1 成为信息瓶颈，开发人员频繁等待答复 | 中 | 中 | #1 产出决策树文档 + 可执行配置文件，减少口头解释 |
| R8 | 对战判定描述矛盾（一击必杀 vs 伤害公式） | 高 | 高 | **已修复**：统一为 DESIGN.md 中的伤害制 |
| R9 | AI 生成代码 bug 多，联调时间远超预期 | 中 | 高 | 要求每人至少写 5 条自动化测试 |
| R10 | 五人 Git 分支管理混乱，合并冲突频发 | 中 | 中 | 严格目录隔离，每人只写自己的目录 |

---

## 附录 A：Vibe Coding 通用 Prompt 模板（#1 维护）

```markdown
## 角色
你是一个 Python 游戏开发专家，正在参与开源项目 BlindCommand。

## 项目背景
BlindCommand 是一款以信息不对称为核心的即时战术指挥游戏。
架构：底层数据层 → 业务逻辑层 → UI 表现层，事件总线通信。

## 项目代码规范
- Python 3.11+，使用类型注解
- 遵循 black 格式化风格（行宽 100）
- 类名 PascalCase，函数名 snake_case，常量 UPPER_SNAKE_CASE
- 所有公共函数必须有 docstring（Google 风格）
- import 顺序：标准库 → 第三方库 → 项目内部（isort 自动处理）

## 本次任务
{具体任务描述}

## 上下文文件
{相关接口/类型/配置文件路径}

## 输出要求
- 只输出完整的 .py 文件内容
- 不修改 src/core/interfaces.py、src/core/types.py、src/core/events.py
- 若需要新增接口，先在回答中说明，不要直接修改接口文件
```

---

## 附录 B：接口变更流程

```
1. 发现接口不满足需求
      │
      ▼
2. 在团队频道提出变更请求（说明原因 + 建议修改内容）
      │
      ▼
3. #1 评估影响范围，决定是否变更
      │
      ▼
4. 若同意：修改 interfaces.py / events.py / types.py → 提交 PR
      │
      ▼
5. 至少 2 名其他成员 Review + Approve
      │
      ▼
6. 合并 → 全员 git pull → 各自适配
```

---

> **本文档与 DESIGN.md 互为补充：DESIGN.md 定义"做什么"，本文档定义"谁来做、怎么做、何时做"。**
