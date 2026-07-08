"""
BlindCommand 范围检索 — IRangeQuery 接口的具体实现
=====================================================
本模块提供 `RangeQuery` 类：基于单位列表 + 地图，实现任意切比雪夫半径内的
单位检索、最近敌人查找、敌情存在性判断。供 #3 战斗系统与侦察逻辑调用。

设计要点：
- 距离用切比雪夫，与 attack_range / vision_range 一致
- 返回按距离升序排序，同距按 unit_id 字典序（确定性）
- 仅返回 is_alive 的单位（INV-3）

约束：不依赖 src/battle/ 或 src/ui/

版本：v0.1.0（对齐 CORE_SPEC.md §6）
"""

from __future__ import annotations

from typing import Callable, Optional

from src.core.constants import Coordinate, Faction
from src.core.interfaces import IMap, IRangeQuery, IUnit


def _opposite_faction(faction: Faction) -> Faction:
    """返回对立阵营。"""
    if faction == Faction.FRIENDLY:
        return Faction.ENEMY
    elif faction == Faction.ENEMY:
        return Faction.FRIENDLY
    else:
        raise ValueError(f"未知阵营: {faction}")


class RangeQuery(IRangeQuery):
    """范围检索工具类。

    注入 units_provider（可调用，实时获取存活单位列表）以避免持有
    过期引用。GameMap 用于获取地形/位置信息。
    """

    # ── __init__ ───────────────────────────────────────────────────────

    def __init__(
        self,
        game_map: IMap,
        units_provider: Callable[[], list[IUnit]],
    ) -> None:
        """构造范围检索器。

        Args:
            game_map: 实现 IMap 的地图对象
            units_provider: 无参可调用，返回当前所有存活单位列表
        """
        if units_provider is None:
            raise ValueError("units_provider 不能为 None")
        self._map = game_map
        self._units_provider = units_provider

    # ── 公开 API ──────────────────────────────────────────────────────

    def get_units_in_range(
        self,
        center: Coordinate,
        radius: int,
        faction: Optional[Faction] = None,
        exclude_ids: Optional[set[str]] = None,
    ) -> list[IUnit]:
        """以 center 为中心，radius 为切比雪夫半径检索范围内的存活单位。

        Args:
            center: 检索中心坐标
            radius: 检索半径（切比雪夫距离），1 = 八邻域
            faction: 若指定，仅返回该阵营单位；None 返回全部
            exclude_ids: 排除的单位 ID 集合

        Returns:
            按距离升序排列的单位列表；同距离按 unit_id 字典序
        """
        if radius < 0:
            return []

        exclude_ids = exclude_ids or set()
        collected: list[tuple[int, str, IUnit]] = []

        for u in self._units_provider():
            if not u.is_alive:
                continue
            if u.unit_id in exclude_ids:
                continue
            if faction is not None and u.faction != faction:
                continue

            dist = center.chebyshev_distance(u.position)
            if dist <= radius:
                collected.append((dist, u.unit_id, u))

        collected.sort(key=lambda t: (t[0], t[1]))
        return [u for _, _, u in collected]

    def find_nearest_enemy(self, unit: IUnit) -> Optional[IUnit]:
        """找到某单位视野范围内最近的敌人。

        Args:
            unit: 查询单位

        Returns:
            最近敌人，若无则返回 None
        """
        enemies = self.get_units_in_range(
            center=unit.position,
            radius=unit.vision_range,
            faction=_opposite_faction(unit.faction),
            exclude_ids={unit.unit_id},
        )
        return enemies[0] if enemies else None

    def has_enemy_in_range(self, unit: IUnit, radius: int) -> bool:
        """某单位指定范围内是否有敌人（短路版本）。

        发现第一个敌人即返回 True，避免全量扫描+排序。

        Args:
            unit: 查询单位
            radius: 检索半径

        Returns:
            True 若范围内存活敌人 ≥ 1
        """
        target_faction = _opposite_faction(unit.faction)
        for u in self._units_provider():
            if not u.is_alive:
                continue
            if u.faction != target_faction:
                continue
            if u.unit_id == unit.unit_id:
                continue
            if unit.position.chebyshev_distance(u.position) <= radius:
                return True
        return False
