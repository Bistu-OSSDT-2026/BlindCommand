"""
RTT 实时战斗结算 — 持续攻防，2s/轮
===================================
每轮: damage = max(1, atk - def) × 克制倍率
远程先手（炮兵），步兵/骑兵/侦察同时结算。

由 RealTimeEngine 每 2s 调用 resolve_combat_round()。
"""

from __future__ import annotations

import logging

from src.core.constants import (
    COMBAT_MIN_DAMAGE,
    UnitType,
)
from src.core.interfaces import IUnit

logger = logging.getLogger(__name__)

# ── 兵种克制 ──────────────────────────────────────────────────────────

_TYPE_ADVANTAGE: dict[UnitType, dict[UnitType, float]] = {
    UnitType.INFANTRY: {UnitType.CAVALRY: 1.5},
    UnitType.CAVALRY: {UnitType.ARTILLERY: 1.5},
    UnitType.ARTILLERY: {UnitType.INFANTRY: 1.5},
}


def calc_damage(attacker: IUnit, defender: IUnit) -> int:
    """计算单次攻击伤害。"""
    raw = max(COMBAT_MIN_DAMAGE, attacker.attack - defender.defense)
    mult = _TYPE_ADVANTAGE.get(attacker.unit_type, {}).get(defender.unit_type, 1.0)
    return max(1, int(raw * mult))


def resolve_combat_round(a: IUnit, b: IUnit, elapsed: float) -> str | None:
    """执行一轮攻防。

    远程单位（炮兵 attack_range > 1）先手。双方交替攻击一次。
    返回战报文本，无事件返回 None。
    """
    if not a.is_alive or not b.is_alive:
        return None

    first = a if a.attack_range > 1 else b
    second = b if first is a else a

    parts: list[str] = []

    dmg1 = calc_damage(first, second)
    actual1 = second.take_damage(dmg1, first)
    if actual1 > 0:
        parts.append(f"{first.name} 攻击 {second.name}，造成 {actual1} 点伤害")

    if not second.is_alive:
        parts.append(f"{second.name} 阵亡！")
        return "；".join(parts)

    dmg2 = calc_damage(second, first)
    actual2 = first.take_damage(dmg2, second)
    if actual2 > 0:
        parts.append(f"{second.name} 反击 {first.name}，造成 {actual2} 点伤害")

    if not first.is_alive:
        parts.append(f"{first.name} 阵亡！")

    return "；".join(parts) if parts else None
