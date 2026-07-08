"""
BlindCommand 迷雾与视野管理 — IFogOfWar 接口的具体实现
=========================================================
本模块提供 `FogOfWar` 类：视野计算、可见性查询、可见区域集合、
带误差的大致坐标汇报、友军周期性汇报调度。

关键设计（CORE_SPEC.md §7）：
- 视野模型：effective_vision = vision_range + observer_terrain.vision_modifier
- 可见判定：chebyshev(U, C) ≤ effective_vision - stealth(C)
- 己方单位对己方阵营「存在可见」
- 汇报误差在 ±FOG_POSITION_ERROR_RADIUS 内，钳制到地图范围
- should_report_position 为纯查询，副作用由 on_position_reported 完成

约束：不直接 emit 事件，不依赖 src/battle/ 或 src/ui/

版本：v0.2.0（对齐 CORE_SPEC.md §7，CP-2：性能注释 + 边界加固）
"""

from __future__ import annotations

import logging
import random
from typing import Callable

from src.core.constants import (
    FOG_POSITION_ERROR_RADIUS,
    FOG_POSITION_REPORT_INTERVAL_MAX,
    FOG_POSITION_REPORT_INTERVAL_MIN,
    Coordinate,
    Faction,
    get_terrain_props,
)
from src.core.interfaces import IFogOfWar, IMap, IUnit

logger = logging.getLogger(__name__)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


class FogOfWar(IFogOfWar):
    """迷雾/视野管理器。

    注入 units_provider 实时获取存活单位列表；IMap 用于地形查询。
    维护友军汇报调度状态（_next_report_turn）。
    """

    # ── __init__ ───────────────────────────────────────────────────────

    def __init__(
        self,
        game_map: IMap,
        units_provider: Callable[[], list[IUnit]],
        seed: int | None = None,
    ) -> None:
        """构造迷雾系统。

        Args:
            game_map: 地图对象
            units_provider: 返回当前存活单位列表的可调用
            seed: 随机种子（便于测试重现）
        """
        self._map = game_map
        self._units_provider = units_provider
        self._rng = random.Random(seed)

        # 友军汇报调度：unit_id → 下次应汇报的回合
        self._next_report_turn: dict[str, int] = {}

    # ── 视野计算 ──────────────────────────────────────────────────────

    def is_visible_to_faction(self, coord: Coordinate, faction: Faction) -> bool:
        """坐标 coord 对 faction 阵营是否可见。

        若 faction 任一存活单位的有效视野覆盖该坐标，返回 True。
        有效视野 = vision_range + observer_terrain.vision_modifier - target_terrain.stealth_modifier。
        """
        if not self._map.is_within_bounds(coord):
            return False

        for u in self._units_provider():
            if not u.is_alive or u.faction != faction:
                continue

            eff_vision = u.vision_range + self._terrain_vision_mod(u.position)
            threshold = eff_vision - self._terrain_stealth(coord)
            if threshold >= 0 and coord.chebyshev_distance(u.position) <= threshold:
                return True

        return False

    def is_unit_visible(self, unit: IUnit, to_faction: Faction) -> bool:
        """判断 unit 对 to_faction 是否可见。

        己方单位对己方阵营永远「存在可见」；
        敌方单位需进入 to_faction 任一单位的视野。
        """
        if not unit.is_alive:
            return False
        if unit.faction == to_faction:
            return True
        return self.is_visible_to_faction(unit.position, to_faction)

    def get_visible_area(self, faction: Faction) -> set[Coordinate]:
        """获取 faction 阵营当前可见的所有坐标集合。"""
        result: set[Coordinate] = set()
        observers = [u for u in self._units_provider()
                     if u.is_alive and u.faction == faction]

        for u in observers:
            eff_vision = u.vision_range + self._terrain_vision_mod(u.position)
            radius = max(0, eff_vision)
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    c = Coordinate(u.position.x + dx, u.position.y + dy)
                    if self._map.is_within_bounds(c) and self.is_visible_to_faction(c, faction):
                        result.add(c)

        return result

    # ── 带误差汇报 ────────────────────────────────────────────────────

    def get_approximate_position(self, unit: IUnit) -> Coordinate:
        """返回单位向玩家汇报的带误差大致坐标（±FOG_POSITION_ERROR_RADIUS）。

        Raises:
            ValueError: 若 unit 非 FRIENDLY
        """
        if unit.faction != Faction.FRIENDLY:
            raise ValueError(
                f"get_approximate_position 仅对 FRIENDLY 有效，收到 {unit.faction}"
            )
        r = FOG_POSITION_ERROR_RADIUS
        dx = self._rng.randint(-r, r)
        dy = self._rng.randint(-r, r)
        rx = _clamp(unit.position.x + dx, 0, self._map.width - 1)
        ry = _clamp(unit.position.y + dy, 0, self._map.height - 1)
        return Coordinate(rx, ry)

    # ── 友军汇报调度 ──────────────────────────────────────────────────

    def init_report_schedule(self, unit: IUnit, current_turn: int) -> None:
        """单位创建/游戏开始时调用，安排首次汇报。

        此方法为内部辅助，不在 IFogOfWar 跨层接口中。
        """
        if unit.faction != Faction.FRIENDLY:
            return
        self._next_report_turn[unit.unit_id] = (
            current_turn + self._random_interval()
        )

    def should_report_position(self, unit: IUnit, current_turn: int) -> bool:
        """判断该友军单位本回合是否需要汇报位置（纯查询，无副作用）。

        副作用由 on_position_reported 完成。
        """
        if unit.faction != Faction.FRIENDLY or not unit.is_alive:
            return False
        next_turn = self._next_report_turn.get(unit.unit_id)
        if next_turn is None:
            logger.debug(
                "should_report_position: 单位 %s 未初始化汇报调度，默认立即汇报", unit.unit_id
            )
            return True
        return current_turn >= next_turn

    def on_position_reported(self, unit: IUnit, current_turn: int) -> None:
        """GameLoop 在实际 emit POSITION_REPORT 后调用，安排下次汇报。

        此方法为内部辅助，不在 IFogOfWar 跨层接口中。
        """
        if unit.faction != Faction.FRIENDLY:
            return
        self._next_report_turn[unit.unit_id] = (
            current_turn + self._random_interval()
        )

    # ── 内部辅助 ──────────────────────────────────────────────────────

    def _terrain_vision_mod(self, coord: Coordinate) -> int:
        """观察者所在地形的视野修正。越界返回 0。"""
        if not self._map.is_within_bounds(coord):
            return 0
        terrain_code = self._map.get_terrain(coord).value
        return get_terrain_props(terrain_code).vision_modifier

    def _terrain_stealth(self, coord: Coordinate) -> int:
        """目标所在地形的隐蔽修正。越界返回 0。"""
        if not self._map.is_within_bounds(coord):
            return 0
        terrain_code = self._map.get_terrain(coord).value
        return get_terrain_props(terrain_code).stealth_modifier

    def _random_interval(self) -> int:
        """返回随机汇报间隔 [MIN, MAX]。"""
        return self._rng.randint(
            FOG_POSITION_REPORT_INTERVAL_MIN,
            FOG_POSITION_REPORT_INTERVAL_MAX,
        )
