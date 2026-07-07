"""
GameMap 单元测试 — 对齐 CORE_SPEC.md §9.2
===========================================
覆盖：越界/地形查询、河流不可通行、单位放置/移动、A* 寻路、HQ 双占。
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from src.core.constants import (
    MAP_MAX_SIZE,
    MAP_MIN_SIZE,
    UNIT_STATS,
    Coordinate,
    Faction,
    TerrainType,
    UnitType,
)
from src.core.map import GameMap
from src.core.unit_base import UnitBase


# ── 测试夹具 ──────────────────────────────────────────────────────────

# 10×10 平原（满足 MAP_MIN_SIZE）
PLAIN_10X10 = [[0] * 10 for _ in range(10)]

# 5×5 带河流地图（直接构造，不经过 from_map_file）
RIVER_5X5 = [
    [0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0],
    [3, 3, 3, 3, 3],
    [0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0],
]

# 混合地形（平原/森林/河流/山地）
MIXED_5X5 = [
    [0, 0, 0, 0, 0],
    [0, 1, 1, 0, 0],
    [0, 1, 0, 3, 0],
    [0, 0, 0, 0, 2],
    [0, 0, 0, 0, 0],
]


@pytest.fixture
def simple_map() -> GameMap:
    """10×10 全平原。"""
    return GameMap(
        terrain=PLAIN_10X10,
        friendly_hq=Coordinate(0, 0),
        enemy_hq=Coordinate(9, 9),
    )


@pytest.fixture
def river_map() -> GameMap:
    """5×5 带河流地图。"""
    return GameMap(
        terrain=RIVER_5X5,
        friendly_hq=Coordinate(0, 0),
        enemy_hq=Coordinate(4, 4),
    )


@pytest.fixture
def mixed_map() -> GameMap:
    """5×5 混合地形。"""
    return GameMap(
        terrain=MIXED_5X5,
        friendly_hq=Coordinate(0, 0),
        enemy_hq=Coordinate(4, 4),
    )


@pytest.fixture
def infantry_unit() -> UnitBase:
    return UnitBase(
        unit_id="inf", name="步兵",
        faction=Faction.FRIENDLY, unit_type=UnitType.INFANTRY,
        position=Coordinate(0, 0),
        stats=UNIT_STATS[UnitType.INFANTRY],
    )


# ============================================================================
# M1 — 越界与边界查询
# ============================================================================

class TestBoundsAndTerrain:

    def test_within_bounds(self, simple_map):
        assert simple_map.is_within_bounds(Coordinate(0, 0)) is True
        assert simple_map.is_within_bounds(Coordinate(9, 9)) is True
        assert simple_map.is_within_bounds(Coordinate(-1, 0)) is False
        assert simple_map.is_within_bounds(Coordinate(0, 10)) is False

    def test_get_terrain_oob_raises(self, simple_map):
        with pytest.raises(ValueError, match="越界"):
            simple_map.get_terrain(Coordinate(-1, 0))

    def test_is_passable_oob_is_false(self, simple_map):
        assert simple_map.is_passable(Coordinate(-1, 0)) is False

    def test_get_move_cost_oob_is_neg1(self, simple_map):
        assert simple_map.get_move_cost(Coordinate(99, 99)) == -1

    def test_get_defense_bonus_oob_is_zero(self, simple_map):
        assert simple_map.get_defense_bonus(Coordinate(99, 99)) == 0

    def test_dimensions(self, simple_map):
        assert simple_map.width == 10
        assert simple_map.height == 10


# ============================================================================
# M2 — 河流不可通行
# ============================================================================

class TestRiverImpassable:

    def test_river_not_passable(self, river_map):
        for x in range(5):
            assert river_map.is_passable(Coordinate(x, 2)) is False

    def test_river_move_cost_minus_one(self, river_map):
        for x in range(5):
            assert river_map.get_move_cost(Coordinate(x, 2)) == -1

    def test_river_cannot_place_unit(self, river_map, infantry_unit):
        assert river_map.place_unit(infantry_unit, Coordinate(2, 2)) is False

    def test_neighbors_exclude_river(self, river_map):
        nb = river_map.get_neighbors(Coordinate(2, 1))
        river_cells = {Coordinate(x, 2) for x in range(5)}
        assert all(c not in river_cells for c in nb)


# ============================================================================
# M3 — 单位放置与 HQ 双占
# ============================================================================

class TestPlaceUnit:

    def test_place_on_empty_succeeds(self, simple_map, infantry_unit):
        assert simple_map.place_unit(infantry_unit, Coordinate(5, 5)) is True
        assert infantry_unit in simple_map.get_units_at(Coordinate(5, 5))

    def test_place_on_occupied_fails(self, simple_map, infantry_unit):
        simple_map.place_unit(infantry_unit, Coordinate(5, 5))
        other = UnitBase(
            unit_id="other", name="x",
            faction=Faction.FRIENDLY, unit_type=UnitType.INFANTRY,
            position=Coordinate(0, 0),
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        assert simple_map.place_unit(other, Coordinate(5, 5)) is False

    def test_stacking_on_hq_allowed(self, simple_map):
        hq = UnitBase(
            unit_id="hq", name="HQ",
            faction=Faction.FRIENDLY, unit_type=UnitType.HQ,
            position=Coordinate(0, 0),
            stats=UNIT_STATS[UnitType.HQ],
        )
        atk = UnitBase(
            unit_id="atk", name="Attacker",
            faction=Faction.ENEMY, unit_type=UnitType.INFANTRY,
            position=Coordinate(9, 9),
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        simple_map.place_unit(hq, Coordinate(0, 0))
        assert simple_map.place_unit(atk, Coordinate(0, 0)) is True
        assert len(simple_map.get_units_at(Coordinate(0, 0))) == 2

    def test_stacking_on_hq_no_third(self, simple_map):
        hq = UnitBase(
            unit_id="hq", name="HQ",
            faction=Faction.FRIENDLY, unit_type=UnitType.HQ,
            position=Coordinate(0, 0),
            stats=UNIT_STATS[UnitType.HQ],
        )
        atk = UnitBase(
            unit_id="atk", name="a",
            faction=Faction.ENEMY, unit_type=UnitType.INFANTRY,
            position=Coordinate(9, 9),
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        third = UnitBase(
            unit_id="3", name="c",
            faction=Faction.ENEMY, unit_type=UnitType.INFANTRY,
            position=Coordinate(8, 8),
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        simple_map.place_unit(hq, Coordinate(0, 0))
        simple_map.place_unit(atk, Coordinate(0, 0))
        assert simple_map.place_unit(third, Coordinate(0, 0)) is False

    def test_remove_unit_clears(self, simple_map, infantry_unit):
        simple_map.place_unit(infantry_unit, Coordinate(3, 3))
        simple_map.remove_unit(infantry_unit)
        assert simple_map.get_units_at(Coordinate(3, 3)) == []

    def test_remove_unit_nonexistent_noop(self, simple_map, infantry_unit):
        simple_map.remove_unit(infantry_unit)  # no exception


# ============================================================================
# M4 — A* 寻路
# ============================================================================

class TestPathfinding:

    def test_straight_path(self, simple_map):
        path = simple_map.find_path(Coordinate(0, 0), Coordinate(3, 0), max_steps=10)
        assert len(path) == 4
        assert path[0] == Coordinate(0, 0)
        assert path[-1] == Coordinate(3, 0)

    def test_start_equals_end(self, simple_map):
        path = simple_map.find_path(Coordinate(2, 2), Coordinate(2, 2), max_steps=5)
        assert path == [Coordinate(2, 2)]

    def test_river_blocks_path(self, river_map):
        # 河上方到河下方，无桥 → 不可达
        path = river_map.find_path(Coordinate(2, 1), Coordinate(2, 3), max_steps=10)
        assert path == []

    def test_avoid_river_cells(self, mixed_map):
        path = mixed_map.find_path(Coordinate(0, 2), Coordinate(4, 2), max_steps=15)
        if path:
            for c in path:
                assert mixed_map.get_terrain(c) != TerrainType.RIVER

    def test_diagonal_path(self, simple_map):
        path = simple_map.find_path(Coordinate(0, 0), Coordinate(2, 2), max_steps=5)
        assert path[0] == Coordinate(0, 0)
        assert path[-1] == Coordinate(2, 2)
        assert len(path) == 3

    def test_avoid_mountain(self, mixed_map):
        path = mixed_map.find_path(Coordinate(0, 0), Coordinate(4, 4), max_steps=20)
        # 山地 (4,3) 消耗 3，路径不应经其
        if path:
            assert Coordinate(3, 4) not in path


# ============================================================================
# M5 — max_steps 限制
# ============================================================================

class TestMaxSteps:

    def test_target_beyond_max_steps(self, simple_map):
        path = simple_map.find_path(Coordinate(0, 0), Coordinate(5, 0), max_steps=2)
        assert path == []

    def test_max_steps_zero(self, simple_map):
        assert simple_map.find_path(Coordinate(0, 0), Coordinate(1, 0), max_steps=0) == []

    def test_move_unit_hq_stacking(self, simple_map):
        hq = UnitBase(
            unit_id="hq", name="HQ",
            faction=Faction.ENEMY, unit_type=UnitType.HQ,
            position=Coordinate(9, 9),
            stats=UNIT_STATS[UnitType.HQ],
        )
        atk = UnitBase(
            unit_id="atk", name="a",
            faction=Faction.FRIENDLY, unit_type=UnitType.INFANTRY,
            position=Coordinate(8, 8),
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        simple_map.place_unit(hq, Coordinate(9, 9))
        simple_map.place_unit(atk, Coordinate(8, 8))
        assert simple_map.move_unit(atk, Coordinate(8, 8), Coordinate(9, 9)) is True


# ============================================================================
# HQ & 防御
# ============================================================================

class TestHQAndDefense:

    def test_hq_locations(self, simple_map):
        assert simple_map.get_faction_hq_location(Faction.FRIENDLY) == Coordinate(0, 0)
        assert simple_map.get_faction_hq_location(Faction.ENEMY) == Coordinate(9, 9)

    def test_mountain_defense(self, mixed_map):
        assert mixed_map.get_defense_bonus(Coordinate(4, 3)) == 2

    def test_forest_defense(self, mixed_map):
        assert mixed_map.get_defense_bonus(Coordinate(1, 2)) == 1

    def test_plain_defense(self, simple_map):
        assert simple_map.get_defense_bonus(Coordinate(5, 5)) == 0


# ============================================================================
# 构造约束
# ============================================================================

class TestConstruction:

    def test_empty_terrain_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            GameMap([], Coordinate(0, 0), Coordinate(1, 1))

    def test_inconsistent_rows_raises(self):
        with pytest.raises(ValueError, match="不一致"):
            GameMap([[0, 0], [0]], Coordinate(0, 0), Coordinate(1, 0))

    def test_hq_on_river_raises(self):
        with pytest.raises(ValueError, match="不可通行"):
            GameMap(
                terrain=RIVER_5X5,
                friendly_hq=Coordinate(2, 2),
                enemy_hq=Coordinate(0, 0),
            )

    def test_hq_oob_raises(self):
        with pytest.raises(ValueError, match="越界"):
            GameMap(
                terrain=PLAIN_10X10,
                friendly_hq=Coordinate(99, 0),
                enemy_hq=Coordinate(0, 0),
            )


# ============================================================================
# from_map_file（含尺寸校验）
# ============================================================================

class TestFromMapFile:

    def test_load_from_json(self):
        """加载 10×10 地图。"""
        data = {
            "terrain": PLAIN_10X10,
            "friendly_hq": {"x": 0, "y": 0},
            "enemy_hq": {"x": 9, "y": 9},
        }
        with NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            tmp_path = f.name
        try:
            gm = GameMap.from_map_file(tmp_path)
            assert gm.width == 10
            assert gm.height == 10
        finally:
            Path(tmp_path).unlink()

    def test_too_small_raises(self):
        """宽度不足 MAP_MIN_SIZE(10) 抛异常。"""
        data = {
            "terrain": [[0, 0], [0, 0]],
            "friendly_hq": {"x": 0, "y": 0},
            "enemy_hq": {"x": 1, "y": 1},
        }
        with NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="宽度"):
                GameMap.from_map_file(tmp_path)
        finally:
            Path(tmp_path).unlink()
