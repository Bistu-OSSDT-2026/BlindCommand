"""
BlindCommand 全局常量定义 — 全员唯一事实来源
================================================
本文件定义游戏中所有枚举、数值常量、配置字典。
修改本文件必须走 PR + 至少 2 人 Review，合并后全员 git pull。

负责方：#1 起草 → #2 #3 #4 确认 → #1 定稿
版本：v1.0.0
最后更新：2026-07-07
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

# ============================================================================
# 项目版本号（全局唯一来源，main.py / pyproject.toml 均引用此处）
# ============================================================================

VERSION: Final[str] = "1.0.0"

# ============================================================================
# 第一部分：枚举定义
# ============================================================================


class Faction(Enum):
    """阵营"""
    FRIENDLY = "FRIENDLY"   # 友军（玩家方）
    ENEMY    = "ENEMY"      # 敌军（AI 方）


class UnitType(Enum):
    """兵种"""
    INFANTRY  = "Infantry"    # 步兵
    CAVALRY   = "Cavalry"     # 骑兵
    ARTILLERY = "Artillery"   # 炮兵
    SCOUT     = "Scout"       # 侦察兵
    HQ        = "HQ"          # 指挥所


class TerrainType(Enum):
    """地形类型"""
    PLAIN   = 0   # 平原
    FOREST  = 1   # 森林
    MOUNTAIN = 2  # 山地
    RIVER   = 3   # 河流
    HQ_CELL = 4   # 指挥所
    BRIDGE  = 5   # 桥梁


class CommandType(Enum):
    """玩家指令类型"""
    MOVE    = "MOVE"     # 移动到目标坐标
    ATTACK  = "ATTACK"   # 向目标区域进击，遇敌即战
    HOLD    = "HOLD"     # 原地驻守，遇敌自动反击
    SCOUT   = "SCOUT"    # 向指定方向侦察移动
    RETREAT = "RETREAT"  # 脱离战斗，向指定方向撤退
    CAPTURE = "CAPTURE"  # 移动到指挥所并占领
    PATROL  = "PATROL"   # 按指定路径往复巡逻


class GameEventType(Enum):
    """游戏事件类型（EventBus 广播/订阅用）"""
    TURN_START       = auto()  # 回合开始
    TURN_END         = auto()  # 回合结束
    BATTLE_RESULT    = auto()  # 单次战斗结算
    UNIT_KILLED      = auto()  # 单位阵亡
    UNIT_DAMAGED     = auto()  # 单位受伤（未阵亡）
    ENEMY_SPOTTED    = auto()  # 发现敌军
    HQ_CAPTURED      = auto()  # 指挥所被占领
    HQ_UNDER_ATTACK  = auto()  # 指挥所遭受攻击
    COMMAND_SENT     = auto()  # 指令已发出（进入传达队列）
    COMMAND_ARRIVED  = auto()  # 指令已到达友军（开始执行）
    COMMAND_EXPIRED  = auto()  # 指令作废（单位已阵亡）
    POSITION_REPORT  = auto()  # 友军位置汇报
    GAME_OVER        = auto()  # 游戏结束


class MarkerType(Enum):
    """玩家地图标记类型"""
    FRIENDLY_GUESS = "FRIENDLY_GUESS"   # 推测友军位置（蓝色方块）
    ENEMY_GUESS    = "ENEMY_GUESS"      # 推测敌军位置（红色方块）
    HQ_GUESS       = "HQ_GUESS"         # 推测指挥所（黄色方块）
    CUSTOM_NOTE    = "CUSTOM_NOTE"      # 自定义备注（白色方块）


class Direction(Enum):
    """八方向"""
    N  = (0, -1)
    NE = (1, -1)
    E  = (1, 0)
    SE = (1, 1)
    S  = (0, 1)
    SW = (-1, 1)
    W  = (-1, 0)
    NW = (-1, -1)


class GameResult(Enum):
    """游戏结局"""
    VICTORY = "VICTORY"   # 胜利
    DEFEAT  = "DEFEAT"    # 失败
    DRAW    = "DRAW"      # 平局


class BattleOutcome(Enum):
    """单场战斗结果（用于战报措辞）"""
    DECISIVE_WIN = "DECISIVE_WIN"   # 大胜（友军 HP > 70%）
    PYRHHIC_WIN  = "PYRRHIC_WIN"    # 惨胜（友军 HP < 30%）
    STALEMATE    = "STALEMATE"      # 胶着（双方均存活，HP 在 30%~70%）
    MUTUAL_KILL  = "MUTUAL_KILL"    # 同归于尽
    DECISIVE_LOSS = "DECISIVE_LOSS" # 大败
    ENEMY_ROUTED = "ENEMY_ROUTED"   # 敌方溃逃（敌军 HP < 20%）


# ============================================================================
# 第二部分：数据类
# ============================================================================


@dataclass(frozen=True)
class Coordinate:
    """不可变坐标"""
    x: int
    y: int

    def __add__(self, other: "Coordinate") -> "Coordinate":
        return Coordinate(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Coordinate") -> "Coordinate":
        return Coordinate(self.x - other.x, self.y - other.y)

    def manhattan_distance(self, other: "Coordinate") -> int:
        """曼哈顿距离"""
        return abs(self.x - other.x) + abs(self.y - other.y)

    def chebyshev_distance(self, other: "Coordinate") -> int:
        """切比雪夫距离（网格棋盘距离）"""
        return max(abs(self.x - other.x), abs(self.y - other.y))

    def to_tuple(self) -> tuple[int, int]:
        return (self.x, self.y)


@dataclass(frozen=True)
class UnitStats:
    """兵种基础属性（不可变模板）"""
    max_hp: int
    attack: int
    defense: int
    speed: int            # 每回合可移动格数
    attack_range: int     # 攻击范围（格数，0=不可攻击）
    vision_range: int     # 视野范围（格数）
    strong_against: tuple[UnitType, ...] = ()  # 克制的兵种
    is_hq: bool = False   # 是否是指挥所
    capture_turns: int = 0  # 占领所需停留回合数（仅 HQ 有效）


# ============================================================================
# 第三部分：兵种数值表
# ============================================================================

# ── 兵种属性模板（不可变） ──────────────────────────────────────────────
# 格式：UnitType → UnitStats
# 所有单位实例创建时以此为蓝本

UNIT_STATS: Final[dict[UnitType, UnitStats]] = {
    UnitType.INFANTRY: UnitStats(
        max_hp=10,
        attack=3,
        defense=2,
        speed=3,
        attack_range=1,
        vision_range=3,
        strong_against=(UnitType.CAVALRY,),
    ),
    UnitType.CAVALRY: UnitStats(
        max_hp=8,
        attack=4,
        defense=1,
        speed=6,
        attack_range=1,
        vision_range=4,
        strong_against=(UnitType.ARTILLERY,),
    ),
    UnitType.ARTILLERY: UnitStats(
        max_hp=6,
        attack=5,
        defense=1,
        speed=1,
        attack_range=3,
        vision_range=2,
        strong_against=(UnitType.INFANTRY,),
    ),
    UnitType.SCOUT: UnitStats(
        max_hp=5,
        attack=1,
        defense=1,
        speed=5,
        attack_range=1,
        vision_range=6,
        strong_against=(),
    ),
    UnitType.HQ: UnitStats(
        max_hp=30,
        attack=0,
        defense=3,
        speed=0,
        attack_range=0,
        vision_range=0,
        strong_against=(),
        is_hq=True,
        capture_turns=2,
    ),
}

# ── 兵种克制倍率表 ─────────────────────────────────────────────────────
# 格式：TYPE_ADVANTAGE[attacker][defender] = 伤害倍率
# 未列出的组合默认为 1.0

TYPE_ADVANTAGE: Final[dict[UnitType, dict[UnitType, float]]] = {
    UnitType.INFANTRY:  {UnitType.CAVALRY: 1.5},
    UnitType.CAVALRY:   {UnitType.ARTILLERY: 1.5},
    UnitType.ARTILLERY: {UnitType.INFANTRY: 1.5},
    # Scout, HQ 无克制关系
}

# ── 兵种显示名称（中文） ────────────────────────────────────────────────

UNIT_DISPLAY_NAMES: Final[dict[UnitType, str]] = {
    UnitType.INFANTRY:  "步兵",
    UnitType.CAVALRY:   "骑兵",
    UnitType.ARTILLERY: "炮兵",
    UnitType.SCOUT:     "侦察兵",
    UnitType.HQ:        "指挥所",
}

# ============================================================================
# 第四部分：地形属性表
# ============================================================================

# ── 地形属性 ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TerrainProps:
    """单种地形的所有属性"""
    name: str
    move_cost: int              # 移动消耗（不可通行=-1）
    defense_bonus: int          # 防御加成
    vision_modifier: int        # 视野修正（+1 = 增加1格视野）
    stealth_modifier: int       # 隐蔽修正（+1 = 更难被发现）
    is_passable: bool = True    # 是否可通过

TERRAIN_PROPS: Final[dict[TerrainType, TerrainProps]] = {
    TerrainType.PLAIN: TerrainProps(
        name="平原",
        move_cost=1,
        defense_bonus=0,
        vision_modifier=0,
        stealth_modifier=0,
    ),
    TerrainType.FOREST: TerrainProps(
        name="森林",
        move_cost=2,
        defense_bonus=1,
        vision_modifier=0,
        stealth_modifier=1,
    ),
    TerrainType.MOUNTAIN: TerrainProps(
        name="山地",
        move_cost=3,
        defense_bonus=2,
        vision_modifier=1,
        stealth_modifier=0,
    ),
    TerrainType.RIVER: TerrainProps(
        name="河流",
        move_cost=-1,
        defense_bonus=0,
        vision_modifier=0,
        stealth_modifier=0,
        is_passable=False,
    ),
    TerrainType.HQ_CELL: TerrainProps(
        name="指挥所",
        move_cost=1,
        defense_bonus=3,
        vision_modifier=0,
        stealth_modifier=0,
    ),
    TerrainType.BRIDGE: TerrainProps(
        name="桥梁",
        move_cost=1,
        defense_bonus=0,
        vision_modifier=0,
        stealth_modifier=0,
    ),
}

# ── 地形显示图标（文本模式/终端调试用） ────────────────────────────────

TERRAIN_SYMBOLS: Final[dict[TerrainType, str]] = {
    TerrainType.PLAIN:    "·",
    TerrainType.FOREST:   "♣",
    TerrainType.MOUNTAIN: "▲",
    TerrainType.RIVER:    "≈",
    TerrainType.HQ_CELL:  "◈",
    TerrainType.BRIDGE:   "═",
}

# ============================================================================
# 第五部分：游戏规则常量
# ============================================================================

# ── 地图默认值 ──────────────────────────────────────────────────────────

MAP_DEFAULT_WIDTH:  Final[int] = 20    # 地图默认宽度（列数）
MAP_DEFAULT_HEIGHT: Final[int] = 15    # 地图默认高度（行数）
MAP_MIN_SIZE:       Final[int] = 10    # 地图最小尺寸
MAP_MAX_SIZE:       Final[int] = 40    # 地图最大尺寸

# ── 迷雾与信息不对称 ───────────────────────────────────────────────────

FOG_POSITION_REPORT_INTERVAL_MIN: Final[int] = 3   # 友军汇报间隔最小值（回合）
FOG_POSITION_REPORT_INTERVAL_MAX: Final[int] = 5   # 友军汇报间隔最大值（回合）
FOG_POSITION_ERROR_RADIUS:        Final[int] = 2   # 汇报坐标的随机误差（±N 格）
FOG_COMBAT_REVEALS_POSITION:      Final[bool] = True  # 交战时是否暴露精确位置

# 注意：迷雾的"谁看得见谁"计算逻辑归属 #2（src/core/fog_of_war.py）
#      UI 只调用 is_visible_to_faction() 查询接口

# ── 通信延迟 ────────────────────────────────────────────────────────────

COMMAND_DELAY_MIN:       Final[int] = 1  # 最短传达延迟（回合）
COMMAND_DELAY_MAX:       Final[int] = 3  # 最长传达延迟（回合）
COMMAND_DELAY_WEIGHTS:   Final[tuple[float, float, float]] = (0.30, 0.50, 0.20)
# 延迟概率分布：[1回合30%, 2回合50%, 3回合20%] — 对应索引 0,1,2

# ── 战斗系统 ────────────────────────────────────────────────────────────

COMBAT_MIN_DAMAGE:           Final[int]   = 1     # 单次攻击最小伤害
COMBAT_TYPE_ADVANTAGE_MULT:  Final[float] = 1.5   # 兵种克制伤害倍率
COMBAT_COUNTERATTACK_ENABLED: Final[bool] = True   # 是否启用反击
COMBAT_RANGED_FIRST_STRIKE:  Final[bool] = True    # 远程单位（炮兵）是否先手
COMBAT_CRITICAL_HP_RATIO:    Final[float] = 0.30   # 低于此比例视为"残血/惨胜"
COMBAT_HEALTHY_HP_RATIO:     Final[float] = 0.70   # 高于此比例视为"大胜"
COMBAT_ROUT_HP_RATIO:        Final[float] = 0.20   # 低于此比例敌军可能溃逃
COMBAT_ROUT_CHANCE:          Final[float] = 0.40   # 溃逃触发概率

# ── 指挥所占领 ──────────────────────────────────────────────────────────

CAPTURE_REQUIRED_TURNS: Final[int] = 2  # 占领指挥所需连续停留回合数
CAPTURE_INTERRUPTIBLE:  Final[bool] = True  # 占领过程中被打断是否需要重新计时

# ── 胜利/失败条件 ───────────────────────────────────────────────────────

MAX_TURNS: Final[int] = 50  # 回合上限（达到后判平局）

# ── 单位限制 ────────────────────────────────────────────────────────────

MAX_UNITS_PER_FACTION: Final[int] = 20  # 单阵营最大单位数
MAX_UNITS_TOTAL:       Final[int] = 40  # 全局最大单位数

# ============================================================================
# 第六部分：事件载荷数据类（EventBus 统一消息格式）
# ============================================================================


@dataclass
class BattleResultPayload:
    """战斗结算事件的载荷"""
    turn: int
    attacker_id: str
    attacker_name: str
    attacker_faction: str
    attacker_hp_before: int
    attacker_hp_after: int
    defender_id: str
    defender_name: str
    defender_faction: str
    defender_hp_before: int
    defender_hp_after: int
    damage_to_defender: int
    damage_to_attacker: int
    attacker_killed: bool
    defender_killed: bool
    location: tuple[int, int]
    outcome: str  # BattleOutcome 的值


@dataclass
class UnitKilledPayload:
    """单位阵亡事件的载荷"""
    turn: int
    unit_id: str
    unit_name: str
    unit_type: str
    faction: str
    killer_id: str
    killer_name: str
    actual_x: int          # 真实坐标（仅服务端）
    actual_y: int
    reported_x: int        # 向玩家汇报的坐标（带误差，仅友军阵亡时有意义）
    reported_y: int


@dataclass
class EnemySpottedPayload:
    """发现敌军事件的载荷"""
    turn: int
    reporter_id: str
    reporter_name: str
    enemy_type: str
    enemy_count: int
    location: tuple[int, int]


@dataclass
class HqCapturedPayload:
    """指挥所被占领事件的载荷"""
    turn: int
    capturer_id: str
    capturer_name: str
    capturer_faction: str
    hq_location: tuple[int, int]


@dataclass
class PositionReportPayload:
    """友军位置汇报事件的载荷（带误差）"""
    turn: int
    unit_id: str
    unit_name: str
    reported_x: int    # 汇报坐标（有误差，UI 展示此值）
    reported_y: int
    has_enemy_nearby: bool  # 附近是否有敌军
    enemy_info: str = ""    # 若有敌军，简述（如"发现骑兵×2"）


@dataclass
class CommandSentPayload:
    """指令已发出事件的载荷"""
    turn: int
    target_unit_id: str
    target_unit_name: str
    command_type: str       # CommandType 的值
    params: str             # 指令参数的人类可读描述
    estimated_arrival_turn: int  # 预计到达回合


@dataclass
class CommandArrivedPayload:
    """指令已到达事件的载荷"""
    turn: int
    target_unit_id: str
    target_unit_name: str
    command_type: str


@dataclass
class GameOverPayload:
    """游戏结束事件的载荷"""
    turn: int
    result: str     # GameResult 的值
    reason: str     # 人类可读的结局原因


@dataclass
class UnitDamagedPayload:
    """单位受伤（未阵亡）事件的载荷"""
    turn: int
    unit_id: str
    unit_name: str
    faction: str
    hp_before: int
    hp_after: int
    damage: int
    source_name: str  # 伤害来源
    location: tuple[int, int]


# 事件类型 → 载荷类型的映射（供 EventBus 校验用）
EVENT_PAYLOAD_MAP: Final[dict[GameEventType, type | None]] = {
    GameEventType.BATTLE_RESULT:    BattleResultPayload,
    GameEventType.UNIT_KILLED:      UnitKilledPayload,
    GameEventType.UNIT_DAMAGED:     UnitDamagedPayload,
    GameEventType.ENEMY_SPOTTED:    EnemySpottedPayload,
    GameEventType.HQ_CAPTURED:      HqCapturedPayload,
    GameEventType.COMMAND_SENT:     CommandSentPayload,
    GameEventType.COMMAND_ARRIVED:  CommandArrivedPayload,
    GameEventType.COMMAND_EXPIRED:  None,   # 无额外载荷
    GameEventType.POSITION_REPORT:  PositionReportPayload,
    GameEventType.GAME_OVER:        GameOverPayload,
    GameEventType.TURN_START:       None,   # 无额外载荷
    GameEventType.TURN_END:         None,
    GameEventType.HQ_UNDER_ATTACK:  None,
}

# ============================================================================
# 第七部分：UI 常量
# ============================================================================

# ── 窗口尺寸 ────────────────────────────────────────────────────────────

WINDOW_WIDTH:  Final[int] = 1280
WINDOW_HEIGHT: Final[int] = 800
WINDOW_TITLE:  Final[str] = "BlindCommand — 盲棋指挥"

# ── 面板布局比例 ────────────────────────────────────────────────────────

BATTLE_LOG_WIDTH_RATIO: Final[float] = 0.28   # 战报面板宽度占比
MAP_AREA_WIDTH_RATIO:   Final[float] = 0.72   # 地图区域宽度占比
COMMAND_PANEL_HEIGHT:   Final[int]   = 80     # 底部指令栏高度（像素）

# ── 地图格子渲染 ────────────────────────────────────────────────────────

TILE_SIZE:           Final[int] = 40  # 每格像素尺寸
TILE_BORDER_COLOR:   Final[str] = "#333333"  # 格子边框颜色
TILE_BORDER_WIDTH:   Final[int] = 1

# ── 阵营颜色 ────────────────────────────────────────────────────────────

COLOR_FRIENDLY:      Final[str] = "#4488FF"  # 友军蓝色
COLOR_FRIENDLY_FAINT: Final[str] = "#8899CC" # 友军迷雾蓝色（模糊）
COLOR_ENEMY:         Final[str] = "#FF4444"  # 敌军红色
COLOR_ENEMY_FAINT:   Final[str] = "#CC8888"  # 敌军迷雾红色（一般不可见）

# ── 标记颜色 ────────────────────────────────────────────────────────────

COLOR_MARKER_FRIENDLY: Final[str] = "#4488FF80"  # 推测友军（半透明蓝）
COLOR_MARKER_ENEMY:    Final[str] = "#FF444480"  # 推测敌军（半透明红）
COLOR_MARKER_HQ:       Final[str] = "#FFD70080"  # 推测指挥所（半透明金）
COLOR_MARKER_NOTE:     Final[str] = "#FFFFFF80"  # 自定义备注（半透明白）

# ── 战报面板 ────────────────────────────────────────────────────────────

BATTLE_LOG_MAX_LINES:     Final[int] = 500   # 最大行数（超出裁剪旧记录）
BATTLE_LOG_FONT_SIZE:     Final[int] = 13    # 字体大小
BATTLE_LOG_BG_COLOR:      Final[str] = "#1A1A1A"   # 背景色
BATTLE_LOG_TEXT_COLOR:    Final[str] = "#CCCCCC"   # 普通文本色
BATTLE_LOG_HIGHLIGHT_COLOR: Final[str] = "#FFD700" # 高亮文本色（重要事件）
BATTLE_LOG_DANGER_COLOR:  Final[str] = "#FF4444"   # 危险文本色（阵亡/大败）

# ── 指令面板 ────────────────────────────────────────────────────────────

COMMAND_PANEL_BG_COLOR: Final[str] = "#2A2A2A"

# ── 迷雾视觉效果 ────────────────────────────────────────────────────────

FOG_ALPHA:          Final[int] = 180      # 迷雾遮罩透明度（0-255）
FOG_COLOR:          Final[str] = "#000000" # 迷雾颜色
FOG_APPROXIMATE_RADIUS: Final[int] = 3    # "大致位置"显示区域半径

# ============================================================================
# 第八部分：资源路径常量
# ============================================================================

ASSETS_DIR:     Final[str] = "src/ui/assets"
TERRAIN_IMG_DIR: Final[str] = "src/ui/assets/terrain"
UNITS_IMG_DIR:  Final[str] = "src/ui/assets/units"
DATA_DIR:       Final[str] = "data"
MAPS_DIR:       Final[str] = "data/maps"
DEFAULT_MAP_FILE: Final[str] = "data/maps/map_01.json"
UNIT_CONFIG_FILE: Final[str] = "data/unit_config.json"

# ── 地形图片文件名映射 ──────────────────────────────────────────────────

TERRAIN_IMAGE_FILES: Final[dict[TerrainType, str]] = {
    TerrainType.PLAIN:    "plain.png",
    TerrainType.FOREST:   "forest.png",
    TerrainType.MOUNTAIN: "mountain.png",
    TerrainType.RIVER:    "river.png",
    TerrainType.HQ_CELL:  "hq.png",
    TerrainType.BRIDGE:   "bridge.png",
}

# ============================================================================
# 第九部分：兵种数值配置 JSON 结构（供 data/unit_config.json 使用）
# ============================================================================

# 此字典定义了 unit_config.json 的标准格式
# #5 批量生成配置文件时以此为模板
UNIT_CONFIG_SCHEMA: Final[dict[str, dict[str, object]]] = {
    "unit_types": {
        unit_type.value: {
            "max_hp": stats.max_hp,
            "attack": stats.attack,
            "defense": stats.defense,
            "speed": stats.speed,
            "attack_range": stats.attack_range,
            "vision_range": stats.vision_range,
            "strong_against": [t.value for t in stats.strong_against],
            "is_hq": stats.is_hq,
            "capture_turns": stats.capture_turns,
        }
        for unit_type, stats in UNIT_STATS.items()
    }
}

# ============================================================================
# 第十部分：便捷查询函数
# ============================================================================


def get_terrain_props(terrain_code: int) -> TerrainProps:
    """根据地形成员编码获取 TerrainProps（方便地图遍历时调用）。"""
    terrain = TerrainType(terrain_code)
    return TERRAIN_PROPS[terrain]


def get_unit_stats(unit_type: UnitType) -> UnitStats:
    """获取兵种的属性模板。"""
    return UNIT_STATS[unit_type]


def get_advantage_multiplier(attacker: UnitType, defender: UnitType) -> float:
    """获取攻击者对防御者的兵种克制倍率。"""
    attacker_advantages = TYPE_ADVANTAGE.get(attacker, {})
    return attacker_advantages.get(defender, 1.0)


def is_passable(terrain_code: int) -> bool:
    """判断地形是否可通行。"""
    return get_terrain_props(terrain_code).is_passable


def get_move_cost(terrain_code: int) -> int:
    """获取地形移动消耗。"""
    return get_terrain_props(terrain_code).move_cost


# ============================================================================
# 第十一部分：自检（导入本模块时自动验证常量一致性）
# ============================================================================


def _validate_constants() -> None:
    """导入时自动执行的完整性校验。防止成员手动修改常量导致不一致。"""
    errors: list[str] = []

    # 1. 每种 UnitType 必须有对应的 UNIT_STATS
    for ut in UnitType:
        if ut not in UNIT_STATS:
            errors.append(f"UNIT_STATS 缺少 {ut} 的配置")

    # 2. 每种 TerrainType 必须有对应的 TERRAIN_PROPS、TERRAIN_SYMBOLS、TERRAIN_IMAGE_FILES
    for tt in TerrainType:
        if tt not in TERRAIN_PROPS:
            errors.append(f"TERRAIN_PROPS 缺少 {tt} 的配置")
        if tt not in TERRAIN_SYMBOLS:
            errors.append(f"TERRAIN_SYMBOLS 缺少 {tt} 的配置")
        if tt not in TERRAIN_IMAGE_FILES:
            errors.append(f"TERRAIN_IMAGE_FILES 缺少 {tt} 的配置")

    # 3. TYPE_ADVANTAGE 中的兵种引用必须有效
    for attacker, defenders in TYPE_ADVANTAGE.items():
        for defender in defenders:
            if defender not in UnitType:
                errors.append(f"TYPE_ADVANTAGE[{attacker}] 引用了无效兵种 {defender}")

    # 4. EVENT_PAYLOAD_MAP 中的事件类型必须覆盖所有 GameEventType
    for event_type in GameEventType:
        if event_type not in EVENT_PAYLOAD_MAP:
            errors.append(f"EVENT_PAYLOAD_MAP 缺少 {event_type} 的映射")

    # 5. 数值范围检查
    if COMBAT_TYPE_ADVANTAGE_MULT <= 1.0:
        errors.append("COMBAT_TYPE_ADVANTAGE_MULT 必须 > 1.0，否则克制无意义")
    if COMMAND_DELAY_MIN > COMMAND_DELAY_MAX:
        errors.append("COMMAND_DELAY_MIN 不能大于 COMMAND_DELAY_MAX")
    if MAP_MIN_SIZE > MAP_MAX_SIZE:
        errors.append("MAP_MIN_SIZE 不能大于 MAP_MAX_SIZE")
    if COMBAT_MIN_DAMAGE < 1:
        errors.append("COMBAT_MIN_DAMAGE 必须 ≥ 1")

    # 6. 布局比例与权重总和校验
    import math
    if not math.isclose(BATTLE_LOG_WIDTH_RATIO + MAP_AREA_WIDTH_RATIO, 1.0):
        errors.append(
            f"BATTLE_LOG_WIDTH_RATIO ({BATTLE_LOG_WIDTH_RATIO}) + "
            f"MAP_AREA_WIDTH_RATIO ({MAP_AREA_WIDTH_RATIO}) 必须等于 1.0"
        )
    weights_sum = sum(COMMAND_DELAY_WEIGHTS)
    if not math.isclose(weights_sum, 1.0):
        errors.append(
            f"COMMAND_DELAY_WEIGHTS 总和 ({weights_sum}) 必须等于 1.0"
        )

    if errors:
        raise ValueError(
            "全局常量一致性校验失败！请检查 constants.py:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


_validate_constants()
