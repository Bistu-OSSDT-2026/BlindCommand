# BlindCommand 底层数据层设计规范（CORE_SPEC）

> **版本**: v1.1  
> **负责人**: #2（底层架构 Vibe 程序员）  
> **范围**: `src/core/` 下除 Phase 0 已定稿文件（`constants.py` / `types.py` / `events.py` / `interfaces.py` / `event_bus.py`）之外的全部模块  
> **依赖文档**: `DESIGN.md`（做什么）、`WORKFLOW.md`（谁来做/怎么做）、`STYLE_GUIDE.md`（怎么写）、`TECH_STACK.md`（工具链）、`PROMPTS.md`（AI 生成模板）  
> **最后更新**: 2026-07-08

---

## 0. 阅读约定

- 本 spec 中所有接口签名**必须与 `src/core/interfaces.py` 逐字一致**；如发现冲突，以 `interfaces.py` 为准，并按 `WORKFLOW.md` 附录 B「接口变更流程」提 PR 修正。
- 标记 `⚠️ 待确认` 的条目是本 spec 做出的设计决议，但触及跨层契约，需 #1/#3/#4 在评审时确认；确认前按本 spec 的推荐方案实现。
- 标记 `📌 DECISION` 的条目是 #2 内部设计选择，无需跨层评审，但记录在案以便回溯。
- 伪代码使用 Python 风格，省略 docstring 与类型注解以求简洁；正式实现必须补齐（遵循 `STYLE_GUIDE.md`）。

---

## 1. 设计目标与全局约束

### 1.1 本层职责边界

底层数据层是整个游戏的**事实来源（source of truth）**：地图状态、单位实例、坐标体系、视野/迷雾计算、主循环时序。所有上层（#3 业务层、#4 UI 层）只能通过 `interfaces.py` 中定义的抽象接口读写本层。

```
┌─────────────────────────────────────────────────────────┐
│  #4 UI 层        ──只订阅 EventBus + 查询 IFogOfWar/IMap──▶  本层  │
│  #3 业务层       ──只调用 IUnit/IMap/IRangeQuery/IGameState──▶  本层 │
│  本层（#2）      ──不依赖任何上层，不 import src.battle / src.ui──  │
└─────────────────────────────────────────────────────────┘
```

### 1.2 不可破坏的不变量

| # | 不变量 | 守护位置 |
|:--:|------|----------|
| INV-1 | 单位坐标永远在地图范围内 `[0,width) × [0,height)` | `Map.place_unit` / `Unit.move_to` |
| INV-2 | `current_hp` 永远满足 `0 ≤ current_hp ≤ max_hp` | `UnitBase.take_damage` / `heal` |
| INV-3 | `is_alive == False` 的单位不出现在任何检索结果中 | `RangeQuery` / `FogOfWar` 过滤 |
| INV-4 | 同一普通格子上至多一个非 HQ 单位（HQ 格例外，见 §5.3） | `Map` 占用表 |
| INV-5 | `GameLoop.current_turn` 单调递增，到达 `MAX_TURNS` 后不再增加 | `GameLoop.run_turn` |
| INV-6 | 单位 `unit_id` 全局唯一 | `UnitManager` / 构造校验 |
| INV-7 | 河流（`RIVER`）格子不可放置/移动任何单位 | `Map.is_passable` |
| INV-8 | `EventBus` 回调内抛出的异常不得中断主循环 | `EventBus` 已实现 + `GameLoop` 不依赖回调返回值 |

### 1.3 编码规范要点（摘自 STYLE_GUIDE.md）

- Python 3.11+，`mypy --strict` 必须通过
- 类名 `PascalCase`；接口已用 `I` 前缀（`IUnit` 等），**实现类不加 `I` 前缀**（如 `UnitBase`、`GameMap`、`RangeQuery`、`FogOfWar`、`GameLoop`）
- 常量引用 `constants.py`，**禁止魔法数字**
- 公开方法 Google 风格 docstring
- import 顺序：标准库 → 第三方 → 项目内部（isort 自动）
- 禁止 `from X import *`、裸 `except:`、生产代码 `print()`
- 单元文件头部写模块 docstring

---

## 2. 模块依赖图与开发顺序

### 2.1 模块依赖关系

```
                    ┌──────────────┐
                    │  constants   │  (Phase 0, 只读)
                    │  interfaces  │
                    └──────┬───────┘
                           │ 被 import
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
       ┌─────────┐    ┌─────────┐    ┌──────────┐
       │unit_base│    │   map   │    │event_bus │ (已完成)
       │  .py    │◀───│  .py    │    │  .py     │
       └────┬────┘    └────┬────┘    └──────────┘
            │              │
            └──────┬───────┘
                   ▼
            ┌─────────────┐
            │ range_utils │  依赖 unit 列表 + map
            │    .py      │
            └──────┬──────┘
                   ▼
            ┌─────────────┐
            │ fog_of_war  │  依赖 unit 列表 + map + 地形
            │    .py      │
            └──────┬──────┘
                   ▼
            ┌─────────────┐
            │  game_loop  │  组装全部，实现 IGameLoop + IGameState
            │    .py      │
            └─────────────┘
```

### 2.2 推荐开发顺序（对齐 WORKFLOW.md Sprint 1/2）

| 阶段 | 模块 | 里程碑对齐 | 自测最低条数 |
|:----:|------|-----------|:---:|
| Sprint 1-a | `unit_base.py` | CP-1 | 2 |
| Sprint 1-b | `map.py` | CP-1 | 2 |
| Sprint 1-c | `range_utils.py` | CP-1 | 1 |
| Sprint 2-a | `fog_of_war.py` | CP-2 | 2 |
| Sprint 2-b | `game_loop.py` | CP-2 | 1（+ #5 集成测试） |
| — | `event_bus.py` | 已完成 | 已有 |

> WORKFLOW.md §7.1 要求 #2 至少 5 条自动化测试；本 spec 在 §9 给出 18 条建议测试，覆盖更全。

---

## 3. 模块一：`src/core/unit_base.py`

### 3.1 职责

实现 `IUnit` 接口的具体基类 `UnitBase`，作为所有兵种的父类（#3 的 `Infantry/Cavalry/...` 继承它）。负责：

- 持有单位全部属性（血量、攻防、坐标、阵营、兵种等）
- `take_damage`（受伤）、内部销毁逻辑
- `move_to`（委托 Map 寻路）
- `attack_target`（**最小默认实现**，#3 可重写）
- `can_attack` / `get_state_report`

### 3.2 实现的接口（精确签名，与 `interfaces.py:33-173` 一致）

```python
class UnitBase(IUnit):
    # ── 只读属性 ──
    @property
    def unit_id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def faction(self) -> Faction: ...
    @property
    def unit_type(self) -> UnitType: ...
    @property
    def position(self) -> Coordinate: ...
    @property
    def max_hp(self) -> int: ...
    @property
    def current_hp(self) -> int: ...
    @property
    def attack(self) -> int: ...
    @property
    def defense(self) -> int: ...          # 含地形加成，见 §3.5
    @property
    def speed(self) -> int: ...
    @property
    def attack_range(self) -> int: ...
    @property
    def vision_range(self) -> int: ...
    @property
    def is_alive(self) -> bool: ...
    @property
    def is_hq(self) -> bool: ...

    # ── 操作方法 ──
    def take_damage(self, amount: int, source: IUnit) -> int: ...
    def move_to(self, target: Coordinate) -> bool: ...
    def attack_target(self, target: IUnit) -> int: ...
    def get_state_report(self) -> str: ...
    def can_attack(self, target: IUnit) -> bool: ...
```

### 3.3 内部数据结构

```python
class UnitBase(IUnit):
    def __init__(
        self,
        unit_id: str,
        name: str,
        faction: Faction,
        unit_type: UnitType,
        position: Coordinate,
        stats: UnitStats,            # 从 UNIT_STATS[unit_type] 取
        game_map: IMap | None = None,  # 可选 Map 引用，见 §3.6
    ) -> None: ...

        # 私有字段
        self._unit_id = unit_id
        self._name = name
        self._faction = faction
        self._unit_type = unit_type
        self._position = position
        self._max_hp = stats.max_hp
        self._current_hp = stats.max_hp
        self._base_attack = stats.attack
        self._base_defense = stats.defense
        self._speed = stats.speed
        self._attack_range = stats.attack_range
        self._vision_range = stats.vision_range
        self._is_hq = stats.is_hq
        self._is_alive = True
        self._game_map = game_map       # 弱依赖，仅 move_to 用
```

> 📌 DECISION：单位不持有可变状态机字段（`is_moving`/`is_in_combat`/`pending_order`）。这些是 #3 的业务状态，由 #3 在兵种子类或 `UnitManager` 中维护，避免底层数据类承担业务语义。

### 3.4 `take_damage` 语义（⚠️ 待确认 — 接口 docstring 歧义）

`interfaces.py:128-139` 的 docstring 存在歧义：

- Args 写「amount: 原始伤害值（计算克制/地形前的值由调用方处理）」
- Returns 写「实际造成的伤害值（扣除防御后）」

**本 spec 决议（推荐方案）**：

> `take_damage` 是**纯扣血原语**。传入的 `amount` 是 #3 的 `battle_system` 用完整伤害公式计算后的**最终伤害值**（已扣除防御、已乘克制倍率与地形修正）。本方法只负责：扣减 `current_hp`（下限 0）、阵亡判定、返回**实际扣血量** `min(amount, 扣血前 current_hp)`。防御力/克制/地形的计算完全归属 #3。

```python
def take_damage(self, amount: int, source: IUnit) -> int:
    if not self._is_alive:
        return 0
    if amount < 0:
        raise ValueError(f"伤害值不能为负，收到 {amount}")
    applied = min(amount, self._current_hp)
    self._current_hp -= applied
    if self._current_hp == 0:
        self._is_alive = False
    return applied
```

> ⚠️ 待确认：此决议与 #3 的 `battle_system` 设计强相关。若 #3 期望 `take_damage` 自行扣除 `defense`，则需走接口变更流程修改 `IUnit.take_damage` 的 docstring 并明确「防御扣减在哪一层」。**默认按本 spec 方案实现。**

### 3.5 `defense` 属性：含地形加成

`interfaces.py` 注明 `defense` 是「防御力（含地形加成后的最终值）」。本层负责计算：

```python
@property
def defense(self) -> int:
    if self._game_map is None:
        return self._base_defense
    bonus = self._game_map.get_defense_bonus(self._position)
    return self._base_defense + bonus
```

> 📌 DECISION：地形防御加成归属 #2（底层），因为它只依赖单位自身坐标 + 地形表，无业务语义。#3 读 `unit.defense` 即可拿到含地形的最终防御。

### 3.6 `move_to` 实现

```python
def move_to(self, target: Coordinate) -> bool:
    """移动到 target。返回 True 当且仅当目标在本回合移动力内可达并已抵达。"""
    if not self._is_alive:
        return False
    if self._game_map is None:
        # 无 Map 模式（单测/#3 兵种自测）：直接更新坐标，假定合法
        self._position = target
        return True
    if not self._game_map.is_within_bounds(target):
        return False
    if self._position == target:
        return True
    path = self._game_map.find_path(self._position, target, self._speed)
    if not path:
        return False                  # 不可达
    # find_path 已按 max_steps=speed 截断；path[-1] 即本回合最远可达点
    reached_end = self._game_map.move_unit(self, self._position, path[-1])
    if reached_end:
        self._position = path[-1]
    return self._position == target   # True 仅当真正抵达 target
```

> 📌 DECISION：`move_to` 是「全或无」语义——只有真正抵达 `target` 才返回 True（对齐接口 docstring「路径存在且剩余移动力足够」）。部分移动（走 `speed` 步但未到 target）**不发生**；若 #3 需要逐格推进（如 PATROL），应由 #3 在多回合内重复调用。

### 3.7 `attack_target` 默认实现（⚠️ 待确认 — 与 #3 职责边界）

```python
def attack_target(self, target: IUnit) -> int:
    """默认近战攻击：基础伤害 = max(COMBAT_MIN_DAMAGE, atk - def)。不含克制/反击/先手。"""
    if not self.can_attack(target):
        return 0
    raw = max(COMBAT_MIN_DAMAGE, self.attack - target.defense)
    return target.take_damage(raw, self)
```

> ⚠️ 待确认：完整伤害公式（兵种克制 `get_advantage_multiplier`、反击、炮兵远程先手、地形修正）按 `WORKFLOW.md` 归属 #3 的 `battle_system`。本层的默认 `attack_target` 只提供**最朴素的单次伤害原语**，供：
> - #3 不重写时的兜底
> - #2 自测（验证扣血链路）
>
> #3 应在其兵种子类或 `battle_system.resolve_combat()` 中实现完整公式，并可在重写 `attack_target` 时调用 `get_advantage_multiplier()`。**若 #1 认为 `attack_target` 应内含克制倍率，请走接口变更流程明确。**

### 3.8 `can_attack`

```python
def can_attack(self, target: IUnit) -> bool:
    if not self._is_alive or not target.is_alive:
        return False
    if self._attack_range == 0:            # HQ 不可攻击
        return False
    if target.faction == self._faction:    # 同阵营不可攻击
        return False
    dist = self._position.chebyshev_distance(target.position)
    return dist <= self._attack_range
```

> 📌 DECISION：距离判定用**切比雪夫距离**（八邻域），与 `IRangeQuery` 的 radius 语义一致。

### 3.9 `get_state_report`

生成战报用的人类可读文本，调用 `UNIT_DISPLAY_NAMES`：

```python
def get_state_report(self) -> str:
    status = "存活" if self._is_alive else "阵亡"
    hp_pct = int(self._current_hp / self._max_hp * 100) if self._max_hp else 0
    return (f"{self._name}（{UNIT_DISPLAY_NAMES[self._unit_type]}）"
            f" [{status}] HP {self._current_hp}/{self._max_hp} ({hp_pct}%)")
```

### 3.10 边界与错误处理

| 场景 | 处理 |
|------|------|
| 对已阵亡单位调用 `take_damage` | 返回 0（幂等，不抛异常） |
| `amount < 0` | `raise ValueError` |
| `move_to` 目标越界 / 不可达 / 被占 | 返回 False，位置不变 |
| 对已阵亡单位调用 `move_to` / `attack_target` | 返回 False / 0 |
| HQ 的 `attack_range == 0` | `can_attack` 恒为 False |
| 构造时 `position` 越界 | `raise ValueError`（若传了 `game_map`） |

### 3.11 事件总线交互

`UnitBase` 本身**不直接 emit 事件**。阵亡事件 `UNIT_KILLED`、受伤事件 `UNIT_DAMAGED` 由 #3 的 `battle_system` 在调用 `take_damage` 后根据返回值广播（#3 拥有战斗语义）。本层保持被动。

> 📌 DECISION：保持 Unit 为纯数据+行为对象，不耦合 EventBus，降低 #3/#4 测试时的副作用。

---

## 4. 模块二：`src/core/map.py`

### 4.1 职责

实现 `IMap` 的具体类 `GameMap`：二维地形数组、格子占用表、越界/通行/移动消耗查询、单位放置/移除/移动、八邻域、A* 寻路、双方指挥所坐标。

### 4.2 实现的接口（精确签名，与 `interfaces.py:180-273` 一致）

```python
class GameMap(IMap):
    @property
    def width(self) -> int: ...
    @property
    def height(self) -> int: ...
    def get_terrain(self, coord: Coordinate) -> TerrainType: ...
    def is_passable(self, coord: Coordinate) -> bool: ...
    def is_within_bounds(self, coord: Coordinate) -> bool: ...
    def get_move_cost(self, coord: Coordinate) -> int: ...
    def get_defense_bonus(self, coord: Coordinate) -> int: ...
    def get_units_at(self, coord: Coordinate) -> list[IUnit]: ...
    def place_unit(self, unit: IUnit, coord: Coordinate) -> bool: ...
    def remove_unit(self, unit: IUnit) -> None: ...
    def move_unit(self, unit: IUnit, from_coord: Coordinate, to_coord: Coordinate) -> bool: ...
    def get_faction_hq_location(self, faction: Faction) -> Optional[Coordinate]: ...
    def find_path(self, start: Coordinate, end: Coordinate, max_steps: int) -> list[Coordinate]: ...
    def get_neighbors(self, coord: Coordinate) -> list[Coordinate]: ...
```

### 4.3 内部数据结构

```python
class GameMap(IMap):
    def __init__(
        self,
        terrain: list[list[int]],          # height×width 的地形编码矩阵
        friendly_hq: Coordinate,
        enemy_hq: Coordinate,
        allow_stacking_on_hq: bool = True,  # 见 §5.3
    ) -> None: ...

        self._width = len(terrain[0]) if terrain else 0
        self._height = len(terrain)
        self._terrain = terrain                        # 直接持有，不复制单位实例
        # 占用表：Coordinate -> list[IUnit]
        self._occupancy: dict[Coordinate, list[IUnit]] = defaultdict(list)
        self._hq_locations: dict[Faction, Coordinate] = {
            Faction.FRIENDLY: friendly_hq,
            Faction.ENEMY: enemy_hq,
        }
```

> 📌 DECISION：占用表用 `dict[Coordinate, list[IUnit]]` 而非单值映射，以容纳 HQ 格的「HQ 单位 + 围攻单位」共存情况（见 §5.3）。普通格通过 `place_unit` 保证 list 长度 ≤ 1。

### 4.4 工厂方法：从 JSON 加载

```python
@classmethod
def from_map_file(cls, path: str | Path) -> GameMap: ...
```

读取 `data/maps/map_01.json` 的 `terrain` / `friendly_hq` / `enemy_hq` 字段构造。地图尺寸校验：

```python
assert MAP_MIN_SIZE <= width <= MAP_MAX_SIZE
assert MAP_MIN_SIZE <= height <= MAP_MAX_SIZE
assert len(terrain) == height and all(len(row) == width for row in terrain)
```

### 4.5 基础查询

```python
def is_within_bounds(self, coord: Coordinate) -> bool:
    return 0 <= coord.x < self._width and 0 <= coord.y < self._height

def get_terrain(self, coord: Coordinate) -> TerrainType:
    if not self.is_within_bounds(coord):
        raise ValueError(f"坐标 {coord} 越界")
    return TerrainType(self._terrain[coord.y][coord.x])

def is_passable(self, coord: Coordinate) -> bool:
    return self.is_within_bounds(coord) and get_terrain_props(...).is_passable
    # 复用 constants.is_passable(code)

def get_move_cost(self, coord: Coordinate) -> int:
    if not self.is_within_bounds(coord):
        return -1
    return get_move_cost(self._terrain[coord.y][coord.x])   # constants.get_move_cost

def get_defense_bonus(self, coord: Coordinate) -> int:
    return get_terrain_props(self._terrain[coord.y][coord.x]).defense_bonus
```

> 注意：`terrain` 矩阵索引为 `[y][x]`（行优先），与 `Coordinate(x, y)` 对应。全层统一此约定。

### 4.6 单位占用管理

```python
def place_unit(self, unit: IUnit, coord: Coordinate) -> bool:
    if not self.is_within_bounds(coord):
        return False
    if not self.is_passable(coord):
        return False
    occupants = self._occupancy[coord]
    if occupants:
        # 仅允许 HQ 格上叠加一个围攻者（见 §5.3）
        hq_here = any(o.is_hq for o in occupants)
        if not (self.allow_stacking_on_hq and hq_here and len(occupants) == 1):
            return False
    self._occupancy[coord].append(unit)
    return True

def remove_unit(self, unit: IUnit) -> None:
    for coord, occupants in self._occupancy.items():
        if unit in occupants:
            occupants.remove(unit)
            if not occupants:
                del self._occupancy[coord]
            return

def move_unit(self, unit, from_coord, to_coord) -> bool:
    if not self.is_within_bounds(to_coord) or not self.is_passable(to_coord):
        return False
    if unit not in self._occupancy.get(from_coord, []):
        return False
    # 占用检查同 place_unit
    ...
    self._occupancy[from_coord].remove(unit)
    self._occupancy[to_coord].append(unit)
    return True

def get_units_at(self, coord: Coordinate) -> list[IUnit]:
    return list(self._occupancy.get(coord, []))
```

### 4.7 八邻域

```python
def get_neighbors(self, coord: Coordinate) -> list[Coordinate]:
    result = []
    for d in Direction:                       # constants.Direction 八方向
        nb = coord + Coordinate(*d.value)
        if self.is_within_bounds(nb) and self.is_passable(nb):
            result.append(nb)
    return result
```

### 4.8 A* 寻路（核心算法）

**目标**：在 `max_steps` 步数预算内，找到从 `start` 到 `end` 的**最小移动消耗**路径。河流不可通行；森林消耗 2、山地消耗 3、平原/桥梁/指挥所消耗 1。

```python
import heapq

def find_path(self, start: Coordinate, end: Coordinate, max_steps: int) -> list[Coordinate]:
    # 边界
    if not (self.is_within_bounds(start) and self.is_within_bounds(end)):
        return []
    if not (self.is_passable(start) and self.is_passable(end)):
        return []
    if start == end:
        return [start]

    def h(c: Coordinate) -> int:
        # 启发式：切比雪夫距离 × 最小地形消耗（1），admissible
        return c.chebyshev_distance(end)

    open_heap: list[tuple[int, int, Coordinate]] = []
    counter = 0  # tie-breaker，保证 heapq 稳定
    heapq.heappush(open_heap, (h(start), counter, start))
    g_score: dict[Coordinate, int] = {start: 0}
    steps_taken: dict[Coordinate, int] = {start: 0}
    came_from: dict[Coordinate, Coordinate] = {}

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current == end:
            # 重建路径
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        cur_steps = steps_taken[current]
        if cur_steps >= max_steps:
            continue                          # 步数预算耗尽，不再扩展

        for nb in self.get_neighbors(current):
            step_cost = self.get_move_cost(nb)            # 1 / 2 / 3
            tentative_g = g_score[current] + step_cost
            tentative_steps = cur_steps + 1
            prev_g = g_score.get(nb, inf)
            # 同时受累计消耗与步数双重约束
            if tentative_g < prev_g and tentative_steps <= max_steps:
                came_from[nb] = current
                g_score[nb] = tentative_g
                steps_taken[nb] = tentative_steps
                counter += 1
                heapq.heappush(open_heap, (tentative_g + h(nb), counter, nb))

    return []                                  # 不可达
```

**设计要点**：

| 要点 | 说明 |
|------|------|
| `max_steps` 语义 | 限制**格子跳数**（每跨一格 +1），等于单位 `speed`。同时累计移动消耗用于最优路径选择 |
| 启发式 admissible | 切比雪夫距离 × 1（最小消耗）≤ 真实消耗，保证 A* 最优 |
| 返回路径含首尾 | `[start, ..., end]` |
| 不可达返回 `[]` | |
| 步数耗尽 | 若 `end` 在 `max_steps` 外，返回 `[]`（§3.6 的全或无语义） |

### 4.9 指挥所坐标

```python
def get_faction_hq_location(self, faction: Faction) -> Optional[Coordinate]:
    return self._hq_locations.get(faction)
```

### 4.10 边界与错误处理

| 场景 | 处理 |
|------|------|
| 越界 `get_terrain` | `raise ValueError` |
| 越界 `is_passable` / `get_move_cost` | 返回 False / -1（不抛） |
| `place_unit` 到河流/越界/已占普通格 | 返回 False |
| `move_unit` 起点无该单位 | 返回 False |
| `remove_unit` 不存在的单位 | 静默返回（幂等） |
| `find_path` 起或终在河流 | 返回 `[]` |

### 4.11 事件总线交互

`GameMap` 不 emit 事件。位置变化类事件（`POSITION_REPORT` / 阵亡移除）由调用方（#3 / `GameLoop`）广播。

---

## 5. 跨模块约定：HQ 格与单位叠加（⚠️ 待确认）

### 5.1 问题

`DESIGN.md` §9.1 胜利条件「占领指挥所：友军步兵在敌军指挥所格停留 2 回合」要求一个非 HQ 单位**进入**敌方 HQ 所在格。但 HQ 本身也是一个 `IUnit`（`is_hq=True`），按 INV-4 该格已被占用，攻击者无法进入。

### 5.2 候选方案

| 方案 | 说明 | 取舍 |
|------|------|------|
| A. 允许 HQ 格双占 | 围攻者与 HQ 单位同格，`get_units_at` 返回两者 | 简单，但破坏「一格一单位」直觉 |
| B. 攻击者占位、HQ 视作「建筑」不占格 | HQ 不进占用表，仅记录坐标 | 改变 HQ 作为可被攻击单位的语义 |
| C. 占领改为「相邻 2 回合」 | 攻击者无需进入 HQ 格 | 偏离 DESIGN.md 原文，需 #1 改设计 |

### 5.3 本 spec 决议

采用**方案 A**，并通过 `allow_stacking_on_hq` 开关控制（默认 True）：

- HQ 格上可同时存在：1 个 HQ 单位 + 1 个围攻方非 HQ 单位（敌方）
- 普通格仍强制单占（INV-4 修订为：「普通格至多 1 个单位；HQ 格至多 1 HQ + 1 围攻者」）
- 占领计时与打断逻辑归属 #3（`CAPTURE_INTERRUPTIBLE` / `CAPTURE_REQUIRED_TURNS` 由 #3 维护）

> ⚠️ 待确认：若 #1/#3 倾向方案 B 或 C，需更新 DESIGN.md 与本 spec。默认按方案 A 实现。

---

## 6. 模块三：`src/core/range_utils.py`

### 6.1 职责

实现 `IRangeQuery` 的具体类 `RangeQuery`：基于单位列表 + 地图，提供任意切比雪夫半径内的单位检索、最近敌人查找、敌情存在性判断。供 #3 战斗系统与侦察逻辑调用。

### 6.2 实现的接口（与 `interfaces.py:280-313` 一致）

```python
class RangeQuery(IRangeQuery):
    def __init__(self, game_map: IMap, units_provider: Callable[[], list[IUnit]]) -> None: ...

    def get_units_in_range(
        self,
        center: Coordinate,
        radius: int,
        faction: Optional[Faction] = None,
        exclude_ids: Optional[set[str]] = None,
    ) -> list[IUnit]: ...

    def find_nearest_enemy(self, unit: IUnit) -> Optional[IUnit]: ...
    def has_enemy_in_range(self, unit: IUnit, radius: int) -> bool: ...
```

### 6.3 内部数据结构

```python
class RangeQuery(IRangeQuery):
    def __init__(self, game_map: IMap, units_provider: Callable[[], list[IUnit]]) -> None:
        self._map = game_map
        self._units_provider = units_provider   # 每次调用实时拉取，保证存活单位最新
```

> 📌 DECISION：注入 `units_provider: Callable[[], list[IUnit]]`（通常绑定到 `GameLoop.get_all_units`）而非快照列表，避免持有过期引用。`GameMap` 不持有单位总表（单位生命周期由 `GameLoop` 管理），因此 RangeQuery 从外部获取单位列表。

### 6.4 `get_units_in_range`

```python
def get_units_in_range(self, center, radius, faction=None, exclude_ids=None) -> list[IUnit]:
    if radius < 0:
        return []
    exclude_ids = exclude_ids or set()
    found: list[tuple[int, str, IUnit]] = []   # (距离, unit_id, unit) 用于排序
    for u in self._units_provider():
        if not u.is_alive:
            continue
        if u.unit_id in exclude_ids:
            continue
        if faction is not None and u.faction != faction:
            continue
        dist = center.chebyshev_distance(u.position)
        if dist <= radius:
            found.append((dist, u.unit_id, u))
    # 排序：距离升序，同距按 unit_id 字典序（确定性）
    found.sort(key=lambda t: (t[0], t[1]))
    return [u for _, _, u in found]
```

**设计要点**：

- 半径语义为**切比雪夫距离**（`radius=1` 即八邻域），与 `attack_range` / `vision_range` 一致
- 返回**按距离升序**，同距按 `unit_id` 字典序，保证测试可复现
- 自动排除已阵亡单位（INV-3）

### 6.5 `find_nearest_enemy`

```python
def find_nearest_enemy(self, unit: IUnit) -> Optional[IUnit]:
    # 视野范围内最近的敌人（视野由 unit.vision_range 决定）
    enemies = self.get_units_in_range(
        center=unit.position,
        radius=unit.vision_range,
        faction=_opposite_faction(unit.faction),
        exclude_ids={unit.unit_id},
    )
    return enemies[0] if enemies else None
```

```python
def _opposite_faction(f: Faction) -> Faction:
    return Faction.ENEMY if f == Faction.FRIENDLY else Faction.FRIENDLY
```

### 6.6 `has_enemy_in_range`

```python
def has_enemy_in_range(self, unit: IUnit, radius: int) -> bool:
    return bool(self.get_units_in_range(
        center=unit.position,
        radius=radius,
        faction=_opposite_faction(unit.faction),
        exclude_ids={unit.unit_id},
    ))
```

### 6.7 边界与错误处理

| 场景 | 处理 |
|------|------|
| `radius < 0` | 返回 `[]` / False |
| `unit` 已阵亡 | 仍可查询（以坐标为准），但通常调用方先判存活 |
| 无任何匹配 | 返回 `[]` / None / False |

### 6.8 事件总线交互

无。RangeQuery 是纯查询工具。

---

## 7. 模块四：`src/core/fog_of_war.py`

### 7.1 职责

实现 `IFogOfWar` 的具体类 `FogOfWar`：视野计算、可见性查询、可见区域集合、带误差的大致坐标、友军周期性汇报调度。**计算逻辑归属 #2，UI 只读结果**（`WORKFLOW.md` §1.1 已明确）。

### 7.2 实现的接口（与 `interfaces.py:320-358` 一致）

```python
class FogOfWar(IFogOfWar):
    def is_visible_to_faction(self, coord: Coordinate, faction: Faction) -> bool: ...
    def is_unit_visible(self, unit: IUnit, to_faction: Faction) -> bool: ...
    def get_visible_area(self, faction: Faction) -> set[Coordinate]: ...
    def get_approximate_position(self, unit: IUnit) -> Coordinate: ...
    def should_report_position(self, unit: IUnit, current_turn: int) -> bool: ...
```

### 7.3 内部数据结构

```python
class FogOfWar(IFogOfWar):
    def __init__(self, game_map: IMap, units_provider: Callable[[], list[IUnit]]) -> None:
        self._map = game_map
        self._units_provider = units_provider
        # 友军汇报调度：unit_id -> 下次应汇报的回合
        self._next_report_turn: dict[str, int] = {}
        self._rng = random.Random()       # 可注入 seed 便于测试
```

### 7.4 视野计算模型（⚠️ 待确认 — 地形修正规则）

`constants.py` 中地形有两个相关字段：`vision_modifier`（观察者站在此地形看到的更远）与 `stealth_modifier`（此地形中的单位更难被发现）。本 spec 决议：

> **可见性规则**：坐标 `C` 对阵营 `F` 可见，当且仅当存在 `F` 阵营的存活单位 `U`，使得
> ```
> chebyshev(U.position, C) ≤ effective_vision(U) - stealth(C)
> ```
> 其中：
> - `effective_vision(U) = U.vision_range + vision_modifier(terrain_at(U.position))`
> - `stealth(C) = stealth_modifier(terrain_at(C))`
> - 若右侧 ≤ 0，则该 `U` 无法看到 `C`

```python
def is_visible_to_faction(self, coord: Coordinate, faction: Faction) -> bool:
    for u in self._units_provider():
        if not u.is_alive or u.faction != faction:
            continue
        eff_vision = u.vision_range + self._terrain_vision_mod(u.position)
        threshold = eff_vision - self._terrain_stealth(coord)
        if threshold >= 0 and coord.chebyshev_distance(u.position) <= threshold:
            return True
    return False

def _terrain_vision_mod(self, coord: Coordinate) -> int:
    return get_terrain_props(self._map.get_terrain(coord).value).vision_modifier

def _terrain_stealth(self, coord: Coordinate) -> int:
    return get_terrain_props(self._map.get_terrain(coord).value).stealth_modifier
```

> ⚠️ 待确认：地形对视野/隐蔽的影响规则（山地 +1 视野、森林 +1 隐蔽）`DESIGN.md` 仅粗略描述。本 spec 的「视野 - 隐蔽」模型是一种实现选择；若 #1 有更精确规则（如「森林中的单位对所有人隐蔽 +1」需同时影响友军），请明确。默认按本 spec 实现。

### 7.5 `is_unit_visible`

```python
def is_unit_visible(self, unit: IUnit, to_faction: Faction) -> bool:
    if not unit.is_alive:
        return False
    # 己方单位对己方阵营「存在可见」（位置仍可能只是大致，见 get_approximate_position）
    if unit.faction == to_faction:
        return True
    # 敌方单位需进入视野
    return self.is_visible_to_faction(unit.position, to_faction)
```

### 7.6 `get_visible_area`

```python
def get_visible_area(self, faction: Faction) -> set[Coordinate]:
    result: set[Coordinate] = set()
    observers = [u for u in self._units_provider()
                 if u.is_alive and u.faction == faction]
    for u in observers:
        eff_vision = u.vision_range + self._terrain_vision_mod(u.position)
        radius = max(0, eff_vision)            # 粗略上界；逐格再用 stealth 过滤
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                c = Coordinate(u.position.x + dx, u.position.y + dy)
                if self._map.is_within_bounds(c) and self.is_visible_to_faction(c, faction):
                    result.add(c)
    return result
```

> 性能注记：地图 20×15=300 格，每方 ≤20 单位，最坏 6000 次可见性判定/调用，可接受。若后续地图变大或频繁调用，可缓存并在单位移动时失效。

### 7.7 `get_approximate_position`（带误差汇报）

```python
def get_approximate_position(self, unit: IUnit) -> Coordinate:
    if unit.faction != Faction.FRIENDLY:
        raise ValueError("get_approximate_position 仅对 FRIENDLY 单位有效")
    r = FOG_POSITION_ERROR_RADIUS                       # = 2
    dx = self._rng.randint(-r, r)
    dy = self._rng.randint(-r, r)
    rx = _clamp(unit.position.x + dx, 0, self._map.width - 1)
    ry = _clamp(unit.position.y + dy, 0, self._map.height - 1)
    return Coordinate(rx, ry)
```

```python
def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))
```

### 7.8 友军位置汇报调度

接口只要求 `should_report_position`。汇报周期由 `FOG_POSITION_REPORT_INTERVAL_MIN/MAX`（3~5 回合）控制，需**逐单位**维护下次汇报回合。本 spec 增加两个**内部辅助方法**（不在跨层接口中，仅供 `GameLoop` 调用）：

```python
def init_report_schedule(self, unit: IUnit, current_turn: int) -> None:
    """单位创建/游戏开始时调用，安排首次汇报。"""
    self._next_report_turn[unit.unit_id] = current_turn + self._random_interval()

def should_report_position(self, unit: IUnit, current_turn: int) -> bool:
    if unit.faction != Faction.FRIENDLY or not unit.is_alive:
        return False
    return current_turn >= self._next_report_turn.get(unit.unit_id, current_turn)

def on_position_reported(self, unit: IUnit, current_turn: int) -> None:
    """GameLoop 在实际 emit POSITION_REPORT 后调用，安排下次汇报。"""
    self._next_report_turn[unit.unit_id] = current_turn + self._random_interval()

def _random_interval(self) -> int:
    return self._rng.randint(
        FOG_POSITION_REPORT_INTERVAL_MIN,
        FOG_POSITION_REPORT_INTERVAL_MAX,
    )
```

> 📌 DECISION：`should_report_position` 设计为**纯查询**（无副作用），实际推进由 `on_position_reported` 完成，避免「查询即改变状态」的隐患。`GameLoop` 在汇报阶段调用顺序：`should_report_position` → 生成 `PositionReportPayload` → `event_bus.emit` → `on_position_reported`。

### 7.9 边界与错误处理

| 场景 | 处理 |
|------|------|
| `get_approximate_position` 传入敌军 | `raise ValueError` |
| 汇报误差越界 | 钳制到地图范围 |
| 单位未注册调度 | `should_report_position` 返回 False（或当回合即触发，见实现） |
| 无任何观察者 | `is_visible_to_faction` 返回 False |

### 7.10 事件总线交互

`FogOfWar` 本身不 emit 事件。`POSITION_REPORT` 事件由 `GameLoop` 在汇报阶段组装并广播（`FogOfWar` 提供 `get_approximate_position` 的数据源）。

---

## 8. 模块五：`src/core/game_loop.py`

### 8.1 职责

实现 `IGameLoop` 与 `IGameState` 的具体类 `GameLoop`：组装地图、单位、范围检索、迷雾；驱动 8 阶段回合时序；维护回合数与游戏结果；提供只读状态查询供 #3 指令执行。

### 8.2 实现的接口

`IGameLoop`（`interfaces.py:366-403`）+ `IGameState`（`interfaces.py:487-508`）：

```python
class GameLoop(IGameLoop, IGameState):
    # ── IGameLoop ──
    def start(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def get_current_turn(self) -> int: ...
    def get_all_units(self, faction: Optional[Faction] = None) -> list[IUnit]: ...
    def get_game_result(self) -> Optional[GameResult]: ...
    def check_victory_conditions(self) -> Optional[GameResult]: ...

    # ── IGameState ──
    def get_unit_by_id(self, unit_id: str) -> Optional[IUnit]: ...
    def get_map(self) -> IMap: ...
    def get_range_query(self) -> IRangeQuery: ...
    # get_current_turn 同上
```

### 8.3 内部数据结构

```python
class GameLoop(IGameLoop, IGameState):
    def __init__(
        self,
        game_map: GameMap,
        units: list[IUnit],
        commander: ICommander | None = None,           # #3 注入（可空，CP-1 前）
        combat_resolver: Callable[[IGameState], None] | None = None,   # #3 战斗阶段钩子
        ai_decider: Callable[[IGameState], None] | None = None,        # #3 AI 阶段钩子
    ) -> None: ...

        self._map = game_map
        self._units: dict[str, IUnit] = {u.unit_id: u for u in units}
        self._commander = commander
        self._combat_resolver = combat_resolver
        self._ai_decider = ai_decider

        self._range_query = RangeQuery(game_map, self._live_units)
        self._fog = FogOfWar(game_map, self._live_units)

        self._current_turn = 0
        self._result: Optional[GameResult] = None
        self._paused = False
        self._running = False

        # 初始化所有友军汇报调度
        for u in units:
            if u.faction == Faction.FRIENDLY:
                self._fog.init_report_schedule(u, self._current_turn)

    def _live_units(self) -> list[IUnit]:
        return [u for u in self._units.values() if u.is_alive]
```

> 📌 DECISION（关键）：#2 不 import `src.battle`。#3 拥有的阶段（指令处理、战斗结算、AI 决策）通过**构造注入的可调用钩子**接入。CP-1 之前这些钩子可留空，`GameLoop` 仍能跑通「地图→单位→事件」骨架。#3 完成后将其 `Commander` / `battle_system.resolve_combat` / `ai.decide` 作为钩子注入。

### 8.4 `run_turn`：8 阶段主循环时序

对齐 `DESIGN.md` §6.1 的 8 阶段。每个 `run_turn()` 推进一回合；`start()` 循环调用直到结束。

```python
def run_turn(self) -> Optional[GameResult]:
    if self._result is not None:
        return self._result
    self._current_turn += 1

    # ── 阶段 0：回合开始 ──
    event_bus.emit(GameEventType.TURN_START, None)

    # ── 阶段 1：指令出队（#3）──
    if self._commander is not None:
        due = self._commander.process_command_queue(self._current_turn)
        for cmd in due:
            event_bus.emit(GameEventType.COMMAND_ARRIVED, ...)   # payload 由 #3 构造或此处包装

    # ── 阶段 2：AI 决策（#3）──
    if self._ai_decider is not None:
        self._ai_decider(self)

    # ── 阶段 3：移动结算 ──
    #   实际逐单位移动由 #3 的指令执行驱动；本层仅广播阶段信号。
    #   #2 负责：清除已阵亡单位的占用（map.remove_unit），保证检索一致。

    # ── 阶段 4：侦察 / 视野更新 ──
    #   迷雾为查询式，无需主动更新；此处可触发 ENEMY_SPOTTED 检测：
    self._detect_enemy_spotted()

    # ── 阶段 5：对战结算（#3）──
    if self._combat_resolver is not None:
        self._combat_resolver(self)

    # ── 阶段 6：清理阵亡单位 ──
    self._cleanup_dead_units()

    # ── 阶段 7：友军位置汇报 ──
    self._report_friendly_positions()

    # ── 阶段 8：胜负判定 ──
    self._result = self.check_victory_conditions()
    if self._result is not None:
        event_bus.emit(GameEventType.GAME_OVER, GameOverPayload(
            turn=self._current_turn,
            result=self._result.value,
            reason=self._result_reason(self._result),
        ))

    event_bus.emit(GameEventType.TURN_END, None)
    return self._result
```

```python
def start(self) -> None:
    self._running = True
    self._paused = False
    while self._running and self._result is None:
        if self._paused:
            break
        result = self.run_turn()
        if result is not None:
            break
```

### 8.5 辅助：敌情检测、清理、汇报

```python
def _detect_enemy_spotted(self) -> None:
    """对每个友军，若其视野内出现了上一回合未见到的敌人，广播 ENEMY_SPOTTED。"""
    # 简化实现：遍历友军 → find_nearest_enemy → 若存在且本次首次发现则 emit
    # 完整「首次发现」需维护已发现集合；CP-1 可用简化版，CP-2 补全。
    ...

def _cleanup_dead_units(self) -> None:
    for u in list(self._units.values()):
        if not u.is_alive:
            self._map.remove_unit(u)
            if self._commander is not None:
                self._commander.cancel_all_commands(u.unit_id)

def _report_friendly_positions(self) -> None:
    for u in self._live_units():
        if u.faction != Faction.FRIENDLY:
            continue
        if self._fog.should_report_position(u, self._current_turn):
            approx = self._fog.get_approximate_position(u)
            has_enemy = self._range_query.has_enemy_in_range(u, u.vision_range)
            enemy_info = ""  # #3 或此处根据 find_nearest_enemy 生成简述
            event_bus.emit(GameEventType.POSITION_REPORT, PositionReportPayload(
                turn=self._current_turn,
                unit_id=u.unit_id,
                unit_name=u.name,
                reported_x=approx.x,
                reported_y=approx.y,
                has_enemy_nearby=has_enemy,
                enemy_info=enemy_info,
            ))
            self._fog.on_position_reported(u, self._current_turn)
```

### 8.6 `check_victory_conditions`

```python
def check_victory_conditions(self) -> Optional[GameResult]:
    if self._result is not None:
        return self._result
    friendly_alive = any(u.is_alive and u.faction == Faction.FRIENDLY
                         and not u.is_hq is False   # HQ 也算存活单位
                         for u in self._units.values())
    # 简化：以「该阵营是否有存活非 HQ 战斗单位或 HQ」判定
    friendly_units = [u for u in self._units.values()
                      if u.faction == Faction.FRIENDLY and u.is_alive]
    enemy_units = [u for u in self._units.values()
                   if u.faction == Faction.ENEMY and u.is_alive]
    friendly_hq_alive = any(u.is_hq for u in friendly_units)
    enemy_hq_alive = any(u.is_hq for u in enemy_units)

    # 失败：己方全军覆没（含 HQ 阵亡）或指挥所沦陷（由 #3 通过 HQ_CAPTURED 置位）
    if not friendly_units:
        return GameResult.DEFEAT
    if not enemy_units:
        return GameResult.VICTORY
    if self._current_turn >= MAX_TURNS:
        return GameResult.DRAW
    return None
```

> ⚠️ 待确认：HQ 被占领的胜负判定。占领逻辑（`CAPTURE_REQUIRED_TURNS=2`）归属 #3。本 spec 决议：#3 在占领完成时 emit `HQ_CAPTURED` 事件，`GameLoop` 订阅该事件并据此置 `self._result`（敌占我 HQ → DEFEAT，我占敌 HQ → VICTORY）。`check_victory_conditions` 内不重复判定占领，只判定「全歼」与「回合上限」。**若 #1 认为占领判定应在底层，需重新分配职责。**

```python
# GameLoop.__init__ 中订阅：
event_bus.subscribe(GameEventType.HQ_CAPTURED, self._on_hq_captured)

def _on_hq_captured(self, payload: HqCapturedPayload) -> None:
    if payload.capturer_faction == Faction.FRIENDLY.value:
        self._result = GameResult.VICTORY
    else:
        self._result = GameResult.DEFEAT
```

### 8.7 `IGameState` 查询

```python
def get_unit_by_id(self, unit_id: str) -> Optional[IUnit]:
    return self._units.get(unit_id)

def get_map(self) -> IMap:
    return self._map

def get_range_query(self) -> IRangeQuery:
    return self._range_query
```

### 8.8 `pause` / `resume`

```python
def pause(self) -> None:
    self._paused = True

def resume(self) -> None:
    self._paused = False
```

> 📌 DECISION：`start()` 是**阻塞式回合循环**（CP-1 命令行模式用）。GUI 模式下（#4），#4 不调用 `start()`，而是每帧/每用户操作调用一次 `run_turn()`，由 #4 控制节奏。两种模式共用同一个 `run_turn`。

### 8.9 边界与错误处理

| 场景 | 处理 |
|------|------|
| 游戏已结束时再 `run_turn` | 直接返回 `_result`，不推进回合 |
| 钩子为 None（#3 未接入） | 跳过该阶段，不报错 |
| 钩子内抛异常 | 由 EventBus / 调用方捕获；#3 钩子应自保护 |
| 单位 `unit_id` 重复 | 构造时 `raise ValueError` |

### 8.10 事件总线交互

`GameLoop` 是事件**主要生产者**之一：emit `TURN_START` / `TURN_END` / `POSITION_REPORT` / `GAME_OVER`（及简化的 `ENEMY_SPOTTED`）。同时**订阅** `HQ_CAPTURED` 以更新胜负。事件载荷严格使用 `constants.py` 中定义的 dataclass。

---

## 9. 测试计划（`tests/core/`）

> 文件组织遵循 `WORKFLOW.md` §7.2。最低 5 条（WORKFLOW 要求），本 spec 给出 18 条建议，覆盖各模块关键路径与边界。

### 9.1 `tests/core/test_unit_base.py`

| # | 测试 | 覆盖 |
|:--:|------|------|
| U1 | `take_damage` 正常扣血，返回值 = 实际扣血 | §3.4 |
| U2 | `take_damage` 把血量打到 0 → `is_alive=False` | §3.4 |
| U3 | 对已阵亡单位 `take_damage` 返回 0，幂等 | §3.4 |
| U4 | `defense` 属性含地形加成（站在山地 +2） | §3.5 |
| U5 | `can_attack`：同阵营/超距/HQ 攻击均返回 False | §3.8 |

### 9.2 `tests/core/test_map.py`

| # | 测试 | 覆盖 |
|:--:|------|------|
| M1 | `is_within_bounds` / 越界 `get_terrain` 抛 ValueError | §4.5 |
| M2 | 河流 `is_passable=False`，`get_move_cost=-1` | §4.5 |
| M3 | `place_unit` 到已占普通格返回 False；HQ 格允许双占 | §4.6, §5.3 |
| M4 | `find_path` 平原直达；遇河流绕行 | §4.8 |
| M5 | `find_path` 目标超出 `max_steps` 返回 `[]` | §4.8 |

### 9.3 `tests/core/test_range.py`

| # | 测试 | 覆盖 |
|:--:|------|------|
| R1 | `get_units_in_range` 半径=1 返回八邻域单位，按距离排序 | §6.4 |
| R2 | `faction` 过滤：只返回指定阵营 | §6.4 |
| R3 | `find_nearest_enemy` 返回视野内最近敌人；无敌人返回 None | §6.5 |

### 9.4 `tests/core/test_fog.py`

| # | 测试 | 覆盖 |
|:--:|------|------|
| F1 | 友军在视野半径内 → `is_visible_to_faction=True`；移出 → False | §7.4 |
| F2 | 森林中敌人（stealth+1）需更近才可见 | §7.4 |
| F3 | `get_approximate_position` 误差在 ±`FOG_POSITION_ERROR_RADIUS` 内且在地图范围 | §7.7 |
| F4 | `should_report_position` 按 3~5 回合周期触发；汇报后下次周期重置 | §7.8 |
| F5 | `get_approximate_position` 传入敌军抛 ValueError | §7.9 |

### 9.5 `tests/core/test_event_bus.py`（event_bus 已实现，补回归）

| # | 测试 | 覆盖 |
|:--:|------|------|
| E1 | subscribe → emit → 回调被调用，次数正确 | event_bus.py |
| E2 | 回调抛异常不影响其他回调 | event_bus.py |

### 9.6 集成冒烟（移交 #5 放 `tests/integration/`）

| # | 测试 | 覆盖 |
|:--:|------|------|
| S1 | 加载 `map_01.json` → 创建双方单位 → 跑 1 回合 → `TURN_START`/`TURN_END` 各一次 | §8.4 |

> 所有测试不得 import `src.battle` 或 `src.ui`（验证三层隔离）。

---

## 10. 与 #3 / #4 的契约要点（待评审确认汇总）

本 spec 做出的、需要跨层确认的决议集中如下，供评审一次性决策：

| 编号 | 决议 | 影响方 | 默认方案 |
|:----:|------|:----:|----------|
| C-1 | `take_damage` 是纯扣血原语，伤害公式（含防御/克制/地形）归 #3 | #3 | 按 §3.4 |
| C-2 | `attack_target` 默认实现只含 `max(1, atk-def)`，克制/反击/先手归 #3 | #3 | 按 §3.7 |
| C-3 | `defense` 属性含地形加成，由 #2 计算 | #3 | 按 §3.5 |
| C-4 | HQ 格允许「HQ 单位 + 1 围攻者」双占 | #1, #3 | 方案 A，§5.3 |
| C-5 | 视野/隐蔽地形修正采用「eff_vision - stealth」模型 | #1 | 按 §7.4 |
| C-6 | 占领胜负由 #3 emit `HQ_CAPTURED`，#2 订阅置位 | #1, #3 | 按 §8.6 |
| C-7 | `move_to` 全或无语义（未抵达 target 不部分移动） | #3 | 按 §3.6 |
| C-8 | `GameLoop` 通过钩子接入 #3 的指令/战斗/AI 阶段 | #3, #5 | 按 §8.3 |

---

## 11. 开发顺序与里程碑对齐

| Sprint | 本 spec 产出 | 对齐 Checkpoint | 验收 |
|:------:|-------------|:---:|------|
| Sprint 1 (Day 3-7) | `unit_base.py` + `map.py` + `range_utils.py` + 对应测试 | CP-1 | 命令行：加载地图 → 创建单位 → `get_units_in_range` → `find_path` 可用 |
| Sprint 2 (Day 9-14) | `fog_of_war.py` + `game_loop.py` + 对应测试 | CP-2 | `GameLoop.run_turn()` 跑通，`POSITION_REPORT` / `TURN_START` 事件按预期 emit |
| Sprint 3 (Day 16-20) | 性能优化、边界补全、配合 #5 联调 | CP-3 | mypy --strict 通过，pytest 全绿 |

---

## 12. 变更记录

| 版本 | 日期 | 作者 | 变更 |
|:----:|:----:|:----:|------|
| v1.0-draft | 2026-07-07 | #2 | 初稿，覆盖 5 个模块 + 跨层契约 8 项 |
| v1.1 | 2026-07-08 | #2 | Sprint 2 完成：CP-2 敌情首次发现追踪 + GameLoop 动态单位注册 + 测试补全（+8 条） |

---

> **本 spec 与 `interfaces.py` / `constants.py` 共同构成 #2 的开发依据。`interfaces.py` 为唯一接口事实来源；本 spec 描述「如何实现」。任何与 `interfaces.py` 的冲突以接口文件为准，并提 PR 修正本 spec。**
