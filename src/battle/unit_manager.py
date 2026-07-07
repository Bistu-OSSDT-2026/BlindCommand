"""
单位实例管理器 — 负责单位的创建、查询、销毁与统计。

本模块是 battle 层与 #2 底层（IMap）之间的"单位注册中心"。
通过工厂方法创建 5 种兵种实例，提供 ID/阵营/兵种/坐标维度的查询，
并在单位阵亡时更新地图并广播事件。

依赖:
    src/core/interfaces.py — IUnit, IMap 接口
    src/core/constants.py  — UnitType, Faction, 事件载荷
    src/core/event_bus.py  — 事件广播
    src/battle/units.py    — 5 个兵种子类

版本: v0.1.0
"""

from __future__ import annotations

from src.battle.units import HQ, Artillery, Cavalry, Infantry, Scout, Unit
from src.core.constants import (
    FOG_POSITION_ERROR_RADIUS,
    Coordinate,
    Faction,
    GameEventType,
    UnitKilledPayload,
    UnitType,
)
from src.core.event_bus import event_bus
from src.core.interfaces import IMap, IUnit

# ============================================================================
# 兵种工厂映射
# ============================================================================

_UNIT_CLASS_MAP: dict[UnitType, type[Unit]] = {
    UnitType.INFANTRY: Infantry,
    UnitType.CAVALRY: Cavalry,
    UnitType.ARTILLERY: Artillery,
    UnitType.SCOUT: Scout,
    UnitType.HQ: HQ,
}


def _create_unit_instance(
    unit_type: UnitType,
    unit_id: str,
    name: str,
    faction: Faction,
    position: Coordinate,
) -> Unit:
    """工厂函数：根据兵种类型创建对应的子类实例。

    Args:
        unit_type: 兵种类型
        unit_id: 全局唯一标识
        name: 人类可读名称
        faction: 所属阵营
        position: 初始坐标

    Returns:
        对应兵种的 Unit 子类实例

    Raises:
        ValueError: unit_type 无效
    """
    cls = _UNIT_CLASS_MAP.get(unit_type)
    if cls is None:
        raise ValueError(f"未知兵种类型: {unit_type}")
    return cls(unit_id=unit_id, name=name, faction=faction, start_pos=position)


# ============================================================================
# UnitManager
# ============================================================================


class UnitManager:
    """单位实例管理器。

    职责:
        - 工厂方法创建 5 种兵种实例
        - 按 ID / 阵营 / 兵种 / 坐标查询
        - 销毁单位（更新地图 + 广播事件）
        - 统计存活数量
    """

    def __init__(self, game_map: IMap) -> None:
        """初始化管理器。

        Args:
            game_map: 地图对象（#2 实现），用于 place_unit / remove_unit
        """
        self._map = game_map
        self._units: dict[str, Unit] = {}  # unit_id → Unit

    # ── 工厂方法 ──────────────────────────────────────────────────────────

    def create_unit(
        self,
        unit_type: UnitType,
        unit_id: str,
        name: str,
        faction: Faction,
        position: Coordinate,
    ) -> Unit:
        """根据兵种类型创建对应子类实例，并放置到地图上。

        Args:
            unit_type: 兵种类型
            unit_id: 全局唯一标识（必须唯一）
            name: 人类可读名称
            faction: 所属阵营
            position: 初始坐标

        Returns:
            创建的 Unit 实例

        Raises:
            ValueError: unit_id 重复或 unit_type 无效
        """
        if unit_id in self._units:
            raise ValueError(f"单位 ID 重复: {unit_id}")

        unit = _create_unit_instance(unit_type, unit_id, name, faction, position)
        self._units[unit_id] = unit
        self._map.place_unit(unit, position)
        return unit

    def create_units_from_config(
        self, config_list: list[dict], faction: Faction
    ) -> list[Unit]:
        """从配置文件批量创建单位。

        Args:
            config_list: 单位配置列表，每项含 unit_id, name, unit_type, start_x, start_y
            faction: 全部单位的所属阵营

        Returns:
            创建的单位列表
        """
        created: list[Unit] = []
        for cfg in config_list:
            unit_type = UnitType(cfg["unit_type"])
            unit = self.create_unit(
                unit_type=unit_type,
                unit_id=cfg["unit_id"],
                name=cfg["name"],
                faction=faction,
                position=Coordinate(cfg["start_x"], cfg["start_y"]),
            )
            created.append(unit)
        return created

    # ── 查询方法 ──────────────────────────────────────────────────────────

    def get_unit_by_id(self, unit_id: str) -> Unit | None:
        """按 ID 查找单位。

        Args:
            unit_id: 单位唯一标识

        Returns:
            找到的 Unit，不存在返回 None
        """
        return self._units.get(unit_id)

    def get_units_by_faction(self, faction: Faction) -> list[Unit]:
        """获取某阵营所有存活单位。

        Args:
            faction: 阵营

        Returns:
            存活单位列表
        """
        return [u for u in self._units.values() if u.faction == faction and u.is_alive]

    def get_alive_units(self) -> list[Unit]:
        """获取所有存活单位。

        Returns:
            所有存活单位列表
        """
        return [u for u in self._units.values() if u.is_alive]

    def get_units_by_type(
        self, unit_type: UnitType, faction: Faction | None = None
    ) -> list[Unit]:
        """按兵种筛选单位。

        Args:
            unit_type: 兵种类型
            faction: 可选，限定阵营

        Returns:
            符合条件的存活单位列表
        """
        result = [
            u
            for u in self._units.values()
            if u.unit_type == unit_type and u.is_alive
        ]
        if faction is not None:
            result = [u for u in result if u.faction == faction]
        return result

    def get_all_units(self) -> list[Unit]:
        """获取所有单位（含已阵亡，调试用）。

        Returns:
            全部单位列表
        """
        return list(self._units.values())

    # ── 销毁方法 ──────────────────────────────────────────────────────────

    def kill_unit(self, unit: Unit, killer: IUnit, current_turn: int) -> None:
        """销毁单位: 标记阵亡 + 从地图移除 + 广播 UNIT_KILLED 事件。

        注意: 待执行指令的清理由 Commander 监听 UNIT_KILLED 事件后自行处理，
        避免循环依赖（Commander 依赖 UnitManager）。

        Args:
            unit: 被击杀的单位
            killer: 击杀者
            current_turn: 当前回合数
        """
        if not unit.is_alive:
            # 单位可能已被 battle_system 的 take_damage 杀死——仍需广播事件。
            # 但不再重复调用 take_damage（避免 HP 已为 0 时再扣）。
            pass
        else:
            # 标记阵亡并确保 HP 为 0
            unit.take_damage(unit.current_hp, killer)

        # 从地图移除
        self._map.remove_unit(unit)

        # 计算汇报坐标（友军阵亡带误差，敌军精确）
        actual_pos = unit.position
        if unit.faction == Faction.FRIENDLY:
            import random
            reported_x = actual_pos.x + random.randint(
                -FOG_POSITION_ERROR_RADIUS, FOG_POSITION_ERROR_RADIUS
            )
            reported_y = actual_pos.y + random.randint(
                -FOG_POSITION_ERROR_RADIUS, FOG_POSITION_ERROR_RADIUS
            )
        else:
            reported_x, reported_y = actual_pos.x, actual_pos.y

        # 广播事件
        event_bus.emit(
            GameEventType.UNIT_KILLED,
            UnitKilledPayload(
                turn=current_turn,
                unit_id=unit.unit_id,
                unit_name=unit.name,
                unit_type=unit.unit_type.value,
                faction=unit.faction.value,
                killer_id=killer.unit_id,
                killer_name=killer.name,
                actual_x=actual_pos.x,
                actual_y=actual_pos.y,
                reported_x=reported_x,
                reported_y=reported_y,
            ),
        )

    # ── 统计方法 ──────────────────────────────────────────────────────────

    def count_alive_by_faction(self, faction: Faction) -> int:
        """某阵营存活单位数。

        Args:
            faction: 阵营

        Returns:
            存活数量
        """
        return len(self.get_units_by_faction(faction))

    def check_all_eliminated(self, faction: Faction) -> bool:
        """某阵营是否全军覆没（不含 HQ）。

        注意: HQ 作为特殊单位单独检查，这里只检查战斗单位。

        Args:
            faction: 阵营

        Returns:
            True 如果所有非 HQ 单位均已阵亡
        """
        combat_units = [
            u
            for u in self._units.values()
            if u.faction == faction and not u.is_hq
        ]
        return all(not u.is_alive for u in combat_units) if combat_units else True

    # ── HQ 相关 ───────────────────────────────────────────────────────────

    def get_hq(self, faction: Faction) -> Unit | None:
        """获取某阵营指挥所。

        Args:
            faction: 阵营

        Returns:
            HQ 单位，不存在返回 None
        """
        for u in self._units.values():
            if u.faction == faction and u.is_hq:
                return u
        return None

    def is_hq_alive(self, faction: Faction) -> bool:
        """指挥所是否存活。

        Args:
            faction: 阵营

        Returns:
            True 如果 HQ 存在且存活
        """
        hq = self.get_hq(faction)
        return hq is not None and hq.is_alive

    # ── 数量限制 ──────────────────────────────────────────────────────────

    @property
    def total_count(self) -> int:
        """已注册单位总数（含已阵亡）。"""
        return len(self._units)

    def count_alive(self) -> int:
        """存活单位总数。"""
        return len(self.get_alive_units())
