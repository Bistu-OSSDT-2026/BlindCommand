# BlindCommand RTT 架构设计

> **版本**: v0.1-draft  
> **状态**: 设计阶段  
> **替代**: 当前的回合制 GameLoop (§8 CORE_SPEC)

---

## 1. 核心参数（已确认）

| 参数 | 值 | 说明 |
|------|:--:|------|
| 移动速度 | `秒/格 = 6 / speed` | 骑兵 1s/格, 步兵 2s/格, 炮兵 6s/格 |
| 通信延迟 | ~1 秒 | 指令几乎即时到达 |
| 指令下达 | 随时 | 不暂停 |
| AI 决策 | 定时 tick | 每隔 N 秒运行一次 |
| 棋盘 | 34×25, TILE_SIZE=24px | — |

---

## 2. 架构：从回合制到实时制

### 旧（回合制）

```
GameLoop.run_turn()
  → 阶段 1: 指令出队
  → 阶段 2: AI 决策
  → 阶段 3: 移动（跳格子）
  → 阶段 4: 侦察
  → 阶段 5: 战斗
  → ...
  
单位移动 = 每个 turn 跳跃 speed 格
```

### 新（实时制）

```
主循环 tick (60fps)
  → 更新所有单位位置（连续移动）
  → 检测敌我遭遇
  → 战斗结算
  → AI tick 定时触发
  → 位置汇报检查
  → 渲染

单位移动 = 每帧前进 delta_time / 秒每格 格
```

---

## 3. 核心类设计

### 3.1 RealTimeEngine（替代 GameLoop）

```
RealTimeEngine:
    _map: IMap
    _units: dict[id, Unit]
    _commander: Commander
    _ai: EnemyAI
    _fog: FogOfWar
    _range_query: RangeQuery
    _clock: pygame.Clock
    _elapsed: float           # 游戏总运行时间（秒）
    _ai_tick_interval: float  # AI tick 间隔（秒）
    
    主循环:
      while running:
        dt = clock.tick(60) / 1000  # 秒
        _update(dt)
        _render()
    
    _update(dt):
        # 1. 处理指令队列（到时的指令分配给单位）
        # 2. AI tick（定时触发）
        # 3. 更新所有单位位置（连续移动）
        # 4. 检测遭遇
        # 5. 战斗结算
        # 6. 位置汇报
        # 7. 胜负判定
```

### 3.2 Unit 改造：连续移动

```
旧: unit.move_to(target) → 寻路 + 跳格子
新: unit.set_destination(target) → 计算路径
    unit.update(dt) → 沿路径逐帧推进 position
    unit.position 从 int Coordinate 变为 float (x, y)
```

```
每帧:
    if unit._path:
        next_point = unit._path[unit._path_index]
        move_amount = dt / unit.seconds_per_tile  # 本帧前进的格数
        unit._progress += move_amount
        if unit._progress >= 1.0:
            unit._progress -= 1.0
            unit._path_index += 1
            unit.position = 当前格坐标
            if 到达目标:
                unit._path = []
```

### 3.3 Commander 改造：延迟从回合改为秒

```
旧: CommandQueue 管理回合延迟 (1~3 turns)
新: 延迟改为秒，单位收到指令时间 = 当前时间 + 延迟秒数

issue_command() → cmd.deliver_at = _elapsed + delay_seconds
每帧 process_queue() → 取出 cmd.deliver_at <= _elapsed 的指令 → 执行
```

### 3.4 AI 定时 tick

```
EnemyAI:
    _tick_interval: float  # 如 3 秒
    _last_tick: float
    
    update(dt):
        _last_tick += dt
        if _last_tick >= _tick_interval:
            _last_tick = 0
            decide_all()
```

---

## 4. 显示层：地图上永不显示单位

```
地图渲染层级（从底到顶）：

层 0: 基底纹理     ← 泛黄亚麻纸，平铺
层 1: 地形符号     ← 逐格 stamp
层 2: 玩家标记     ← 数字 + 兵种图标，从托盘拖出，可再拖/右键删除
层 3: 汇报圈       ← 短暂铅笔圈，5 秒消失，**在最上方**
```

网格线隐藏，无迷雾遮罩。单位真实位置**永不渲染**。

---

## 5. 事件系统（保留）

现有 EventBus 保留，事件类型不变，但 payload 中回合数替换为时间戳：

```
POSITION_REPORT:  (unit_id, unit_name, reported_x, reported_y, has_enemy, enemy_info, timestamp)
UNIT_KILLED:      (unit_id, killer_id, actual_x, actual_y, reported_x, reported_y, timestamp)
ENEMY_SPOTTED:    (reporter_id, enemy_type, location, timestamp)
BATTLE_RESULT:    同上 + timestamp
COMMAND_SENT / ARRIVED / EXPIRED
HQ_CAPTURED
GAME_OVER
```

---

## 6. 文件变更计划

| 模块 | 变更 |
|------|------|
| `src/core/game_loop.py` | → **删除**，替换为 `src/core/engine.py` |
| `src/core/unit_base.py` | 增加 `set_destination()`, `update(dt)`, `seconds_per_tile`, float position |
| `src/core/map.py` | 增加 `get_path_progress()`, 保留 find_path 和 occupancy |
| `src/battle/commander.py` | `issue_command()` 加 `delay_seconds`, `process_queue()` 按时间出队 |
| `src/battle/command_queue.py` | 延迟从回合改为秒 |
| `src/battle/ai.py` | 增加 `update(dt)` 定时 tick |
| `src/ui/map_widget.py` | **移除** `_render_unit_layer_*()`, 不再渲染单位 |
| `src/ui/main_window.py` | 暂停/恢复改为速度控制, 对接新的 Engine |
| `src/core/interfaces.py` | IGameLoop → IEngine, 调整数据结构 |
| `src/core/constants.py` | 保留 TILE_SIZE=24, MAP_DEFAULT=34×25 |

---

## 7. 保持不变的部分

- 地图系统（IMap / GameMap）- 完整保留
- 迷雾/视野计算（FogOfWar）- 完整保留
- 兵种数值（UNIT_STATS）- 完整保留
- 兵种克制（TYPE_ADVANTAGE）- 完整保留
- 战报面板（BattleLogPanel）- 保留，对接事件
- 标记系统（MarkerSystem）- 保留
- 所有 UI 布局常量 - 保留
- 大地图棋盘 34×25, TILE_SIZE=24 - 保留

---

## 8. 移动速度表

基于公式 `秒/格 = 6 / speed`：

| 兵种 | speed | 秒/格 | 横穿地图(34格) |
|------|:--:|:--:|:--:|
| 骑兵 | 6 | 1.0s | 34s |
| 侦察兵 | 5 | 1.2s | 41s |
| 步兵 | 3 | 2.0s | 68s |
| 炮兵 | 1 | 6.0s | 204s |
| HQ | 0 | — | 不动 |

---

## 9. 待定事项

| 事项 | 默认值（待确认） |
|------|:--:|
| AI tick 间隔 | 3 秒 |
| 通信延迟范围 | 0.5 ~ 1.5 秒 |
| 位置汇报间隔 | 15 ~ 25 秒（原 3~5 回合映射） |
| 战斗结算频率 | 遭遇即结算（实时） |

---

## 10. 玩家与地图的交互

### 10.1 地图不可见规则

地图上**永不显示**：
- 友军单位及其实时位置
- 敌军单位及其实时位置
- 单位移动过程

地图上**显示**：
- 地形（基底 + 地形符号）
- 玩家自己拖放的推测标记（永久）
- 汇报圈（见 10.2）

### 10.2 汇报圈

```
触发：    友军位置汇报事件（POSITION_REPORT）
样式：    暗灰铅笔色，半透明，手绘感不规则椭圆
目的：    给玩家一个短暂视觉锚点
```

汇报圈参数定义为常量，后期可调难度：

| 常量 | 默认 | 含义 | 简单难度 | 困难难度 |
|------|:--:|------|:--:|:--:|
| `REPORT_CIRCLE_RADIUS` | 3 | 圈半径（格） | 2 | 5 |
| `REPORT_CIRCLE_DURATION` | 5 | 显示时长（秒） | 8 | 3 |
| `REPORT_CIRCLE_ALPHA` | 80 | 透明度（0-255） | 100 | 50 |

```
简单模式：圈小（更精确）→ 显示更久
困难模式：圈大（更模糊）→ 显示更短 → 玩家得赶紧记住
```

### 10.3 下达指令

玩家只能下达两种指令：

| 指令 | 含义 | 参数 |
|------|------|------|
| **MOVE** | 向目标方向移动指定格数 | 八方向 + 距离（格数） |
| **RETREAT** | 向指定方向快速撤退，脱离当前战斗 | 八方向 |

```
指令栏：

目标: [第二步兵连 ▼]
指令: [ MOVE ▼ ]     方向: [  ↖  ↑  ↗  ]   距离: [ 5 ] 格
                     方向: [  ←  ·  →  ]
                           [  ↙  ↓  ↘  ]
                                       [ ▶ 下达 ]
```

### 10.3.1 自动行为

| 触发条件 | 行为 |
|------|------|
| 到达目标位置 | 自动 HOLD（原地驻守，遇敌反击） |
| 敌我单位进入彼此攻击范围 | 自动战斗（1 秒延迟后开始） |
| 附近友军战斗中、本军空闲 | 自动向战斗位置移动增援 |

### 10.3.2 增援

```
触发条件：
  - 友军正在战斗
  - 本军未在执行移动指令（空闲/HOLD）
  - 距离战斗位置 < 5 格

行为：
  自动向战斗位置移动
  到达后自动加入战斗

战报：
  "第一骑兵连向战斗位置增援。"
```

### 10.4 战报文字

```
不使用数字坐标 → 使用地形参照描述

示例：
  "第一步兵连汇报：我部在森林以东，距河约2格。"
  "第二骑兵连汇报：我部抵达山地西麓。"
  "侦察排汇报：在开阔地带发现敌军骑兵，交火中。"
  "第一步兵连阵亡！最后已知位置在指挥所以北，森林附近。"

生成逻辑：
	  扫描单位周围 N 格 → 找最近的地形特征（森林/山/河/HQ）
	  → 自动生成位置描述文本
```

---

## 11. 战斗系统

### 11.1 触发规则

```
敌我单位进入彼此攻击范围
  ↓
1 秒延迟（反应时间）
  ↓
自动开始战斗
  ↓
每 2 秒一轮攻防（双方交替掉血）
  ↓
一方阵亡或脱离 → 战斗结束
```

### 11.2 战斗时长（基于伤害公式自动计算）

```
每轮伤害 = max(1, 攻击方攻击 - 防御方防御) × 克制倍率
所需轮数 = ⌈目标血量 / 每轮伤害⌉
战斗时长 = 所需轮数 × 攻击间隔
```

**攻击间隔**：

| 兵种 | 间隔 | 原因 |
|------|:--:|------|
| 骑兵 | 1.5s | 冲锋快，近身即砍 |
| 侦察兵 | 1.5s | 轻装速射 |
| 步兵 | 2.0s | 标准步枪对射 |
| 炮兵 | 3.0s | 装填瞄准耗时 |
| HQ | — | 不攻击 |

**实际战例**：

| 对战 | 每轮伤害 | 轮数 | 时长 |
|------|:--:|:--:|:--:|
| 骑兵(攻4) vs 步兵(防2,血10) | 2 | 5 | **7.5s** |
| 步兵(攻3) vs 步兵(防2,血10) | 1 | 10 | **20s** |
| 炮兵(攻5) vs 步兵(防2,血10) | 3 | 4 | **12s** |
| 骑兵(攻4) vs HQ(防3,血30) | 1 | 30 | **45s** |
| 骑兵(攻4)×1.5 vs 炮兵(防1,血6) | 4×1.5-1=5 | 2 | **3s** |

> 公式自动得出每种兵种组合的自然时长，无需硬编码。

### 11.3 战斗中的战报

四种维度随机组合，不重复：

| 维度 | 变体 |
|------|------|
| 态势 | "我军占优" / "势均力敌" / "我军受创" / "危急" |
| 程度 | "轻微交火" / "交战中" / "激战中" / "损失惨重" |
| 地点 | 从地形参照描述生成 |
| 敌军 | "遭遇敌军骑兵" / "发现约2支敌军" / "敌军兵力不明" |

```
示例：
  "在森林东侧与敌军骑兵激战中，我军占优。"
  "河附近遭遇敌军，势均力敌，轻微交火。"
  "开阔地带与敌军炮兵接火，我军受创，损失惨重！"
```

### 11.4 脱离

```
战斗中 → 玩家下达 RETREAT 至某方向
  → 单位停止攻击，向该方向移动
  → 脱离期间不能反击
  → 敌军可能追击 1~2 轮（速度差决定追击距离）
  → 成功脱离 → 或未跑掉阵亡
```

### 11.5 阵亡通知

```
单位阵亡时：
  1. 立即停止活动
  2. 延迟 2~4 秒后发送战报（模拟信息滞后）
  3. 使用地形参照描述最后位置

示例：
  "第一步兵连阵亡！最后已知位置在河以北，森林东侧。"
```

---

## 12. 胜利与失败条件

| 条件 | 结果 |
|------|:--:|
| 全歼敌军 | 🏆 胜利 |
| 占领敌方 HQ | 🏆 胜利 |
| 己方全军覆没 | 💀 失败 |
| 己方 HQ 被占领 | 💀 失败 |

---

## 13. 暂停

| 触发 | 效果 |
|------|------|
| 空格键 | 暂停 / 恢复 |
| 左侧暂停按钮（战报面板上方） | 暂停 / 恢复 |

暂停时：
- 游戏时间冻结，单位停止移动
- 战报可滚动阅读
- 标记**不可拖放**
- 指令栏禁用
- 地形始终可见

---

## 14. 游戏开始流程

```
1. 加载地图 (JSON → GameMap)
2. 双方单位按预设位置部署（不可见）
3. 播放开场战报："我军已就位，等待命令。"
4. 玩家开始操作
```

> 无部署阶段——单位初始位置由地图 JSON 预设。后期可加入玩家手动部署。

---

## 15. 指令栏改造

```
回合制：7 种指令 (MOVE/ATTACK/HOLD/SCOUT/RETREAT/CAPTURE/PATROL)
RTT：   2 种指令 (MOVE/RETREAT)

指令栏布局：

  目标: [第二步兵连 ▼]  指令: [MOVE ▼]  方向: [↖↑↗←·→↙↓↘]  距离:[5] [▶下达]
```

| 控件 | 说明 |
|------|------|
| 单位下拉 | 存活友军单位列表 |
| 指令下拉 | MOVE / RETREAT |
| 方向罗盘 | 八方向按钮（点击选方向） |
| 距离 | 1~10 格步进器 |
| 下达按钮 | 发送指令（1 秒延迟后到达） |

> 选 MOVE + 点地图目标格 → 方向/距离自动计算填入。RETREAT 只需方向。

---

## 16. 相关文档

| 文档 | 关系 |
|------|------|
| `CORE_SPEC.md` | RTT 替代 §8 GameLoop；§1-7 大部分保留 |
| `MARKER_SPEC.md` | 标记系统替代地图上的单位显示 |
| `TILE_PROMPTS.md` | 地形/兵种素材生成方案 |
| `MAP_GEN_SPEC.md` | 34×25 地图随机生成 |
| `UI_SPEC.md` | UI 布局参考（需更新） |
