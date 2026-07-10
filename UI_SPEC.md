# BlindCommand UI 层技术规格说明书

> **版本**: v2.0 — RTT  
> **负责**: #4 — UI 与可视化  
> **依赖**: RTT_SPEC.md · MARKER_SPEC.md · TILE_PROMPTS.md  
> **约束**: 只订阅 EventBus + 调用查询接口，不修改游戏数据  
> **最后更新**: 2026-07-09

---

## 1. 概述与职责边界

```
#3 业务层（事件生产者）              #4 UI 层（事件消费者）
┌──────────────┐                    ┌──────────────┐
│ 战斗结算完成  │ ────广播────▶     │ 战报面板更新  │
│ 单位阵亡     │ ────广播────▶     │ 阵亡提示显示  │
│ 遭遇敌军     │ ────广播────▶     │ 遇敌文本打印  │
│ 占领指挥所   │ ────广播────▶     │ 胜利画面切换  │
│ 指令已发出   │ ────广播────▶     │ 指令状态提示  │
│ 位置汇报     │ ────广播────▶     │ 汇报圈显示    │
└──────────────┘                    └──────────────┘

硬约束:
  C1: 禁止 import src.battle
  C2: 禁止 import src.core 内部实现模块
  C3: 禁止直接读写 Unit 实例属性
  C4: 禁止直接修改地图数据
  C5: 游戏状态变化只能通过 EventBus 获知
```

---

## 2. 主窗口布局

```
┌──────────────┬──────────────────────────────────────────────┐
│  ⏸ 暂停      │                                              │
├──────────────┤                                              │
│              │                                              │
│   战报面板    │              🗺 地图区域                      │
│   (28%)     │              (72%)                           │
│              │                                               │
│  战报条目    │    层 0: 基底纹理（泛黄亚麻纸，平铺）           │
│  战报条目    │    层 1: 地形符号（逐格 stamp）               │
│  可滚动      │    层 2: 玩家标记（数字+兵种图标，可拖/删）     │
│              │    层 3: 汇报圈（短暂铅笔圈，在最上方）         │
│              │                                               │
├──────────────┤    无迷雾。无敌军/友军单位显示。                │
│  标记托盘:    │    无网格线。                                 │
│  1 2 3 4 5  │                                              │
│  6 7 8 9 10 │                                              │
│  友军5种     │                                              │
│  敌军5种     │                                              │
├──────────────┴──────────────────────────────────────────────┤
│ 目标:[单位▼] 指令:[MOVE▼] 方向:[↖↑↗←·→↙↓↘] 距离:[5] [▶下达] │
└──────────────────────────────────────────────────────────────┘
```

像素计算:

```
battle_log_rect = Rect(0, 30, int(W * 0.28), H - 80 - 100)
marker_tray_rect = Rect(0, H - 180, int(W * 0.28), 100)
map_rect = Rect(int(W * 0.28), 0, W - int(W * 0.28), H - 80)
command_rect = Rect(0, H - 80, W, 80)
pause_btn_rect = Rect(4, 4, 36, 24)
```

---

## 3. 组件树

```
MainWindow
├── PauseButton (左上角，⏸)
├── BattleLogPanel (左 28% 中上)
├── MarkerPalette (左 28% 底部，战报下方)
├── MapWidget (右 72%)
└── CommandPanel (底部 80px)
```

---

## 4. 组件详细规格

### 4.1 BattleLogPanel — 战报面板

**文件**: `src/ui/battle_log.py`  
**Sprint**: 1→RTT 改造

#### 功能

- 左侧滚动文本区域，逐条显示战场事件
- 最新消息追加到底部自动滚动
- 不同事件用不同颜色
- 保留历史记录（最多 500 条）

#### 战报文本格式（RTT 版）

不使用回合数和数字坐标。使用时间戳 + 地形参照描述：

```
"[10:15] 第一步兵连汇报：我部在森林以东，距河约2格。"
"[10:32] 侦察排汇报：在开阔地带发现敌军骑兵，交火中！"
"[10:40] 在森林东侧与敌军骑兵激战中，我军占优。"
"[10:48] 第一步兵连阵亡！最后已知位置在河以北，森林东侧。"
"[11:02] 🏆 占领敌军指挥所！我军胜利！"
```

#### 颜色映射

| 事件类型 | 颜色 |
|------|------|
| 友军汇报 / 正常消息 | `#CCCCCC` |
| 遇敌 / 占领 / 游戏结束 | `#FFD700` |
| 阵亡 / 大败 / HQ 受袭 | `#FF4444` |

#### 事件订阅

| 事件 | 处理 |
|------|------|
| POSITION_REPORT | 追加位置汇报 |
| ENEMY_SPOTTED | 追加遇敌消息 |
| BATTLE_RESULT | 追加战斗结果 |
| UNIT_KILLED | 追加阵亡通知 |
| HQ_CAPTURED | 追加占领消息 |
| COMMAND_SENT / ARRIVED / EXPIRED | 追加指令状态 |
| GAME_OVER | 追加结局 |

---

### 4.2 MapWidget — 地图渲染

**文件**: `src/ui/map_widget.py`  
**改造**: RTT — 移除单位渲染层和迷雾层

#### 渲染分层（由底到顶）

```
层 0: 基底纹理     base.png 平铺
层 1: 地形符号     6 种地形 × 变体，逐格 stamp
层 2: 玩家标记     数字 + 兵种图标（从托盘拖出，可再拖/右键删）
层 3: 汇报圈       report_circle.png，短暂出现后消失，在最上方
```

无网格线。无敌军/友军单位渲染。无迷雾。

#### 地形渲染

```python
for row in range(map_height):
    for col in range(map_width):
        terrain_code = map_data.get_terrain(Coordinate(col, row))
        tile = terrain_tile_cache[terrain_code]  # 预加载 512px, 缩放到 TILE_SIZE
        surface.blit(tile, (col * TILE_SIZE, row * TILE_SIZE))
```

#### 汇报圈

```
POSITION_REPORT 事件触发
  → 在 reported 坐标处显示 report_circle.png
  → 缩放半径为 REPORT_CIRCLE_RADIUS × TILE_SIZE
  → REPORT_CIRCLE_DURATION 秒后淡出消失
```

#### 类接口

```python
class MapWidget:
    def __init__(self, rect: pygame.Rect)
    def set_base_texture(self, base: pygame.Surface)      # 设置基底
    def set_terrain_tiles(self, tiles: dict)               # 设置地形瓦片
    def render(self, markers, report_circles)              # 每帧渲染
    def draw(self, screen: pygame.Surface)
    def pixel_to_coord(px, py) -> Coordinate | None
```

---

### 4.3 CommandPanel — 指令面板（RTT 改造）

**文件**: `src/ui/command_panel.py`  
**改造**: 7 指令 → 2 指令 + 八方向罗盘

#### 布局

```
目标: [第二步兵连 ▼]  指令: [MOVE ▼]  方向: [↖↑↗←·→↙↓↘]  距离:[5] [▶下达]
```

#### 控件

| 控件 | 说明 |
|------|------|
| 单位下拉 | 存活友军单位列表 |
| 指令下拉 | MOVE / RETREAT |
| 方向罗盘 | 八方向按钮，点击高亮选中 |
| 距离步进器 | 1~10 格，MOVE 时启用，RETREAT 时禁用 |
| 下达按钮 | 发送指令 |

#### 交互

```
点击地图目标格 → 代码自动计算方向+距离 → 填入指令栏
玩家确认 → 点下达 → 指令进入延迟队列
```

---

### 4.4 MarkerPalette — 标记托盘（新增）

**文件**: `src/ui/marker_palette.py`（新建）  
**参考**: MARKER_SPEC.md

#### 布局

```
数字: 1 2 3 4 5 6 7 8 9 10     (pygame 渲染，灰铅笔色，透明底)
友军: 🚶 🐴 💣 🔍 🏴              (5 种兵种，蓝色)
敌军: 🚶 🐴 💣 🔍 🏴              (5 种兵种，红色)
```

#### 交互

| 操作 | 行为 |
|------|------|
| 从托盘拖出 | 创建标记实例，托盘自动再生 |
| 放到地图格上 | 标记吸附到该格 |
| 拖地图上已有标记 | 改变位置 |
| 右键地图上标记 | 删除 |
| 拖到地图外释放 | 标记消失 |

#### 生成

- 数字 1-10：pygame freetype 渲染，灰铅笔色 `#777766`
- 兵种图标：已有 10 张 2048×2048 素材，缩放到托盘尺寸 ~36px

---

### 4.5 PauseButton — 暂停按钮（新增）

**位置**: 左上角 `(4, 4)`  
**尺寸**: 36×24px  
**触发**: 空格键 / 点击按钮

暂停时：
- 游戏时间冻结
- 战报可滚动阅读
- 标记不可拖放
- 指令栏禁用
- 地形始终可见

---

## 5. 渲染管线

```
MainWindow.update()
├── 1. pygame.event.get() 处理事件
│     ├── 空格键 / 暂停按钮 → 暂停切换
│     ├── MarkerPalette 拖拽事件
│     ├── MapWidget 标记拖拽/右键事件
│     └── CommandPanel 交互事件
│
├── 2. MapWidget.render(markers, report_circles)
│     ├── blit base.png (层 0)
│     ├── for 每格: blit 地形瓦片 (层 1)
│     ├── for 每个标记: blit 标记 (层 2)
│     └── for 每个汇报圈: blit 圈 (层 3)
│
├── 3. BattleLogPanel.draw()
├── 4. MarkerPalette.draw()
├── 5. CommandPanel.draw()
├── 6. PauseButton.draw()
│
└── 7. pygame.display.flip()
```

---

## 6. 事件订阅映射表

| 事件 | 载荷 | 订阅者 | 处理 |
|------|------|------|------|
| POSITION_REPORT | PositionReportPayload | BattleLogPanel + MapWidget | 追加战报 + 显示汇报圈 |
| BATTLE_RESULT | BattleResultPayload | BattleLogPanel | 追加战斗消息 |
| UNIT_KILLED | UnitKilledPayload | BattleLogPanel | 追加阵亡通知 |
| ENEMY_SPOTTED | EnemySpottedPayload | BattleLogPanel | 追加遇敌消息 |
| HQ_CAPTURED | HqCapturedPayload | BattleLogPanel | 追加占领消息 |
| COMMAND_SENT | CommandSentPayload | BattleLogPanel | 追加指令已发出 |
| COMMAND_ARRIVED | CommandArrivedPayload | BattleLogPanel | 追加指令已到达 |
| COMMAND_EXPIRED | None | BattleLogPanel | 追加指令作废 |
| GAME_OVER | GameOverPayload | BattleLogPanel | 追加结局 |

---

## 7. 资源文件

| 文件 | 用途 | 层 |
|------|------|:--:|
| `terrain/base.png` | 泛黄亚麻纸基底（平铺） | 0 |
| `terrain/plain/forest/mountain/river/hq/bridge.png` | 地形符号（透明底） | 1 |
| `units/Infantry_blue.png` 等 10 张 | 兵种图标（托盘用） | 2 |
| `assets/report_circle.png` | 汇报圈（透明底灰铅笔椭圆） | 3 |

---

## 8. 常量

```python
# 窗口
WINDOW_WIDTH  = 1280
WINDOW_HEIGHT = 800

# 布局比例
BATTLE_LOG_WIDTH_RATIO = 0.28
MARKER_TRAY_HEIGHT     = 100      # 标记托盘高度

# 棋盘
TILE_SIZE  = 24
MAP_WIDTH  = 34
MAP_HEIGHT = 25

# 汇报圈
REPORT_CIRCLE_RADIUS   = 3        # 半径（格）
REPORT_CIRCLE_DURATION = 5        # 持续（秒）
REPORT_CIRCLE_ALPHA    = 80       # 透明度

# 颜色
COLOR_BG       = (30, 30, 30)
COLOR_PANEL_BG = (26, 26, 26)
COLOR_BORDER   = (60, 60, 60)
```
