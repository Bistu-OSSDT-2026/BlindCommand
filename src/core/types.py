"""
BlindCommand 公共类型定义
=========================
本文件从 constants.py 重导出所有公共类型，作为团队成员按 WORKFLOW.md 查找的入口。

实际定义位于 src/core/constants.py（全局唯一事实来源）。
修改类型定义请修改 constants.py，然后 PR + Review。

版本：v1.0
"""

from src.core.constants import (  # noqa: F401  — 重导出
    # ── 数据类 ──────────────────────────────────────────────────────
    Coordinate,
    UnitStats,
    TerrainProps,
    # ── 枚举 ────────────────────────────────────────────────────────
    BattleOutcome,
    CommandType,
    Direction,
    Faction,
    GameEventType,
    GameResult,
    MarkerType,
    TerrainType,
    UnitType,
)

__all__ = [
    "BattleOutcome",
    "CommandType",
    "Coordinate",
    "Direction",
    "Faction",
    "GameEventType",
    "GameResult",
    "MarkerType",
    "TerrainProps",
    "TerrainType",
    "UnitStats",
    "UnitType",
]
