# src/battle/ — 战斗业务层技术规格说明书

> **负责人**: #3 (战斗业务 Vibe 程序员)  
> **版本**: v1.0  
> **依赖**: `src/core/` (只读)  
> **被依赖**: 无（仅通过 EventBus 广播事件给 #4 UI 层）  
> **最后更新**: 2026-07-07

---

## 目录

1. [架构概览](#1-架构概览)
2. [模块清单与依赖关系](#2-模块清单与依赖关系)
3. [units.py — 兵种子类](#3-unitspy--兵种子类)
4. [unit_manager.py — 单位实例管理](#4-unit_managerpy--单位实例管理)
5. [battle_system.py — 对战结算系统](#5-battle_systempy--对战结算系统)
6. [commander.py — 指令解析与执行](#6-commanderpy--指令解析与执行)
7. [command_queue.py — 通信延迟队列](#7-command_queuepy--通信延迟队列)
8. [ai.py — 敌军 AI 决策](#8-aipy--敌军-ai-决策)
9. [事件广播契约](#9-事件广播契约)
10. [测试计划](#10-测试计划)
11. [实现顺序建议](#11-实现顺序建议)

---

## 1. 架构概览

### 1.1 分层定位

```
┌─────────────────────────────────────────┐
│          #4 UI 层 (src/ui/)              │
│         只监听 EventBus                    │
└────────────────┬────────────────────────┘
                 │ EventBus (事件消费)
┌────────────────┴────────────────────────┐
│          #3 业务层 (src/battle/)  ← 本文件 │
│   units.py · battle_system.py            │
│   commander.py · command_queue.py        │
│   unit_manager.py · ai.py                │
│         调用接口 + 广播事件                  │
└────────────────┬────────────────────────┘
                 │ 接口调用
┌────────────────┴────────────────────────┐
│          #2 底层 (src/core/)              │
│   IUnit · IMap · IRangeQuery            │
│   IFogOfWar · EventBus                  │
└─────────────────────────────────────────┘
```

### 1.2 核心约束

| 规则 | 说明 |
|------|------|
| **不修改 `src/core/`** | 所有 Phase 0 骨架文件只读 |
| **只调用公开接口** | 通过 `IUnit`、`IMap`、`IRangeQuery`、`IGameState` 访问底层 |
| **只广播事件** | 通过 `event_bus.emit()` 通知 UI，不直接操作 UI |
| **不 import `src/ui/`** | 跨层 import 被 pre-commit 拦截 |

### 1.3 模块导入白名单

```python
# ✅ 允许的 import
from src.core import (
    # 枚举
    Faction, UnitType, TerrainType, CommandType, Direction,
    GameEventType, GameResult, BattleOutcome,
    # 数据类
    Coordinate, UnitStats, TerrainProps,
    # 接口
    IUnit, IMap, IRangeQuery, ICommander, ICommand, IGameState,
    # 事件载荷
    BattleResultPayload, UnitKilledPayload, UnitDamagedPayload,
    EnemySpottedPayload, HqCapturedPayload, CommandSentPayload,
    CommandArrivedPayload, GameOverPayload, PositionReportPayload,
    # 事件总线
    event_bus,
    # 常量与工具函数
    UNIT_STATS, TYPE_ADVANTAGE, get_advantage_multiplier,
    COMBAT_MIN_DAMAGE, COMBAT_TYPE_ADVANTAGE_MULT,
    COMBAT_COUNTERATTACK_ENABLED, COMBAT_RANGED_FIRST_STRIKE,
    COMBAT_CRITICAL_HP_RATIO, COMBAT_HEALTHY_HP_RATIO,
    COMBAT_ROUT_HP_RATIO, COMBAT_ROUT_CHANCE,
    COMMAND_DELAY_MIN, COMMAND_DELAY_MAX, COMMAND_DELAY_WEIGHTS,
    CAPTURE_REQUIRED_TURNS, CAPTURE_INTERRUPTIBLE,
    MAX_TURNS, MAX_UNITS_PER_FACTION, MAX_UNITS_TOTAL,
)
```

---

## 2. 模块清单与依赖关系

```
src/battle/
├── __init__.py           # 包导出
├── units.py              # [模块 A] 兵种子类
├── unit_manager.py       # [模块 B] 单位实例管理
├── battle_system.py      # [模块 C] 对战结算系统
├── commander.py          # [模块 D] 指令解析与执行
├── command_queue.py      # [模块 E] 通信延迟队列
└── ai.py                 # [模块 F] 敌军 AI 决策
```

### 依赖关系图

```
unit_manager.py ──依赖──▶ units.py
        │
        ▼
battle_system.py ──依赖──▶ units.py + unit_manager.py + IRangeQuery + EventBus
        │
        ▼
command_queue.py ──依赖──▶ (独立，纯数据结构)
        │
        ▼
commander.py ──依赖──▶ command_queue.py + IMap + unit_manager.py + EventBus
        │
        ▼
ai.py ──依赖──▶ commander.py + battle_system.py + unit_manager.py + IRangeQuery
```

---

## 3. units.py — 兵种子类

### 3.1 概述

基于 #2 提供的 `UnitBase`（实现 `IUnit` 接口），创建 5 个兵种子类。
每个子类从 `UNIT_STATS[unit_type]` 读取属性模板，重写 `attack_target()` 实现特殊攻击逻辑。

### 3.2 类层次结构

```
IUnit (src/core/interfaces.py)           ← #2 定义接口
  └── UnitBase (src/core/unit_base.py)   ← #2 实现基础逻辑
        ├── Infantry                      ← #3 实现
        ├── Cavalry                       ← #3 实现
        ├── Artillery                     ← #3 实现
        ├── Scout                         ← #3 实现
        └── HQ                            ← #3 实现
```

### 3.3 各兵种规格

#### 3.3.1 Infantry（步兵）

| 属性 | 值 | 来源 |
|------|:--:|------|
| unit_type | `UnitType.INFANTRY` | — |
| max_hp | 10 | `UNIT_STATS[INFANTRY]` |
| attack | 3 | 同上 |
| defense | 2 | 同上 |
| speed | 3 | 同上 |
| attack_range | 1 | 同上 |
| vision_range | 3 | 同上 |
| strong_against | `(Cavalry,)` | 同上 |

**特殊行为**: 无。标准近战，攻击范围内相邻格敌人。

**`attack_target()` 实现**:
```python
def attack_target(self, target: IUnit) -> int:
    """步兵标准近战攻击。"""
    damage = calculate_damage(self, target)  # 调用 battle_system 的公式
    target.take_damage(damage, self)
    return damage
```

#### 3.3.2 Cavalry（骑兵）

| 属性 | 值 |
|------|:--:|
| max_hp | 8 |
| attack | 4 |
| defense | 1 |
| speed | 6 |
| attack_range | 1 |
| vision_range | 4 |
| strong_against | `(Artillery,)` |

**特殊行为**: 高速移动（speed=6，全兵种最快）。标准近战攻击。

#### 3.3.3 Artillery（炮兵）

| 属性 | 值 |
|------|:--:|
| max_hp | 6 |
| attack | 5 |
| defense | 1 |
| speed | 1 |
| attack_range | 3 |
| vision_range | 2 |
| strong_against | `(Infantry,)` |

**特殊行为**: 
- **远程先手** (`COMBAT_RANGED_FIRST_STRIKE = True`): 炮兵在攻击范围内（>1格）先手攻击，被攻击者无法反击
- **相邻被攻时无特殊**: 敌人在相邻格攻击炮兵时，正常结算（炮兵毕竟远程，近战劣势已体现在低防御上）

**`attack_target()` 实现**:
```python
def attack_target(self, target: IUnit) -> int:
    """炮兵远程攻击，射程外先手无反击。"""
    dist = self.position.chebyshev_distance(target.position)
    damage = calculate_damage(self, target)
    target.take_damage(damage, self)
    # 远程攻击（距离 > 1）: 不触发反击
    # 此逻辑由 battle_system 根据 COMBAT_RANGED_FIRST_STRIKE 控制
    return damage
```

#### 3.3.4 Scout（侦察兵）

| 属性 | 值 |
|------|:--:|
| max_hp | 5 |
| attack | 1 |
| defense | 1 |
| speed | 5 |
| attack_range | 1 |
| vision_range | 6 |
| strong_against | `()` 无克制 |

**特殊行为**: 
- **视野最大** (vision_range=6): 用于扩大可探测范围
- 战斗力弱，主要用于侦察
- 无兵种克制

#### 3.3.5 HQ（指挥所）

| 属性 | 值 |
|------|:--:|
| max_hp | 30 |
| attack | 0 |
| defense | 3 |
| speed | 0 |
| attack_range | 0 |
| vision_range | 0 |
| strong_against | `()` |
| is_hq | True |
| capture_turns | 2 |

**特殊行为**:
- **不可移动** (speed=0): `move_to()` 始终返回 False
- **不可攻击** (attack_range=0): `can_attack()` 始终返回 False，`attack_target()` 抛出 ValueError
- **可被占领**: 敌军步兵在 HQ 格停留 `CAPTURE_REQUIRED_TURNS` (2) 回合即占领

### 3.4 单位初始化流程

```python
class Infantry(UnitBase):
    def __init__(self, unit_id: str, name: str, faction: Faction,
                 start_pos: Coordinate) -> None:
        stats = UNIT_STATS[UnitType.INFANTRY]
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.INFANTRY,
            position=start_pos,
            max_hp=stats.max_hp,
            attack=stats.attack,
            defense=stats.defense,
            speed=stats.speed,
            attack_range=stats.attack_range,
            vision_range=stats.vision_range,
        )
```

### 3.5 `get_state_report()` 规格

每种兵种返回格式统一的战报文本：

```python
def get_state_report(self) -> str:
    """生成单位状态报告。"""
    hp_ratio = self.current_hp / self.max_hp
    if not self.is_alive:
        return f"{self.name}已阵亡"
    if hp_ratio >= COMBAT_HEALTHY_HP_RATIO:
        status = "状态良好"
    elif hp_ratio >= COMBAT_CRITICAL_HP_RATIO:
        status = "轻微受损"
    else:
        status = "损失惨重"
    return f"{self.name}({UNIT_DISPLAY_NAMES[self.unit_type]}) HP:{self.current_hp}/{self.max_hp} [{status}]"
```

---

## 4. unit_manager.py — 单位实例管理

### 4.1 概述

负责单位的创建、销毁、查询、统计。是 battle 层与 #2 底层之间的"单位注册中心"。

### 4.2 类: `UnitManager`

```python
class UnitManager:
    """单位实例管理器。

    职责:
    - 工厂方法创建 5 种兵种实例
    - 按 ID / 阵营 / 兵种 / 坐标查询
    - 销毁单位（更新地图 + 广播事件）
    - 统计存活数量
    """

    def __init__(self, game_map: IMap) -> None:
        ...

    # ── 工厂方法 ────────────────────────────────────────────────
    def create_unit(self, unit_type: UnitType, unit_id: str, name: str,
                    faction: Faction, position: Coordinate) -> IUnit:
        """根据兵种类型创建对应子类实例，并放置到地图上。"""

    def create_units_from_config(self, config_list: list[dict],
                                  faction: Faction) -> list[IUnit]:
        """从 map_01.json 的 friendly_units / enemy_units 批量创建。"""

    # ── 查询方法 ────────────────────────────────────────────────
    def get_unit_by_id(self, unit_id: str) -> IUnit | None:
        """按 ID 查找。"""

    def get_units_by_faction(self, faction: Faction) -> list[IUnit]:
        """获取某阵营所有存活单位。"""

    def get_alive_units(self) -> list[IUnit]:
        """获取所有存活单位。"""

    def get_units_by_type(self, unit_type: UnitType,
                          faction: Faction | None = None) -> list[IUnit]:
        """按兵种筛选。"""

    # ── 销毁方法 ────────────────────────────────────────────────
    def kill_unit(self, unit: IUnit, killer: IUnit,
                  current_turn: int) -> None:
        """销毁单位: 标记阵亡 + 从地图移除 + 广播 UNIT_KILLED 事件。"""

    # ── 统计方法 ────────────────────────────────────────────────
    def count_alive_by_faction(self, faction: Faction) -> int:
        """某阵营存活数。"""

    def check_all_eliminated(self, faction: Faction) -> bool:
        """某阵营是否全军覆没。"""

    # ── HQ 相关 ─────────────────────────────────────────────────
    def get_hq(self, faction: Faction) -> IUnit | None:
        """获取某阵营指挥所。"""

    def is_hq_alive(self, faction: Faction) -> bool:
        """指挥所是否存活。"""
```

### 4.3 关键逻辑

**`kill_unit()` 流程:**
```
1. unit.is_alive = False
2. game_map.remove_unit(unit)
3. 清理该单位的待执行指令 (commander.cancel_all_commands(unit.unit_id))
4. 广播 UNIT_KILLED 事件:
   event_bus.emit(GameEventType.UNIT_KILLED, UnitKilledPayload(
       turn=current_turn,
       unit_id=unit.unit_id,
       unit_name=unit.name,
       unit_type=unit.unit_type.value,
       faction=unit.faction.value,
       killer_id=killer.unit_id,
       killer_name=killer.name,
       actual_x=unit.position.x,
       actual_y=unit.position.y,
       reported_x=...,  # 对友军带误差，对敌军精确
       reported_y=...,
   ))
```

---

## 5. battle_system.py — 对战结算系统

### 5.1 概述

战斗系统的核心。由游戏主循环在"对战阶段"调用，处理所有敌对单位之间的战斗结算。

### 5.2 纯函数: `calculate_damage()`

```python
def calculate_damage(attacker: IUnit, defender: IUnit) -> int:
    """计算攻击方对防御方造成的实际伤害。

    伤害公式:
        raw = attacker.attack - defender.defense
        raw = max(COMBAT_MIN_DAMAGE, raw)   # 最小伤害 = 1
        multiplier = get_advantage_multiplier(attacker.unit_type, defender.unit_type)
        damage = int(raw * multiplier)

    注意: defender.defense 已含地形加成（per IUnit 接口契约）。
    调用方应在调用前通过 Unit.terrain_defense_bonus 确保防御力反映当前地形。

    Args:
        attacker: 攻击方
        defender: 防御方（defense 属性须已包含地形加成）

    Returns:
        实际伤害值 (int, >= 1)
    """
```

**计算示例**:
```
骑兵(攻4) vs 炮兵(防1) 在平原(加成0):
  raw = max(1, 4 - (1+0)) = 3
  multiplier = 1.5 (骑克炮)
  damage = int(3 * 1.5) = 4

炮兵 HP: 6 → 2 (存活)
```

### 5.3 类: `BattleSystem`

```python
class BattleSystem:
    """对战结算系统。

    由主循环在"对战阶段"调用 process_all_battles()。
    """

    def __init__(self, unit_manager: UnitManager,
                 range_query: IRangeQuery,
                 game_map: IMap) -> None:
        ...

    # ── 主入口 ──────────────────────────────────────────────────
    def process_all_battles(self, current_turn: int) -> list[BattleResultPayload]:
        """处理所有敌对单位相遇的战斗。

        遍历所有存活单位，对每对相邻敌对单位结算战斗。
        返回本回合所有战斗结果（供主循环做胜利判定）。
        """

    # ── 单场战斗 ────────────────────────────────────────────────
    def resolve_battle(self, attacker: IUnit, defender: IUnit,
                       current_turn: int) -> BattleResultPayload:
        """结算单场 1v1 战斗。

        完整流程:
        1. 记录战前 HP
        2. 判定先手:
           - 若 COMBAT_RANGED_FIRST_STRIKE 且 attacker.attack_range > 1
             且距离 > 1: 攻击方先手，防御方不反击
           - 否则: 同时结算（攻击方造成伤害后，若防御方存活，防御方反击）
        3. 计算伤害并应用
        4. 检查阵亡
        5. 若防御方 HP < 20% 且非 HQ: (COMBAT_ROUT_CHANCE) 概率溃逃
        6. 广播 BATTLE_RESULT 事件
        7. 返回 BattleResultPayload
        """

    # ── 辅助 ────────────────────────────────────────────────────
    def determine_outcome(self, attacker_hp_ratio: float,
                          defender_hp_ratio: float,
                          attacker_killed: bool,
                          defender_killed: bool) -> str:
        """根据战后血量比判定战斗结果（用于战报措辞）。

        Returns:
            BattleOutcome 的值字符串
        - attacker_hp_ratio >= 0.70 → DECISIVE_WIN (大胜)
        - attacker_hp_ratio < 0.30 → PYRRHIC_WIN (惨胜)
        - 双方阵亡 → MUTUAL_KILL
        - 防御方 HP < 0.20 且逃跑 → ENEMY_ROUTED
        """

    def get_units_in_combat_range(self) -> list[tuple[IUnit, IUnit]]:
        """找出所有处于交战状态的敌对单位对。

        遍历所有存活单位，用 IRangeQuery 找到彼此攻击范围内的敌人。
        去重：(A, B) 和 (B, A) 只结算一次。
        """
```

### 5.4 战斗流程详解

```
┌──────────────────────────────────────────────┐
│           resolve_battle(A, D)                │
├──────────────────────────────────────────────┤
│ 1. 记录 HP_before (A.hp, D.hp)              │
│                                              │
│ 2. 先手判定:                                  │
│    IF A.attack_range > 1 AND dist(A,D) > 1:  │
│       A 先手攻击 → D 受到伤害                  │
│       IF D 存活 AND dist(D,A) <= D.range:    │
│           D 反击                              │
│    ELSE:                                     │
│       A 攻击 D (近战同时结算)                  │
│       IF D 存活:                              │
│           D 反击 A                            │
│                                              │
│ 3. 伤害结算:                                  │
│    damage = calculate_damage(A, D, terrain)   │
│    actual = D.take_damage(damage, A)          │
│                                              │
│ 4. 阵亡检查:                                  │
│    IF D.current_hp <= 0:                     │
│       unit_manager.kill_unit(D, A, turn)     │
│    IF A.current_hp <= 0:                     │
│       unit_manager.kill_unit(A, D, turn)     │
│                                              │
│ 5. 溃逃判定 (仅敌军 + HP < 20%):              │
│    IF D.faction == ENEMY AND ratio < 0.20:   │
│       IF random() < COMBAT_ROUT_CHANCE:       │
│           强制撤退 1~3 格                      │
│           → outcome = ENEMY_ROUTED            │
│                                              │
│ 6. 广播 BATTLE_RESULT 事件                    │
│                                              │
│ 7. 返回 BattleResultPayload                  │
└──────────────────────────────────────────────┘
```

### 5.5 去重规则

同一对 (A, B) 不重复结算。使用 `frozenset({a.unit_id, b.unit_id})` 标记已处理。

---

## 6. commander.py — 指令解析与执行

### 6.1 概述

实现 `ICommander` 接口，处理玩家下达的 7 种指令的解析、验证、执行。

### 6.2 指令数据结构

```python
@dataclass
class Command(ICommand):
    """单条指令的完整数据。"""
    command_type: CommandType
    target_unit_id: str
    params: dict          # {"x": 10, "y": 5} 或 {"direction": "N"} 等
    issued_turn: int      # 下达时的回合数
    arrival_turn: int     # 预计到达回合 (issued_turn + delay)

    def execute(self, unit: IUnit, game_state: IGameState) -> bool: ...
    def get_human_description(self) -> str: ...
```

### 6.3 类: `Commander`

```python
class Commander(ICommander):
    """指令管理与传达系统。

    职责:
    - 解析玩家指令参数，创建 Command 实例
    - 将指令放入传达队列 (command_queue)
    - 每回合处理到期指令，执行之
    - 指令覆盖/取消
    """

    def __init__(self, unit_manager: UnitManager,
                 game_map: IMap,
                 command_queue: CommandQueue) -> None:
        ...

    # ── 下达指令 ────────────────────────────────────────────────
    def issue_command(self, unit_id: str, command_type: CommandType,
                      params: dict) -> bool:
        """下达指令 → 进入传达队列 → 广播 COMMAND_SENT。"""

    # ── 执行队列 ────────────────────────────────────────────────
    def process_command_queue(self, current_turn: int) -> list[ICommand]:
        """处理传达队列:
        1. command_queue.pop_due_commands(current_turn)
        2. 对每个到期指令，找到目标单位，执行 execute()
        3. 广播 COMMAND_ARRIVED
        4. 返回已执行的指令列表
        """

    # ── 查询/取消 ───────────────────────────────────────────────
    def get_pending_commands(self, unit_id: str) -> list[ICommand]: ...
    def cancel_all_commands(self, unit_id: str) -> None: ...
```

### 6.4 七种指令执行规格

#### 6.4.1 MOVE — 移动到目标坐标

```
参数: {"x": int, "y": int}
执行逻辑:
  1. 验证目标坐标在地图内、可通行
  2. 调用 IMap.find_path(start, target, unit.speed)
  3. 沿路径逐格移动（直到速度耗尽或到达目标）
  4. 若到达目标: 返回 True (指令完成)
  5. 若未到达: 返回 False (下回合继续)
  6. 途中遇到敌人: 停止移动，进入战斗 (战斗由主循环在后续阶段处理)
特殊:
  - HQ (speed=0) 不可执行 MOVE，静默忽略
```

#### 6.4.2 ATTACK — 向目标区域进击

```
参数: {"x": int, "y": int}
执行逻辑:
  1. 向目标坐标移动 (同 MOVE)
  2. 途中检测是否有敌人在攻击范围内:
     IF IRangeQuery.has_enemy_in_range(unit, unit.attack_range):
       停止移动，攻击最近的敌人 (调用 battle_system.resolve_battle)
       返回 True (指令完成，已交战)
  3. 到达目标坐标后: 返回 True
特别:
  与 MOVE 的区别: ATTACK 会在途中主动索敌交战
```

#### 6.4.3 HOLD — 原地驻守

```
参数: {} (无参数)
执行逻辑:
  1. 单位本回合不移动
  2. 若敌人在攻击范围内: 自动攻击最近敌人
  3. 返回 False (驻守持续，直到下达新指令)
  4. 防守加成: 驻守单位获得 +1 临时防御 (仅驻守回合)
特殊:
  - 这是持续指令，直到被新指令覆盖
```

#### 6.4.4 SCOUT — 侦察移动

```
参数: {"direction": str}  # "N"/"NE"/"E"/"SE"/"S"/"SW"/"W"/"NW"
执行逻辑:
  1. 向指定方向移动 unit.speed 格
  2. 视野扩大: 侦察移动时 vision_range 临时 +2
  3. 沿途发现敌人: 记录位置，广播 ENEMY_SPOTTED
  4. 不会主动交战 (遇到敌人绕行或停止)
  5. 到达目标后: 返回 True
特殊:
  - 只有 Scout 兵种可发挥最大效果 (视野 6+2=8)
  - 其他兵种也可用，但侦察效果有限
```

#### 6.4.5 RETREAT — 撤退

```
参数: {"direction": str}
执行逻辑:
  1. 向指定方向快速撤退 unit.speed + 2 格
  2. 撤退不受敌人阻挡 (无视敌方单位占格，但不穿过不可通行地形)
  3. 本回合不反击
  4. 撤退后: 返回 True
特殊:
  - AI 溃逃也调用此逻辑
```

#### 6.4.6 CAPTURE — 占领指挥所

```
参数: {"x": int, "y": int}  # 目标指挥所坐标
执行逻辑:
  1. 移动到目标坐标 (同 MOVE)
  2. 到达后检查该格是否为敌方 HQ:
     IF terrain == HQ_CELL AND 有敌方 HQ 单位:
       进入占领倒计时
  3. 占领倒计时: 需连续停留 CAPTURE_REQUIRED_TURNS (2) 回合
  4. 途中被攻击打断: 若 CAPTURE_INTERRUPTIBLE=True，重置倒计时
  5. 占领成功: 敌方 HQ 被销毁 → 广播 HQ_CAPTURED → 广播 GAME_OVER
特殊:
  - 只有步兵可以占领导致胜利（其他兵种可移动到 HQ 格但不能触发占领）
```

#### 6.4.7 PATROL — 巡逻

```
参数: {"path": [[x1,y1], [x2,y2], ...]}  # 路径坐标列表
执行逻辑:
  1. 沿路径顺序移动，每回合移动 unit.speed 格
  2. 到达路径终点后: 反向移动（往复巡逻）
  3. 途中发现敌人: 攻击（同 ATTACK）
  4. 返回 False (持续巡逻，直到被新指令覆盖)
特殊:
  - 这是持续指令
  - 路径至少 2 个点
```

### 6.5 指令覆盖规则

```
IF 单位正在执行指令 AND 玩家下达新指令:
    1. 清空该单位的传达队列中的旧指令
    2. 新指令进入传达队列（重新计延迟）
    3. 若单位正在战斗中:
       - RETREAT 指令: 脱离战斗后执行
       - 其他指令: 等当前战斗结束再执行
       - 单位阵亡: 指令自动作废 → 广播 COMMAND_EXPIRED
```

---

## 7. command_queue.py — 通信延迟队列

### 7.1 概述

实现指令的通信延迟机制。指令下达后不是立即执行，而是进入队列等待 1~3 回合。

### 7.2 类: `CommandQueue`

```python
class CommandQueue:
    """通信延迟队列。

    管理指令从"下达"到"到达单位"之间的延迟。
    """

    def __init__(self, seed: int | None = None) -> None:
        """初始化队列。
        Args:
            seed: 随机种子（测试用）
        """
        self._queue: list[Command] = []
        self._rng = random.Random(seed)

    # ── 入队 ────────────────────────────────────────────────────
    def enqueue(self, command: Command, current_turn: int) -> int:
        """指令入队，随机分配延迟。

        延迟概率分布 (COMMAND_DELAY_WEIGHTS):
        - 30%: 1 回合
        - 50%: 2 回合
        - 20%: 3 回合

        Returns:
            指令预计到达回合数
        """

    # ── 出队 ────────────────────────────────────────────────────
    def pop_due_commands(self, current_turn: int) -> list[Command]:
        """返回所有本回合到期的指令（从队列中移除）。"""

    # ── 查询 ────────────────────────────────────────────────────
    def get_pending_for_unit(self, unit_id: str) -> list[Command]:
        """获取某单位的所有待执行指令。"""

    def cancel_for_unit(self, unit_id: str) -> None:
        """移除某单位的所有待执行指令。"""

    def peek_all(self) -> list[Command]:
        """查看队列中所有指令（不修改队列，调试用）。"""

    @property
    def size(self) -> int:
        """队列中待处理指令总数。"""
```

### 7.3 延迟分配算法

```python
def _roll_delay(self) -> int:
    """根据权重分布随机延迟回合数。"""
    weights = COMMAND_DELAY_WEIGHTS  # (0.30, 0.50, 0.20)
    # 使用 random.choices([1, 2, 3], weights=weights, k=1)[0]
    return self._rng.choices([1, 2, 3], weights=weights, k=1)[0]
```

---

## 8. ai.py — 敌军 AI 决策

### 8.1 概述

实现敌军单位的自动决策。AI 不是全局智能体，而是每个敌军单位各自运行独立的行为树。

### 8.2 类: `EnemyAI`

```python
class EnemyAI:
    """敌军 AI 决策系统。

    每回合由主循环在"AI 决策阶段"调用 decide_all()。
    """

    def __init__(self, unit_manager: UnitManager,
                 range_query: IRangeQuery,
                 game_map: IMap,
                 commander: Commander) -> None:
        ...

    def decide_all(self, current_turn: int) -> None:
        """为所有存活的敌军单位决策并下达指令。

        决策优先级 (从高到低):
        1. 溃逃: HP < 20% → RETREAT
        2. 战斗: 攻击范围内有敌人 → ATTACK 或 HOLD
        3. 保卫: 友方 HQ 附近有敌人 → 回防 MOVE
        4. 巡逻: 在指定区域 PATROL
        5. 侦察: 向敌方半场 SCOUT
        """

    def decide_for_unit(self, unit: IUnit, current_turn: int) -> Command:
        """为单个敌军单位做出决策。

        行为树:
        ┌─ HP < 20%? ──YES──▶ RETREAT (向己方 HQ 方向)
        │
        └─ NO ─▶ 攻击范围内有敌人?
                  ├─ YES ─▶ 炮兵? ──YES──▶ 保持距离 ATTACK
                  │         └─ NO ──▶ ATTACK 最近敌人
                  │
                  └─ NO ─▶ 己方 HQ 受威胁?
                            ├─ YES ─▶ MOVE 回防 HQ
                            │
                            └─ NO ─▶ 50%: MOVE 向敌方 HQ
                                     └─ 50%: PATROL 当前区域
        """
```

### 8.3 行为优先级详解

| 优先级 | 条件 | 行为 | 说明 |
|:--:|------|------|------|
| 1 | `current_hp / max_hp < COMBAT_ROUT_HP_RATIO` | RETREAT 向己方 HQ | 保命优先 |
| 2 | `has_enemy_in_range(unit, attack_range)` | ATTACK 最近敌人 | 应战 |
| 3 | `has_enemy_in_range(hq, 5)` | MOVE 回防 HQ | 保卫指挥所 |
| 4 | 默认 | PATROL 或 MOVE 向敌方 HQ | 主动进攻 |

### 8.4 AI 约束

- AI 指令也走相同的 Commander + CommandQueue 流程
- AI 不受通信延迟影响（或共用同一延迟系统以保持公平）
- 设计决策: AI 指令走延迟系统，保持游戏性一致

---

## 9. 事件广播契约

### 9.1 事件 → 模块 → 触发条件

| 事件类型 | 广播模块 | 触发条件 |
|----------|:--------:|----------|
| `BATTLE_RESULT` | `battle_system.py` | 每次 resolve_battle() 完成 |
| `UNIT_KILLED` | `unit_manager.py` | kill_unit() 调用时 |
| `UNIT_DAMAGED` | `battle_system.py` | 单位受伤但未阵亡 |
| `ENEMY_SPOTTED` | `ai.py` / `commander.py` | SCOUT 或移动中发现敌军 |
| `HQ_CAPTURED` | `commander.py` | CAPTURE 指令占领成功 |
| `HQ_UNDER_ATTACK` | `battle_system.py` | 指挥所受到攻击 |
| `COMMAND_SENT` | `commander.py` | issue_command() 成功 |
| `COMMAND_ARRIVED` | `commander.py` | process_command_queue() 到期执行 |
| `COMMAND_EXPIRED` | `commander.py` | 单位阵亡导致指令作废 |
| `GAME_OVER` | `battle_system.py` | 检测到胜利/失败条件 |

### 9.2 广播代码模板

```python
from src.core.event_bus import event_bus
from src.core.constants import GameEventType, BattleResultPayload

# 广播战斗结果
event_bus.emit(GameEventType.BATTLE_RESULT, BattleResultPayload(
    turn=current_turn,
    attacker_id=attacker.unit_id,
    attacker_name=attacker.name,
    attacker_faction=attacker.faction.value,
    attacker_hp_before=hp_before_a,
    attacker_hp_after=attacker.current_hp,
    defender_id=defender.unit_id,
    defender_name=defender.name,
    defender_faction=defender.faction.value,
    defender_hp_before=hp_before_d,
    defender_hp_after=defender.current_hp,
    damage_to_defender=damage_to_d,
    damage_to_attacker=damage_to_a,
    attacker_killed=not attacker.is_alive,
    defender_killed=not defender.is_alive,
    location=defender.position.to_tuple(),
    outcome=outcome,
))
```

---

## 10. 测试计划

### 10.1 测试文件清单

```
tests/battle/
├── __init__.py
├── test_units.py           # 8 条
├── test_battle_system.py   # 8 条
└── test_commander.py       # 5 条
```

### 10.2 test_units.py — 兵种行为测试 (最少 8 条)

| # | 测试用例 | 验证点 |
|:--:|----------|--------|
| 1 | `test_create_infantry_has_correct_stats` | 步兵属性 = UNIT_STATS[INFANTRY] |
| 2 | `test_create_all_unit_types` | 5 种兵种均可成功创建 |
| 3 | `test_hq_cannot_attack` | HQ.attack_target() 抛出 ValueError |
| 4 | `test_hq_cannot_move` | HQ.move_to() 返回 False |
| 5 | `test_take_damage_reduces_hp` | 受到 5 点伤害，HP 减少 5 |
| 6 | `test_take_damage_kills_unit` | HP 降为 0 → is_alive = False |
| 7 | `test_can_attack_in_range` | 相邻敌人 → True |
| 8 | `test_can_attack_out_of_range` | 距离超过 attack_range → False |
| 9 | `test_get_state_report` | 包含单位名称、兵种、HP 信息 |

### 10.3 test_battle_system.py — 对战测试 (最少 8 条)

| # | 测试用例 | 验证点 |
|:--:|----------|--------|
| 1 | `test_damage_formula_basic` | attack=4, defense=1 → raw=3 |
| 2 | `test_damage_minimum_one` | attack=1, defense=10 → damage=1 |
| 3 | `test_type_advantage_infantry_vs_cavalry` | 步兵攻骑兵 ×1.5 |
| 4 | `test_type_advantage_cavalry_vs_artillery` | 骑兵攻炮兵 ×1.5 |
| 5 | `test_type_advantage_artillery_vs_infantry` | 炮兵攻步兵 ×1.5 |
| 6 | `test_no_advantage_same_type` | 同兵种 ×1.0 |
| 7 | `test_counterattack` | 被攻击方存活时触发反击 |
| 8 | `test_artillery_ranged_first_strike` | 炮兵远程攻击 → 防御方不反击 |
| 9 | `test_battle_kills_unit` | 伤害 ≥ HP → unit.is_alive = False |

### 10.4 test_commander.py — 指令测试 (最少 5 条)

| # | 测试用例 | 验证点 |
|:--:|----------|--------|
| 1 | `test_command_queue_delay` | 指令入队后 arrival_turn = current + delay |
| 2 | `test_command_delay_in_range` | 延迟在 [1, 3] 范围内 |
| 3 | `test_command_move_executes` | MOVE 指令：单位坐标改变 |
| 4 | `test_command_hold_stays` | HOLD 指令：单位坐标不变 |
| 5 | `test_command_cancel_on_death` | 单位阵亡 → 指令被清除 |

---

## 11. 实现顺序建议

```
Phase 1: 基础搭建 (优先)
  ├── [1] units.py          — 5 个兵种子类 + 与 UnitBase 对接
  ├── [2] unit_manager.py   — 工厂方法 + 销毁 + 统计
  └── [3] tests/test_units.py

Phase 2: 核心战斗 (核心)
  ├── [4] battle_system.py  — calculate_damage + resolve_battle
  └── [5] tests/test_battle_system.py

Phase 3: 指令系统 (战斗闭环)
  ├── [6] command_queue.py  — 延迟队列
  ├── [7] commander.py      — 7 种指令 + ICommander 实现
  └── [8] tests/test_commander.py

Phase 4: AI (可选，Sprint 2)
  └── [9] ai.py             — 敌军行为树

Phase 5: 整合
  └── [10] __init__.py      — 统一导出
```

---

> **本文档与 `src/core/interfaces.py` 和 `src/core/constants.py` 为同一事实来源。如有矛盾，以 Phase 0 骨架代码为准。**
