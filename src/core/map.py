"""
BlindCommand 地图管理 — IMap 接口的具体实现
=============================================
本模块提供 `GameMap` 类：二维地形数组、格子占用表、越界/通行判断、
A* 寻路（最小移动消耗）、单位放置/移除/移动、双方指挥所坐标。

约束：
- 不持有单位总表（单位生命周期由 GameLoop 管理）
- 不 emit 事件
- 不依赖 src/battle/ 或 src/ui/

版本：v0.1.0（对齐 CORE_SPEC.md §4）
"""

from __future__ import annotations

import heapq
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

from src.core.constants import (
    MAP_MAX_SIZE,
    MAP_MIN_SIZE,
    Coordinate,
    Direction,
    Faction,
    TerrainType,
    get_move_cost,
    get_terrain_props,
)
from src.core.constants import is_passable as terrain_is_passable
from src.core.interfaces import IMap, IUnit


class GameMap(IMap):
    """地图管理类。

    维护二维地形矩阵和格子占用状态。支持 A* 寻路、单位放置与移动、
    地形查询。HQ 格允许「HQ 单位 + 1 围攻者」双占（CORE_SPEC.md C-4）。

    Attributes:
        _terrain: height × width 地形编码矩阵
        _occupancy: 坐标 → 该格上的单位列表（普通格最多 1 个，HQ 格最多 2 个）
        _hq_locations: 双方指挥所坐标
        _allow_stacking_on_hq: 是否允许 HQ 双占（默认 True）
    """

    # ── __init__ ───────────────────────────────────────────────────────

    def __init__(
        self,
        terrain: list[list[int]],
        friendly_hq: Coordinate,
        enemy_hq: Coordinate,
        allow_stacking_on_hq: bool = True,
    ) -> None:
        """构造地图。

        Args:
            terrain: height×width 地形编码矩阵（0=平原, 1=森林, …）
            friendly_hq: 友军指挥所坐标
            enemy_hq: 敌军指挥所坐标
            allow_stacking_on_hq: 是否允许 HQ 格双占

        Raises:
            ValueError: 若矩阵为空、各行长度不一致
        """
        height = len(terrain)
        if height == 0:
            raise ValueError("地形矩阵不能为空")
        width = len(terrain[0])

        if not all(len(row) == width for row in terrain):
            raise ValueError("地形矩阵各行长度不一致")

        self._width = width
        self._height = height
        self._terrain = terrain
        self._occupancy: dict[Coordinate, list[IUnit]] = defaultdict(list)
        self._allow_stacking_on_hq = allow_stacking_on_hq
        self._hq_locations: dict[Faction, Coordinate] = {
            Faction.FRIENDLY: friendly_hq,
            Faction.ENEMY: enemy_hq,
        }

        # 校验 HQ 坐标
        for faction, coord in self._hq_locations.items():
            if not self.is_within_bounds(coord):
                raise ValueError(f"{faction.value} 指挥所坐标 {coord} 越界")
            if not self.is_passable(coord):
                raise ValueError(f"{faction.value} 指挥所坐标 {coord} 不可通行")

    # ── 工厂方法 ──────────────────────────────────────────────────────

    @classmethod
    def from_map_file(cls, path: str | Path) -> GameMap:
        """从 JSON 地图文件构造 GameMap。

        JSON 格式参考 data/maps/map_01.json：
        - terrain: int[][] 地形矩阵
        - friendly_hq: {"x": int, "y": int}
        - enemy_hq: {"x": int, "y": int}

        Args:
            path: JSON 文件路径

        Returns:
            GameMap 实例

        Raises:
            FileNotFoundError: 文件不存在
            KeyError: JSON 缺少必要字段
        """
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        terrain: list[list[int]] = data["terrain"]
        h = len(terrain)
        w = len(terrain[0]) if h > 0 else 0

        if not (MAP_MIN_SIZE <= w <= MAP_MAX_SIZE):
            raise ValueError(f"地图宽度 {w} 超出限制 [{MAP_MIN_SIZE}, {MAP_MAX_SIZE}]")
        if not (MAP_MIN_SIZE <= h <= MAP_MAX_SIZE):
            raise ValueError(f"地图高度 {h} 超出限制 [{MAP_MIN_SIZE}, {MAP_MAX_SIZE}]")

        friendly_hq = Coordinate(**data["friendly_hq"])
        enemy_hq = Coordinate(**data["enemy_hq"])
        return cls(terrain, friendly_hq, enemy_hq)

    # ── 地图尺寸 ──────────────────────────────────────────────────────

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    # ── 地形查询 ──────────────────────────────────────────────────────

    def get_terrain(self, coord: Coordinate) -> TerrainType:
        """获取指定坐标的地形类型。

        Raises:
            ValueError: 坐标越界
        """
        if not self.is_within_bounds(coord):
            raise ValueError(f"坐标 {coord} 越界")
        return TerrainType(self._terrain[coord.y][coord.x])

    def is_passable(self, coord: Coordinate) -> bool:
        """坐标是否可通行（越界返回 False）。"""
        if not self.is_within_bounds(coord):
            return False
        return terrain_is_passable(self._terrain[coord.y][coord.x])

    def is_within_bounds(self, coord: Coordinate) -> bool:
        """坐标是否在地图范围内。"""
        return 0 <= coord.x < self._width and 0 <= coord.y < self._height

    def get_move_cost(self, coord: Coordinate) -> int:
        """获取通过该格子的移动消耗。越界/不可通行返回 -1。"""
        if not self.is_within_bounds(coord):
            return -1
        return get_move_cost(self._terrain[coord.y][coord.x])

    def get_defense_bonus(self, coord: Coordinate) -> int:
        """获取该格子的地形防御加成。越界返回 0。"""
        if not self.is_within_bounds(coord):
            return 0
        return get_terrain_props(self._terrain[coord.y][coord.x]).defense_bonus

    # ── 单位占用管理 ──────────────────────────────────────────────────

    def get_units_at(self, coord: Coordinate) -> list[IUnit]:
        """获取该坐标上的所有单位（返回副本）。"""
        return list(self._occupancy.get(coord, []))

    def place_unit(self, unit: IUnit, coord: Coordinate) -> bool:
        """将单位放置到地图上。

        失败条件：
        - 坐标越界
        - 坐标不可通行（河流等）
        - **普通格**已有单位占据
        - **HQ 格**已有 HQ 单位 + 围攻者（已达到双占上限）

        成功条件：
        - 普通格空置 → 放置成功
        - HQ 格当前仅有一 HQ 单位且允许双占 → 放置成功（围攻者进入）

        Returns:
            True 如果放置成功
        """
        if not self.is_within_bounds(coord):
            return False
        if not self.is_passable(coord):
            return False

        return self._try_occupy(unit, coord)

    def remove_unit(self, unit: IUnit) -> None:
        """从地图上移除单位（幂等：不存在时静默返回）。"""
        for coord, occupants in list(self._occupancy.items()):
            try:
                occupants.remove(unit)
                if not occupants:
                    del self._occupancy[coord]
                return
            except ValueError:
                continue

    def move_unit(self, unit: IUnit, from_coord: Coordinate, to_coord: Coordinate) -> bool:
        """移动单位（更新格子占用状态）。

        从 from_coord 移除 unit，放置到 to_coord。

        Returns:
            True 如果移动合法（from 有该单位、to 可达且未被不可叠占占据）
        """
        if not self.is_within_bounds(to_coord) or not self.is_passable(to_coord):
            return False

        occupants_from = self._occupancy.get(from_coord, [])
        if unit not in occupants_from:
            return False

        # 尝试放置到目标格（含 HQ 双占逻辑）
        if not self._try_occupy(unit, to_coord):
            return False

        # 从原格移除
        occupants_from.remove(unit)
        if not occupants_from:
            del self._occupancy[from_coord]
        return True

    # ── 八邻域 ────────────────────────────────────────────────────────

    def get_neighbors(self, coord: Coordinate) -> list[Coordinate]:
        """获取八邻域坐标（排除越界和不可通行格）。"""
        result: list[Coordinate] = []
        for d in Direction:
            nb = coord + Coordinate(*d.value)
            if self.is_within_bounds(nb) and self.is_passable(nb):
                result.append(nb)
        return result

    # ── A* 寻路 ───────────────────────────────────────────────────────

    def find_path(
        self, start: Coordinate, end: Coordinate, max_steps: int
    ) -> list[Coordinate]:
        """A* 寻路：在 max_steps 步数预算内，找最小移动消耗路径。

        - 每跨一格消耗 1 步（max_steps 限制跳数）
        - 步内选择移动消耗（move_cost）最小的路径
        - 切比雪夫距离 × 1 作启发式（admissible）
        - 起点或终点不可通行 → 返回空列表
        - 目标超出 max_steps → 返回空列表（全或无语义）

        Args:
            start: 起点
            end: 终点
            max_steps: 最大跳数（等于单位 speed）

        Returns:
            路径坐标列表 [start, ..., end]；不可达时返回 []
        """
        if not self.is_within_bounds(start) or not self.is_within_bounds(end):
            return []
        if not self.is_passable(start) or not self.is_passable(end):
            return []
        if start == end:
            return [start]
        if max_steps < 1:
            return []

        def h(c: Coordinate) -> int:
            return c.chebyshev_distance(end)

        counter = 0
        open_heap: list[tuple[int, int, Coordinate]] = []
        heapq.heappush(open_heap, (h(start), counter, start))

        g_score: dict[Coordinate, int] = {start: 0}
        hops: dict[Coordinate, int] = {start: 0}
        came_from: dict[Coordinate, Coordinate] = {}

        while open_heap:
            _, _, current = heapq.heappop(open_heap)

            if current == end:
                # 重建路径
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return path

            cur_hops = hops[current]
            if cur_hops >= max_steps:
                continue

            for nb in self.get_neighbors(current):
                step_cost = self.get_move_cost(nb)
                tentative_g = g_score[current] + step_cost
                tentative_hops = cur_hops + 1

                prev_g = g_score.get(nb, float("inf"))
                if tentative_g < prev_g and tentative_hops <= max_steps:
                    came_from[nb] = current
                    g_score[nb] = tentative_g
                    hops[nb] = tentative_hops
                    counter += 1
                    heapq.heappush(
                        open_heap, (tentative_g + h(nb), counter, nb)
                    )

        return []

    # ── 指挥所坐标 ────────────────────────────────────────────────────

    def get_faction_hq_location(self, faction: Faction) -> Optional[Coordinate]:
        """获取指定阵营指挥所的坐标。"""
        return self._hq_locations.get(faction)

    # ── 内部辅助 ──────────────────────────────────────────────────────

    def _try_occupy(self, unit: IUnit, coord: Coordinate) -> bool:
        """尝试将单位放入占用表（内部，不做越界/通行检查）。

        处理 HQ 双占逻辑：普通格最多 1 单位；HQ 格最多 1 HQ + 1 围攻者。
        """
        occupants = self._occupancy.get(coord, [])
        if not occupants:
            self._occupancy[coord].append(unit)
            return True

        # 已有占据者
        if not self._allow_stacking_on_hq:
            return False

        # HQ 双占：仅当已有 1 个 HQ 单位且无其他非 HQ 单位时才允许
        has_hq = any(o.is_hq for o in occupants)
        has_non_hq = any(not o.is_hq for o in occupants)

        if has_hq and not has_non_hq and len(occupants) == 1:
            # HQ 格上有 HQ 单位，允许一个围攻者进入（只要新单位不是 HQ）
            if not unit.is_hq:
                self._occupancy[coord].append(unit)
                return True
            # 另一个 HQ 想进入 → 拒绝
            return False

        # 其他情况：普通格或已满 HQ 格 → 拒绝
        return False
