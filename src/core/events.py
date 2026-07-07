"""
BlindCommand 事件定义
=====================
本文件从 constants.py 重导出所有事件枚举和载荷数据类。

实际定义位于 src/core/constants.py（全局唯一事实来源）。
修改事件定义请修改 constants.py，然后 PR + Review。

版本：v1.0
"""

from src.core.constants import (  # noqa: F401  — 重导出
    # ── 事件枚举 ────────────────────────────────────────────────────
    GameEventType,
    # ── 事件载荷数据类 ──────────────────────────────────────────────
    BattleResultPayload,
    CommandArrivedPayload,
    CommandSentPayload,
    EnemySpottedPayload,
    GameOverPayload,
    HqCapturedPayload,
    PositionReportPayload,
    UnitDamagedPayload,
    UnitKilledPayload,
    # ── 载荷映射表 ──────────────────────────────────────────────────
    EVENT_PAYLOAD_MAP,
)

__all__ = [
    "BattleResultPayload",
    "CommandArrivedPayload",
    "CommandSentPayload",
    "EnemySpottedPayload",
    "EVENT_PAYLOAD_MAP",
    "GameEventType",
    "GameOverPayload",
    "HqCapturedPayload",
    "PositionReportPayload",
    "UnitDamagedPayload",
    "UnitKilledPayload",
]
