"""
兵种子类 — 基于 UnitBase 的五个兵种实现（Sprint 3 迁移版）。

本模块将 Unit 改为继承 #2 的 UnitBase，消除代码重复。
Commander 通过 UnitBase.set_position() 直接同步坐标，不依赖 move_to 的简版 teleport。

兵种列表:
    - Infantry  (步兵): 均衡型，克骑兵 (×1.5)
    - Cavalry   (骑兵): 高速型，克炮兵 (×1.5)
    - Artillery (炮兵): 远程型，克步兵 (×1.5)，攻击范围 3
    - Scout     (侦察兵): 视野型，视野 6，无克制
    - HQ        (指挥所): 固定型，不可移动/攻击，可被占领

依赖:
    src/core/unit_base.py — UnitBase 基类
    src/core/interfaces.py — IUnit 接口
    src/core/constants.py  — UNIT_STATS, 游戏规则常量

版本: v0.2.0 — Sprint 3
"""

from __future__ import annotations

import logging

from src.core.constants import (
    COMBAT_CRITICAL_HP_RATIO,
    COMBAT_HEALTHY_HP_RATIO,
    COMBAT_MIN_DAMAGE,
    UNIT_DISPLAY_NAMES,
    UNIT_STATS,
    Coordinate,
    Faction,
    UnitType,
)
from src.core.interfaces import IMap, IUnit
from src.core.unit_base import UnitBase

logger = logging.getLogger(__name__)


# ============================================================================
# Unit 适配层 — 继承 UnitBase，增加 battle 层需要的扩展属性
# ============================================================================


class Unit(UnitBase):
    """单位基类，继承 #2 的 UnitBase，增加 battle 层扩展。

    Sprint 3 迁移：不再直接实现 IUnit，改为继承 UnitBase。
    额外提供：
        - base_defense: 不含地形加成的基础防御
        - get_state_report: 更丰富的状态报告（健康/受损/惨重）
    """

    def __init__(
        self,
        unit_id: str,
        name: str,
        faction: Faction,
        unit_type: UnitType,
        position: Coordinate,
        stats=None,  # UnitStats | None — 传入时优先，否则从 UNIT_STATS 取
        game_map: IMap | None = None,
    ) -> None:
        """初始化单位。

        兼容两种构造方式：
        1. 新风格（推荐）: Unit(..., stats=UNIT_STATS[UnitType.INFANTRY])
        2. 旧风格（子类兼容）: 子类通过 super().__init__(...) 传入拆分后的参数
           （已不再需要；子类构造时直接传 stats）

        Args:
            unit_id: 全局唯一标识
            name: 人类可读名称
            faction: 所属阵营
            unit_type: 兵种类型
            position: 初始坐标
            stats: 兵种属性模板（None 时从 UNIT_STATS[unit_type] 取）
            game_map: 可选 Map 引用
        """
        if stats is None:
            stats = UNIT_STATS[unit_type]

        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=unit_type,
            position=position,
            stats=stats,
            game_map=game_map,
        )

    # ── battle 层扩展属性 ──────────────────────────────────────────────

    @property
    def base_defense(self) -> int:
        """基础防御力（不含地形加成）。"""
        return self._base_defense  # UnitBase 私有字段，Python 无强制访问控制

    # ── get_state_report 覆盖（更丰富的状态措辞） ──────────────────────

    def get_state_report(self) -> str:
        """生成用于战报的人类可读状态文本（含血量状态措辞）。

        Returns:
            格式：'{名称}({兵种中文}) HP:{cur}/{max} [{状态}] @({x},{y})'
        """
        if not self._is_alive:
            return f"{self._name} 已阵亡"

        hp_ratio = self.hp_ratio
        if hp_ratio >= COMBAT_HEALTHY_HP_RATIO:
            status = "状态良好"
        elif hp_ratio >= COMBAT_CRITICAL_HP_RATIO:
            status = "轻微受损"
        else:
            status = "损失惨重"

        type_name = UNIT_DISPLAY_NAMES.get(self._unit_type, str(self._unit_type))
        return (
            f"{self._name}({type_name}) "
            f"HP:{self._current_hp}/{self._max_hp} "
            f"[{status}]"
            f" @({self._position.x},{self._position.y})"
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"id={self._unit_id!r}, name={self._name!r}, "
            f"hp={self._current_hp}/{self._max_hp}, "
            f"pos=({self._position.x},{self._position.y}), "
            f"alive={self._is_alive})"
        )


# ============================================================================
# 兵种子类 — 继承 Unit，从 UNIT_STATS 自动获取属性
# ============================================================================


class Infantry(Unit):
    """步兵 — 均衡型近战单位，克制骑兵 (×1.5)。"""

    def __init__(
        self, unit_id: str, name: str, faction: Faction, start_pos: Coordinate
    ) -> None:
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.INFANTRY,
            position=start_pos,
        )


class Cavalry(Unit):
    """骑兵 — 高速近战单位，克制炮兵 (×1.5)。速度全兵种最快 (6)。"""

    def __init__(
        self, unit_id: str, name: str, faction: Faction, start_pos: Coordinate
    ) -> None:
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.CAVALRY,
            position=start_pos,
        )


class Artillery(Unit):
    """炮兵 — 远程攻击单位（范围 3），克制步兵 (×1.5)。

    特性：远程先手。当攻击距离 > 1 时，先手攻击且防御方不反击。
    """

    def __init__(
        self, unit_id: str, name: str, faction: Faction, start_pos: Coordinate
    ) -> None:
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.ARTILLERY,
            position=start_pos,
        )

    @property
    def is_ranged_attack(self) -> bool:
        """是否可发起远程先手攻击。"""
        return self._attack_range > 1


class Scout(Unit):
    """侦察兵 — 视野型轻装单位，视野最广 (6)，无兵种克制。

    战斗力弱（攻击 1），主要用于侦察和扩大视野。
    """

    def __init__(
        self, unit_id: str, name: str, faction: Faction, start_pos: Coordinate
    ) -> None:
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.SCOUT,
            position=start_pos,
        )


class HQ(Unit):
    """指挥所 — 固定型单位，不可移动/攻击，可被占领。

    血量最高 (30)，防御最高 (3)，是胜利条件的关键目标。
    被敌军步兵连续占领 2 回合即导致失败。
    """

    def __init__(
        self, unit_id: str, name: str, faction: Faction, start_pos: Coordinate
    ) -> None:
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.HQ,
            position=start_pos,
        )

    # ── HQ 特殊行为覆盖 ──────────────────────────────────────────────

    def move_to(self, target: Coordinate) -> bool:
        """指挥所不可移动。"""
        return False

    def attack_target(self, target: IUnit) -> int:
        """指挥所不可攻击。

        Raises:
            ValueError: 始终抛出
        """
        raise ValueError(f"{self._name} 是指挥所，不可攻击")

    def can_attack(self, target: IUnit) -> bool:
        """指挥所不可攻击。"""
        return False
