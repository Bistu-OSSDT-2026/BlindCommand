"""
src/core — 底层数据层（#2 负责）

本包对外暴露：
- constants: 全局枚举、数值常量、事件载荷类型
- interfaces: 抽象接口契约（#2 实现，#3 #4 调用）
- event_bus:  全局事件总线单例（#3 广播，#4 监听）
"""

# ── 常量 ──────────────────────────────────────────────────────────────
from src.core.constants import (
    # 枚举
    BattleOutcome,
    CommandType,
    Direction,
    Faction,
    GameEventType,
    GameResult,
    MarkerType,
    TerrainType,
    UnitType,
    # 数据类
    Coordinate,
    UnitStats,
    # 兵种配置
    TYPE_ADVANTAGE,
    UNIT_DISPLAY_NAMES,
    UNIT_STATS,
    # 地形配置
    TerrainProps,
    TERRAIN_PROPS,
    TERRAIN_SYMBOLS,
    # 游戏规则
    CAPTURE_REQUIRED_TURNS,
    COMBAT_MIN_DAMAGE,
    COMBAT_TYPE_ADVANTAGE_MULT,
    COMMAND_DELAY_MAX,
    COMMAND_DELAY_MIN,
    FOG_POSITION_ERROR_RADIUS,
    FOG_POSITION_REPORT_INTERVAL_MAX,
    FOG_POSITION_REPORT_INTERVAL_MIN,
    MAP_DEFAULT_HEIGHT,
    MAP_DEFAULT_WIDTH,
    MAX_TURNS,
    # 事件载荷
    BattleResultPayload,
    CommandArrivedPayload,
    CommandSentPayload,
    EnemySpottedPayload,
    EVENT_PAYLOAD_MAP,
    GameOverPayload,
    HqCapturedPayload,
    PositionReportPayload,
    UnitDamagedPayload,
    UnitKilledPayload,
    # 查询函数
    get_advantage_multiplier,
    get_move_cost,
    get_terrain_props,
    get_unit_stats,
    is_passable,
)

# ── 事件总线 ──────────────────────────────────────────────────────────
from src.core.event_bus import EventBus, event_bus

# ── 接口 ──────────────────────────────────────────────────────────────
from src.core.interfaces import (
    ICommand,
    ICommander,
    IFogOfWar,
    IGameLoop,
    IGameState,
    IMap,
    IRangeQuery,
    IUnit,
)

__all__ = [
    # Enums
    "BattleOutcome",
    "CommandType",
    "Direction",
    "Faction",
    "GameEventType",
    "GameResult",
    "MarkerType",
    "TerrainType",
    "UnitType",
    # Dataclasses
    "Coordinate",
    "UnitStats",
    "TerrainProps",
    # Config
    "UNIT_STATS",
    "TYPE_ADVANTAGE",
    "UNIT_DISPLAY_NAMES",
    "TERRAIN_PROPS",
    "TERRAIN_SYMBOLS",
    # Rules
    "CAPTURE_REQUIRED_TURNS",
    "COMBAT_MIN_DAMAGE",
    "COMBAT_TYPE_ADVANTAGE_MULT",
    "COMMAND_DELAY_MAX",
    "COMMAND_DELAY_MIN",
    "FOG_POSITION_ERROR_RADIUS",
    "FOG_POSITION_REPORT_INTERVAL_MAX",
    "FOG_POSITION_REPORT_INTERVAL_MIN",
    "MAP_DEFAULT_HEIGHT",
    "MAP_DEFAULT_WIDTH",
    "MAX_TURNS",
    # Payloads
    "BattleResultPayload",
    "CommandArrivedPayload",
    "CommandSentPayload",
    "EnemySpottedPayload",
    "EVENT_PAYLOAD_MAP",
    "GameOverPayload",
    "HqCapturedPayload",
    "PositionReportPayload",
    "UnitDamagedPayload",
    "UnitKilledPayload",
    # Helpers
    "get_advantage_multiplier",
    "get_move_cost",
    "get_terrain_props",
    "get_unit_stats",
    "is_passable",
    # EventBus
    "EventBus",
    "event_bus",
    # Interfaces
    "ICommand",
    "ICommander",
    "IFogOfWar",
    "IGameLoop",
    "IGameState",
    "IMap",
    "IRangeQuery",
    "IUnit",
]
