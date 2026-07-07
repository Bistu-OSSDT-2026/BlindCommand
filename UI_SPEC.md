# BlindCommand UI 层技术规格说明书

> **版本**: v1.0  
> **负责**: #4 — UI 与可视化 Vibe 程序员  
> **依赖**: #2 IFogOfWar / IMap 接口 · #3 事件广播  
> **约束**: 只订阅 EventBus + 调用 #2 查询接口，不修改游戏数据  
> **最后更新**: 2026-07-07

---

## 目录

1. [概述与职责边界](#1-概述与职责边界)
2. [组件树与文件结构](#2-组件树与文件结构)
3. [主窗口布局规范](#3-主窗口布局规范)
4. [组件详细规格](#4-组件详细规格)
   - 4.1 BattleLogPanel — 战报面板
   - 4.2 MapWidget — 地图渲染
   - 4.3 CommandPanel — 指令面板
   - 4.4 MarkerSystem — 标记系统
   - 4.5 FogRenderer — 迷雾视觉效果
5. [事件订阅映射表](#5-事件订阅映射表)
6. [渲染管线](#6-渲染管线)
7. [状态管理](#7-状态管理)
8. [数据流图](#8-数据流图)
9. [Sprint 分阶段交付计划](#9-sprint-分阶段交付计划)
10. [接口依赖清单](#10-接口依赖清单)
11. [资源文件需求](#11-资源文件需求)
12. [测试策略](#12-测试策略)

---

## 1. 概述与职责边界

### 1.1 UI 层的定位

```
#3 业务层（事件生产者）              #4 UI层（事件消费者）
┌──────────────┐                    ┌──────────────┐
│ 战斗结算完成  │ ────广播────▶     │ 战报面板更新  │
│ 单位阵亡     │ ────广播────▶     │ 阵亡提示显示  │
│ 遭遇敌军     │ ────广播────▶     │ 遇敌文本打印  │
│ 占领指挥所   │ ────广播────▶     │ 胜利画面切换  │
│ 指令已发出   │ ────广播────▶     │ 指令状态提示  │
│ 位置汇报     │ ────广播────▶     │ 迷雾区域更新  │
└──────────────┘                    └──────────────┘

                                     │
                         调用查询接口  │
                                     ▼
                          ┌──────────────────┐
                          │  #2 IFogOfWar     │
                          │  is_visible_to_   │
                          │  faction()        │
                          │  get_visible_area │
                          └──────────────────┘
```

### 1.2 硬约束（违反则 CI 拦截）

| # | 约束 | 说明 |
|:--:|------|------|
| C1 | **禁止** `import src.battle` | 不能碰 #3 代码 |
| C2 | **禁止** `import src.core` 内部实现模块 | 只允许 `interfaces` / `constants` / `event_bus` |
| C3 | **禁止** 直接读写任何 Unit 实例属性 | 只通过 IUnit 接口读取只读属性 |
| C4 | **禁止** 直接修改地图数据 | 地图只读查询 |
| C5 | 所有游戏状态变化**只能**通过 EventBus 获知 | 不轮询、不主动刷新 |

---

## 2. 组件树与文件结构

### 2.1 文件清单

```
src/ui/
├── __init__.py
├── main_window.py      # 主窗口 — 组装所有子面板，持有 pygame Surface 和 UIManager
├── battle_log.py       # 战报面板 — 订阅 EventBus，UITextBox 追加消息
├── map_widget.py       # 地图渲染 — pygame.Surface 瓦片渲染 + 单位精灵
├── command_panel.py    # 指令面板 — UIDropDownMenu + UIButton
├── marker.py           # 标记系统 — 鼠标拖拽方块（Sprint 2）
├── fog_renderer.py     # 迷雾渲染 — 半透明遮罩层（Sprint 2）
└── assets/             # 图片素材（#5 负责维护）
    ├── terrain/
    │   ├── plain.png
    │   ├── forest.png
    │   ├── mountain.png
    │   ├── river.png
    │   ├── hq.png
    │   └── bridge.png
    └── units/
        ├── infantry_blue.png
        ├── cavalry_blue.png
        ├── artillery_blue.png
        ├── scout_blue.png
        ├── hq_blue.png
        ├── infantry_red.png
        ├── cavalry_red.png
        ├── artillery_red.png
        ├── scout_red.png
        └── hq_red.png
```

### 2.2 组件树

```
MainWindow (pygame 主循环)
├── UIManager (pygame_gui 全局管理器)
│
├── BattleLogPanel (左 28%)
│   └── pygame_gui.UITextBox
│       └── HTML 格式化战报条目
│
├── MapWidget (中 72% 上部)
│   ├── TerrainLayer        — 地形瓦片 blit
│   ├── UnitSpriteLayer     — 单位方块（蓝/红）
│   ├── MarkerLayer         — 玩家标记（半透明拖拽方块）[Sprint 2]
│   └── FogOverlay          — 迷雾遮罩（半透明黑色）[Sprint 2]
│
└── CommandPanel (底部 80px)
    ├── UIDropDownMenu — 指令类型选择
    ├── UIDropDownMenu — 目标单位选择
    ├── UITextEntry × 2 — 坐标输入 (x, y)
    └── UIButton — 执行按钮
```

---

## 3. 主窗口布局规范

### 3.1 布局计算（main_window.py 现有 calculate_layout() 保留）

```
┌──────────────┬────────────────────────────────────────┐
│ 战报面板      │              地图区域                  │  ← 0
│ (28%)        │            (72%)                       │
│              │                                        │
│ BATTLE_LOG   │              MAP_AREA                  │
│ WIDTH_RATIO  │            WIDTH_RATIO                 │
│ = 0.28       │             = 0.72                     │
│              │                                        │
│              │                                        │
│              │                                        │
├──────────────┴────────────────────────────────────────┤  ← window_h - 80
│  指令栏 (COMMAND_PANEL_HEIGHT = 80px)                  │
└───────────────────────────────────────────────────────┘
```

### 3.2 面板矩形计算（像素）

```python
battle_log_rect = Rect(0, 0, int(W * 0.28), H - 80)
map_rect        = Rect(int(W * 0.28), 0, W - int(W * 0.28), H - 80)
command_rect    = Rect(0, H - 80, W, 80)
```

### 3.3 与 Phase 0 骨架的区别

| Phase 0 骨架 | Sprint 1 替换为 |
|-------------|----------------|
| 灰色占位矩形 + 文字 | BattleLogPanel（真实 UITextBox） |
| 灰色占位矩形 + 文字 | MapWidget（地形瓦片 + 单位方块） |
| 灰色占位矩形 + 文字 | CommandPanel（真实按钮和下拉菜单） |

---

## 4. 组件详细规格

---

### 4.1 BattleLogPanel — 战报面板

**文件**: `src/ui/battle_log.py`  
**Sprint**: 1  
**依赖**: `pygame_gui.UITextBox` · `event_bus` · 所有事件载荷类型

#### 4.1.1 功能

- 左侧滚动文本区域，逐条显示战场事件
- 最新消息自动追加到底部并滚动
- 不同事件类型使用不同颜色（HTML 标记）
- 保留历史记录（最多 `BATTLE_LOG_MAX_LINES = 500` 条）

#### 4.1.2 颜色映射

| 事件类型 | 颜色 | 常量 |
|---------|------|------|
| 友军报告 / 正常消息 | `#CCCCCC` 白 | `BATTLE_LOG_TEXT_COLOR` |
| 重要事件（遇敌、占领、游戏结束） | `#FFD700` 金 | `BATTLE_LOG_HIGHLIGHT_COLOR` |
| 危险事件（阵亡、大败、HQ受袭） | `#FF4444` 红 | `BATTLE_LOG_DANGER_COLOR` |

#### 4.1.3 事件 → 战报文本格式

```python
# 事件 → (颜色常量, 格式模板)
BATTLE_LOG_FORMATS = {
    GameEventType.TURN_START:    (HIGHLIGHT,  "━━━ 第 {turn} 回合 ━━━"),
    GameEventType.POSITION_REPORT: (NORMAL,  "[第{payload.turn}回合] {payload.unit_name} 汇报：位置约({payload.reported_x}, {payload.reported_y})"),
    GameEventType.ENEMY_SPOTTED: (HIGHLIGHT, "[第{payload.turn}回合] {payload.reporter_name} 发现敌军 {payload.enemy_type}×{payload.enemy_count} ！"),
    GameEventType.BATTLE_RESULT:  (NORMAL,  "[第{payload.turn}回合] {payload.attacker_name} 攻击 {payload.defender_name}，造成 {payload.damage_to_defender} 伤害"),
    GameEventType.UNIT_DAMAGED:   (NORMAL,  "[第{payload.turn}回合] {payload.unit_name} 受到 {payload.damage} 伤害 (HP: {payload.hp_before}→{payload.hp_after})"),
    GameEventType.UNIT_KILLED:    (DANGER,  "[第{payload.turn}回合] 💀 {payload.unit_name} 阵亡！被 {payload.killer_name} 击杀"),
    GameEventType.COMMAND_SENT:   (NORMAL,  "[第{payload.turn}回合] 📨 指令已发出：{payload.target_unit_name} → {payload.command_type}，预计 {payload.estimated_arrival_turn} 回合到达"),
    GameEventType.COMMAND_ARRIVED:(NORMAL,  "[第{payload.turn}回合] 📬 指令已到达 {payload.target_unit_name}：{payload.command_type}"),
    GameEventType.COMMAND_EXPIRED:(NORMAL,  "[第{payload.turn}回合] ⚠ 指令作废"),
    GameEventType.HQ_UNDER_ATTACK:(DANGER,  "[第{payload.turn}回合] 🚨 指挥所遭受攻击！"),
    GameEventType.HQ_CAPTURED:    (HIGHLIGHT,"[第{payload.turn}回合] 🏆 {payload.capturer_name} 占领指挥所！"),
    GameEventType.GAME_OVER:      (HIGHLIGHT,"[第{payload.turn}回合] 游戏结束：{payload.reason} — {payload.result}"),
}
```

#### 4.1.4 类接口

```python
class BattleLogPanel:
    """左侧战报面板。订阅 EventBus，以 HTML 格式追加消息。"""

    def __init__(self, rect: pygame.Rect, ui_manager: pygame_gui.UIManager):
        """创建 UITextBox 并订阅所有事件。"""
        ...

    def subscribe_all(self) -> None:
        """批量订阅 12 种事件。每个回调调用 _append()。"""
        ...

    def _append(self, text: str, color: str = BATTLE_LOG_TEXT_COLOR) -> None:
        """追加一条 HTML 格式消息并自动滚动到底部。"""
        ...

    def clear(self) -> None:
        """清空所有内容（新游戏开始时调用）。"""
        ...

    def update(self, time_delta: float) -> None:
        """每帧调用 pygame_gui 更新。"""
        ...
```

---

### 4.2 MapWidget — 地图渲染

**文件**: `src/ui/map_widget.py`  
**Sprint**: 1  
**依赖**: `IMap` 接口 · `IFogOfWar` 接口 · 地形图片素材

#### 4.2.1 渲染分层（由底到顶）

```
层 0: 地形瓦片 (TerrainLayer)
       └─ 根据 TerrainType 枚举 → 对应 .png 图片 → blit
       不可通行格（河流）→ 叠加红色 X 标记（可选）

层 1: 单位精灵 (UnitSpriteLayer)
       └─ 存活单位 → 阵营颜色方块（蓝=友军 / 红=敌军）
       方块上绘制兵种简写（Inf/Cav/Art/Sct/HQ）
       只渲染对当前阵营可见的单位（调用 is_unit_visible）

层 2: 玩家标记 (MarkerLayer) [Sprint 2]
       └─ 半透明方块（蓝/红/金/白）
       拖拽放置、右键删除

层 3: 迷雾遮罩 (FogOverlay) [Sprint 2]
       └─ 对不可见格绘制半透明黑色遮罩
       FOG_ALPHA=180 的黑色 Surface
```

#### 4.2.2 瓦片渲染算法

```python
def render_terrain_layer(
    surface: pygame.Surface,
    map_data: IMap,
    tile_size: int = TILE_SIZE
) -> None:
    """逐格渲染地形瓦片。

    对于每个 (col, row):
        1. terrain = map_data.get_terrain(Coordinate(col, row))
        2. tile_surf = TERRAIN_CACHE[terrain]  # 预加载缓存
        3. surface.blit(tile_surf, (col * TILE_SIZE, row * TILE_SIZE))
    """
    ...
```

#### 4.2.3 单位渲染算法

```python
def render_unit_layer(
    surface: pygame.Surface,
    game_loop: IGameLoop,       # 获取所有单位
    fog: IFogOfWar,             # 判断可见性
    player_faction: Faction,
    tile_size: int = TILE_SIZE
) -> None:
    """渲染可见的单位。

    对于每个存活单位:
        1. if fog.is_unit_visible(unit, player_faction):
        2.     rect = (x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE)
        3.     color = COLOR_FRIENDLY if friendly else COLOR_ENEMY
        4.     pygame.draw.rect(surface, color, rect, border_radius=4)
        5.     render_unit_label(surface, unit, rect)  # 兵种简写
    """
    ...
```

#### 4.2.4 类接口

```python
class MapWidget:
    """中央地图渲染组件。"""

    def __init__(self, rect: pygame.Rect):
        """创建地图 Surface。"""
        self.surface = pygame.Surface((rect.width, rect.height))
        self.rect = rect
        self.tile_cache: dict[TerrainType, pygame.Surface] = {}
        self._load_tile_images()

    def set_map(self, map_data: IMap) -> None:
        """绑定地图数据源。"""
        ...

    def set_fog(self, fog: IFogOfWar) -> None:
        """绑定迷雾查询接口。"""
        ...

    def render(self, game_loop: IGameLoop, player_faction: Faction) -> None:
        """完整渲染一帧（所有层）。"""
        ...

    def draw(self, screen: pygame.Surface) -> None:
        """将渲染结果 blit 到主屏幕。"""
        screen.blit(self.surface, self.rect.topleft)

    def pixel_to_coord(self, px: int, py: int) -> Coordinate | None:
        """像素坐标 → 地图坐标（用于鼠标点击定位）。"""
        ...
```

---

### 4.3 CommandPanel — 指令面板

**文件**: `src/ui/command_panel.py`  
**Sprint**: 1（骨架）→ Sprint 2（完整交互）  
**依赖**: `pygame_gui.UIDropDownMenu` · `pygame_gui.UIButton` · `pygame_gui.UITextEntry`

#### 4.3.1 布局

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [指令类型 ▼]  [目标单位 ▼]  坐标X: [__]  Y: [__]  [🚀 执行指令]        │
│  MOVE         第一步兵连                                                 │
│  ATTACK       第二步兵连                                                 │
│  HOLD         第一骑兵连                                                 │
│  SCOUT        第一炮兵连                                                 │
│  RETREAT      侦察排                                                    │
│  CAPTURE                                                                │
│  PATROL                                                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 4.3.2 交互流程

```
选择指令类型 → 选择目标单位 → 可选：输入坐标参数 → 点击 [执行]
                                                         │
                                                         ▼
                                              调用 ICommander.issue_command()
                                              （但此时 UI 层不直接调用 ICommander！
                                                而是通过事件总线发消息给 #3）
```

**注意**: Sprint 1 的指令面板为纯 UI 骨架（展示布局、下拉菜单可展开、按钮可点击打印日志），实际指令下达逻辑在 Sprint 2 由 #3 的 ICommander 接口完成后对接。

#### 4.3.3 类接口

```python
class CommandPanel:
    """底部指令选择栏。"""

    def __init__(self, rect: pygame.Rect, ui_manager: pygame_gui.UIManager):
        """创建下拉菜单、输入框、执行按钮。"""
        ...

    def set_available_units(self, units: list[dict]) -> None:
        """更新可选单位列表（由 POSITION_REPORT 事件触发）。"""
        ...

    def on_execute_clicked(self) -> None:
        """执行按钮回调。校验参数 → 发送 COMMAND_REQUEST 事件。"""
        ...

    def update(self, time_delta: float) -> None:
        """每帧调用 pygame_gui 更新。"""
        ...
```

---

### 4.4 MarkerSystem — 标记系统 [Sprint 2]

**文件**: `src/ui/marker.py`  
**Sprint**: 2  
**依赖**: `pygame.mouse` · `MarkerType` 枚举 · `TILE_SIZE`

#### 4.4.1 标记数据模型

```python
@dataclass
class Marker:
    marker_id: str
    marker_type: MarkerType   # FRIENDLY_GUESS / ENEMY_GUESS / HQ_GUESS / CUSTOM_NOTE
    coord: Coordinate         # 地图坐标（非像素）
    label: str = ""           # 自定义备注文字（仅 CUSTOM_NOTE 使用）
```

#### 4.4.2 交互行为

| 操作 | 触发 | 效果 |
|------|------|------|
| 放置标记 | 从调色板拖拽到地图格 | 创建 Marker，吸附到最近格子中心 |
| 移动标记 | 左键拖拽已有标记 | 更新 Marker.coord |
| 删除标记 | 右键点击标记 | 移除 Marker |
| 切换类型 | 点击标记 + 按数字键 1-4 | 切换 MarkerType |

#### 4.4.3 渲染

```python
MARKER_COLORS = {
    MarkerType.FRIENDLY_GUESS: COLOR_MARKER_FRIENDLY,  # 半透明蓝 #4488FF80
    MarkerType.ENEMY_GUESS:    COLOR_MARKER_ENEMY,     # 半透明红 #FF444480
    MarkerType.HQ_GUESS:       COLOR_MARKER_HQ,        # 半透明金 #FFD70080
    MarkerType.CUSTOM_NOTE:    COLOR_MARKER_NOTE,      # 半透明白 #FFFFFF80
}
```

---

### 4.5 FogRenderer — 迷雾视觉效果 [Sprint 2]

**文件**: `src/ui/fog_renderer.py`  
**Sprint**: 2  
**依赖**: `IFogOfWar` 接口

#### 4.5.1 渲染逻辑

```python
def render_fog_overlay(
    surface: pygame.Surface,
    fog: IFogOfWar,
    player_faction: Faction,
    map_width: int,
    map_height: int,
    tile_size: int = TILE_SIZE
) -> None:
    """在不可见区域绘制半透明黑色遮罩。

    对于每个格子 (col, row):
        coord = Coordinate(col, row)
        if not fog.is_visible_to_faction(coord, player_faction):
            fog_rect = (col * tile_size, row * tile_size, tile_size, tile_size)
            pygame.draw.rect(surface, (0, 0, 0, FOG_ALPHA), fog_rect)
    """
    ...
```

#### 4.5.2 "大致位置"效果

当友军汇报位置时（POSITION_REPORT 事件），在汇报坐标周围显示一个半透明区域圈（半径 `FOG_APPROXIMATE_RADIUS = 3` 格），表示"友军大致在此区域"。

---

## 5. 事件订阅映射表

### 5.1 完整映射

| EventBus 事件 | 载荷 | 订阅者 | 处理逻辑 |
|:---|---|:---:|---|
| `TURN_START` | None | BattleLogPanel | 追加回合分隔线 |
| `TURN_END` | None | — | （预留） |
| `BATTLE_RESULT` | BattleResultPayload | BattleLogPanel | 追加战斗结算消息 |
| `UNIT_DAMAGED` | UnitDamagedPayload | BattleLogPanel | 追加受伤消息 |
| `UNIT_KILLED` | UnitKilledPayload | BattleLogPanel | 追加阵亡消息（红色） |
| `ENEMY_SPOTTED` | EnemySpottedPayload | BattleLogPanel | 追加遇敌消息（金色） |
| `HQ_CAPTURED` | HqCapturedPayload | BattleLogPanel | 追加占领消息（金色） |
| `HQ_UNDER_ATTACK` | None | BattleLogPanel | 追加告警消息（红色） |
| `COMMAND_SENT` | CommandSentPayload | BattleLogPanel | 追加指令发出消息 |
| `COMMAND_ARRIVED` | CommandArrivedPayload | BattleLogPanel | 追加指令到达消息 |
| `COMMAND_EXPIRED` | None | BattleLogPanel | 追加指令作废消息 |
| `POSITION_REPORT` | PositionReportPayload | BattleLogPanel + FogRenderer | 追加汇报 + 更新大致位置 |
| `GAME_OVER` | GameOverPayload | BattleLogPanel + MapWidget | 追加结局 + 显示全图 |

### 5.2 订阅代码模板

```python
from src.core.event_bus import event_bus
from src.core.constants import GameEventType

# 订阅示例
def on_battle_result(payload: BattleResultPayload) -> None:
    """战斗结算 → 更新战报"""
    self.battle_log.append_battle_result(payload)

event_bus.subscribe(GameEventType.BATTLE_RESULT, on_battle_result)
```

---

## 6. 渲染管线

### 6.1 每帧渲染顺序

```
MainWindow.update()
│
├─ 1. pygame.event.get() 处理输入事件
│     ├─ pygame_gui 事件 → UIManager.process_events()
│     └─ 鼠标/键盘事件 → MapWidget / MarkerSystem 处理
│
├─ 2. 渲染
│     ├─ screen.fill(COLOR_BG)
│     │
│     ├─ MapWidget.render(game_loop, faction)
│     │     ├─ TerrainLayer blit（全量）
│     │     ├─ UnitSpriteLayer blit（可见单位）
│     │     ├─ MarkerLayer blit（所有标记）[Sprint 2]
│     │     └─ FogOverlay blit（不可见格遮罩）[Sprint 2]
│     │
│     └─ UIManager.draw_ui(screen)
│           ├─ BattleLogPanel (UITextBox)
│           └─ CommandPanel (Buttons, DropDowns)
│
└─ 3. pygame.display.flip()
```

### 6.2 帧率

```
游戏主循环:       30 FPS (clock.tick(30))
UI 事件响应:       实时（pygame 事件驱动）
地图重绘:         每帧（除非实现脏矩形优化）
战报追加:          事件驱动（仅在收到事件时更新 UITextBox）
```

---

## 7. 状态管理

### 7.1 UI 状态机

```
                    ┌─────────┐
        游戏启动 →  │  LOBBY  │  等待 #2 #3 初始化
                    └────┬────┘
                         │ GameLoop.start()
                         ▼
                    ┌─────────┐
              ┌────▶│ PLAYING │  正常游戏流程
              │     └────┬────┘
              │          │ GAME_OVER 事件
              │          ▼
              │     ┌─────────┐
              │     │GAME_END │  显示结局
              │     └────┬────┘
              │          │ 用户点击"再来一局"
              └──────────┘
```

### 7.2 UI 持有的状态

```python
@dataclass
class UIState:
    """UI 层持有的只读状态快照。"""
    current_turn: int = 0
    player_faction: Faction = Faction.FRIENDLY
    units_visible: list[IUnit] = field(default_factory=list)  # 当前可见单位
    markers: list[Marker] = field(default_factory=list)       # 玩家标记 [Sprint 2]
    game_result: GameResult | None = None
```

> ⚠️ **状态不是事实来源**。战斗中状态以 #2 GameLoop 为准，UI 只是事件驱动的快照缓存。

---

## 8. 数据流图

```
                        ┌──────────────────────────┐
                        │         #2 底层           │
                        │  GameLoop · Map · Units   │
                        │  FogOfWar · RangeQuery    │
                        └──┬───────────┬────────────┘
                           │           │
             实现接口      │           │ 调用接口
                           ▼           ▼
                        ┌──────────┐  ┌──────────────┐
                        │  #3 业务  │  │   #4 UI      │
                        │ battle   │  │              │
                        │ commander│  │ IFogOfWar ◀──│── 查询迷雾
                        └────┬─────┘  │ IMap ◀───────│── 查询地形
                             │        │ IUnit ◀──────│── 读取单位属性(只读)
                             │ emit   │              │
                             │        │ event_bus ◀──│── 监听事件
                             ▼        └──────────────┘
                        ┌──────────────────┐
                        │    EventBus      │
                        │  (全局单例)      │
                        └──────────────────┘
```

---

## 9. Sprint 分阶段交付计划

### Sprint 1 (Day 3-7) — 战报面板 + 地图渲染原型

| 文件 | 功能 | 验收标准 |
|------|------|----------|
| `battle_log.py` | UITextBox + 事件订阅 | 能显示硬编码模拟事件消息，自动滚动 |
| `map_widget.py` | 地形瓦片渲染（使用占位色块）+ 单位方块 | 能根据 map_01.json 渲染 20×15 地图 |
| `command_panel.py` | UI 骨架（下拉菜单 + 按钮） | 菜单可展开、按钮可点击（打印日志即可） |
| `main_window.py` | 整合三个面板 | 替换 Phase 0 骨架，面板正确布局 |

**Sprint 1 里程碑**: 启动 `python -m src.main` 后能看到左侧战报滚动、中间地图有色块、底部指令面板有按钮。

### Sprint 2 (Day 9-14) — 标记拖拽 + 迷雾 + 指令对接

| 文件 | 功能 | 验收标准 |
|------|------|----------|
| `marker.py` | 鼠标拖拽标记方块 | 从调色板拖拽到地图，吸附格子，右键删除 |
| `fog_renderer.py` | 迷雾遮罩 + 大致位置高亮 | 未探索区域半透明黑色，友军汇报区域高亮 |
| `command_panel.py` | 对接 ICommander 事件 | 选择指令→点击执行→事件广播 |
| `battle_log.py` | 对接真实事件 | 接收 #3 事件后正确显示所有消息类型 |
| `map_widget.py` | 真实图片渲染 + 可见性过滤 | 加载 .png 素材，只渲染可见单位 |

**Sprint 2 里程碑**: GUI 完整可玩 — 能看到迷雾、能拖标记、能下达指令、能看真实战报。

### Sprint 3 (Day 16-20) — 打磨

- Bug 修复
- 性能优化（脏矩形、图片缓存）
- 视觉打磨（动画、音效、过渡效果）

---

## 10. 接口依赖清单

### 10.1 编译时依赖（import）

```python
# ── 允许的 import ─────────────────────────────────────────────
from src.core import (
    # 枚举
    Faction, UnitType, TerrainType, GameEventType, MarkerType,
    GameResult, CommandType, Direction,
    # 数据类
    Coordinate, UnitStats,
    # 事件载荷
    BattleResultPayload, UnitKilledPayload, UnitDamagedPayload,
    EnemySpottedPayload, HqCapturedPayload, CommandSentPayload,
    CommandArrivedPayload, GameOverPayload, PositionReportPayload,
    # 接口（只读查询）
    IUnit, IMap, IFogOfWar, IGameLoop, IGameState,
    # UI 常量
    WINDOW_WIDTH, WINDOW_HEIGHT, TILE_SIZE,
    BATTLE_LOG_WIDTH_RATIO, MAP_AREA_WIDTH_RATIO, COMMAND_PANEL_HEIGHT,
    COLOR_FRIENDLY, COLOR_ENEMY, COLOR_FRIENDLY_FAINT, COLOR_ENEMY_FAINT,
    COLOR_MARKER_FRIENDLY, COLOR_MARKER_ENEMY, COLOR_MARKER_HQ, COLOR_MARKER_NOTE,
    BATTLE_LOG_MAX_LINES, BATTLE_LOG_BG_COLOR, BATTLE_LOG_TEXT_COLOR,
    BATTLE_LOG_HIGHLIGHT_COLOR, BATTLE_LOG_DANGER_COLOR,
    FOG_ALPHA, FOG_COLOR, FOG_APPROXIMATE_RADIUS,
    TERRAIN_IMAGE_FILES, ASSETS_DIR, TERRAIN_IMG_DIR, UNITS_IMG_DIR,
    # 事件总线
    event_bus, EventBus,
)
```

### 10.2 运行时依赖（#2 提供实例）

```python
# 这些对象在运行时由 MainWindow.__init__() 接收（依赖注入）
game_loop: IGameLoop     # 获取所有单位、当前回合、游戏结果
map_data: IMap           # 获取地形、坐标合法性、寻路
fog: IFogOfWar           # 获取可见性、大致位置
```

---

## 11. 资源文件需求

### 11.1 地形图片（12×12 或 16×16 像素，可放大到 TILE_SIZE）

| 文件 | 对应地形 | 说明 |
|------|---------|------|
| `src/ui/assets/terrain/plain.png` | PLAIN | 绿色/棕色地面 |
| `src/ui/assets/terrain/forest.png` | FOREST | 深绿带树木纹理 |
| `src/ui/assets/terrain/mountain.png` | MOUNTAIN | 灰色岩石纹理 |
| `src/ui/assets/terrain/river.png` | RIVER | 蓝色水面纹理 |
| `src/ui/assets/terrain/hq.png` | HQ_CELL | 城堡/建筑图标 |
| `src/ui/assets/terrain/bridge.png` | BRIDGE | 棕色木桥纹理 |

### 11.2 单位图片（占位可用纯色方块）

| 文件 | 说明 |
|------|------|
| `src/ui/assets/units/infantry_blue.png` | 友军步兵 |
| `src/ui/assets/units/cavalry_blue.png` | 友军骑兵 |
| `src/ui/assets/units/artillery_blue.png` | 友军炮兵 |
| `src/ui/assets/units/scout_blue.png` | 友军侦察兵 |
| `src/ui/assets/units/hq_blue.png` | 友军指挥所 |
| `src/ui/assets/units/infantry_red.png` | 敌军步兵 |
| ... | （同上 5 种 × 红色） |

> **Sprint 1 策略**: 先用 `pygame.draw.rect()` 画纯色方块代替图片，#5 后续补充素材。

---

## 12. 测试策略

### 12.1 手动验收（UI 无自动化要求）

| 测试项 | 方法 | Sprint |
|--------|------|:------:|
| 战报面板追加消息 | 手动触发事件 → 观察 UITextBox 追加和滚动 | 1 |
| 地图渲染完整性 | 打开窗口 → 数格子（20×15）→ 检查颜色 | 1 |
| 标记拖拽吸附 | 拖拽方块 → 检查是否吸附到格子中心 | 2 |
| 迷雾遮罩正确性 | 对照已知可见格 → 检查遮罩覆盖 | 2 |
| 指令面板交互 | 选择指令 → 输入坐标 → 点击执行 → 检查日志 | 2 |

### 12.2 可选的自动化测试

```python
# tests/ui/test_map_widget.py (可选)
def test_pixel_to_coord_mapping():
    widget = MapWidget(pygame.Rect(0, 0, 800, 600))
    assert widget.pixel_to_coord(40, 40) == Coordinate(1, 1)
    assert widget.pixel_to_coord(0, 0) == Coordinate(0, 0)

# tests/ui/test_battle_log.py (可选)
def test_battle_log_append():
    panel = BattleLogPanel(...)
    panel._append("测试消息", "#FF0000")
    assert "测试消息" in panel.text_box.html_text
```

---

## 附录 A: Sprint 1 最小可行实现要点

Sprint 1 的目标是**尽快出画面**，不必追求完美：

1. **地图**: 先不用图片，用 `pygame.draw.rect` 按地形编码画不同颜色的方块
2. **单位**: 蓝色方块 = 友军，红色方块 = 敌军，不区分兵种
3. **战报**: 先用 `print()` 模拟事件流（等 #3 的事件广播就绪后再接 EventBus）
4. **指令栏**: 只画 UI 控件，按钮点击只 `print()` 参数，等 #3 ICommander 就绪后再对接

---

> **本文档由 #4 维护，随开发迭代更新。问题或修改建议请提交 PR。**
