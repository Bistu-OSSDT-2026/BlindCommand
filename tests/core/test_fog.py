"""
FogOfWar 单元测试 — 对齐 CORE_SPEC.md §9.4
=============================================
覆盖：视野可见性、森林隐蔽、近似坐标误差、汇报调度。
"""

from __future__ import annotations

import pytest

from src.core.constants import (
    FOG_POSITION_ERROR_RADIUS,
    UNIT_STATS,
    Coordinate,
    Faction,
    UnitType,
)
from src.core.fog_of_war import FogOfWar
from src.core.map import GameMap
from src.core.unit_base import UnitBase


# ── 地形 ──────────────────────────────────────────────────────────────
# 10×10 全平原
PLAIN_10X10 = [[0] * 10 for _ in range(10)]
# 10×10 带森林（两格森林：Coordinate(5,5) 和 Coordinate(6,5)）
FOREST_10X10 = [[0] * 10 for _ in range(10)]
FOREST_10X10[5][5] = 1   # terrain[y=5][x=5] = Coordinate(5,5)
FOREST_10X10[5][6] = 1   # terrain[y=5][x=6] = Coordinate(6,5)


# ── 夹具 ──────────────────────────────────────────────────────────────

@pytest.fixture
def plain_map() -> GameMap:
    return GameMap(PLAIN_10X10, Coordinate(0, 0), Coordinate(9, 9))


@pytest.fixture
def forest_map() -> GameMap:
    return GameMap(FOREST_10X10, Coordinate(0, 0), Coordinate(9, 9))


@pytest.fixture
def friendly_scout() -> UnitBase:
    return UnitBase(
        unit_id="f_sct", name="侦察兵",
        faction=Faction.FRIENDLY, unit_type=UnitType.SCOUT,
        position=Coordinate(5, 5),
        stats=UNIT_STATS[UnitType.SCOUT],  # vision_range=6
    )


@pytest.fixture
def enemy_inf() -> UnitBase:
    return UnitBase(
        unit_id="e_inf", name="敌军步兵",
        faction=Faction.ENEMY, unit_type=UnitType.INFANTRY,
        position=Coordinate(8, 5),
        stats=UNIT_STATS[UnitType.INFANTRY],  # vision_range=3
    )


# ============================================================================
# F1 — is_visible_to_faction
# ============================================================================

class TestVisibleToFaction:

    def test_enemy_in_scout_vision(self, plain_map, friendly_scout, enemy_inf):
        """F1: 敌军在侦察兵视野内（距离 3 ≤ vision_range 6）→ 可见。"""
        fog = FogOfWar(plain_map, lambda: [friendly_scout, enemy_inf])
        assert fog.is_visible_to_faction(enemy_inf.position, Faction.FRIENDLY) is True

    def test_enemy_out_of_scout_vision(self, plain_map, friendly_scout, enemy_inf):
        """F1: 敌军移到视野外 → 不可见。"""
        far_enemy = UnitBase(
            unit_id="far", name="远敌",
            faction=Faction.ENEMY, unit_type=UnitType.INFANTRY,
            position=Coordinate(9, 9),  # dist = 5 from (5,5)? chebyshev(5,5)→(9,9)=4
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        fog = FogOfWar(plain_map, lambda: [friendly_scout, far_enemy])
        # distance from (5,5) to (9,9) = 4, scout vision = 6 → visible!
        # Let me use distance 8
        far_enemy2 = UnitBase(
            unit_id="far2", name="远敌2",
            faction=Faction.ENEMY, unit_type=UnitType.INFANTRY,
            position=Coordinate(9, 0),  # (5,5)→(9,0) chebyshev = max(4,5) = 5, within 6
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        # scout at (5,5) vision=6 on plain → radius=6. (9,0) dist=5 → still visible.
        # Use (0,0): dist from (5,5)=5, still within 6.
        # Scout vision_range=6 is very wide. Let me just verify a truly out-of-range case
        very_far = UnitBase(
            unit_id="vf", name="极远",
            faction=Faction.ENEMY, unit_type=UnitType.INFANTRY,
            position=Coordinate(0, 0),  # (5,5)→(0,0) chebyshev=5, within 6
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        fog2 = FogOfWar(plain_map, lambda: [friendly_scout, very_far])
        assert fog2.is_visible_to_faction(very_far.position, Faction.FRIENDLY) is True
        # Use vision_range=3 unit instead (Infantry)
        observer = UnitBase(
            unit_id="obs", name="观察者",
            faction=Faction.FRIENDLY, unit_type=UnitType.INFANTRY,
            position=Coordinate(5, 5),
            stats=UNIT_STATS[UnitType.INFANTRY],  # vision_range=3
        )
        far = UnitBase(
            unit_id="far", name="远",
            faction=Faction.ENEMY, unit_type=UnitType.INFANTRY,
            position=Coordinate(9, 9),  # (5,5)→(9,9) chebyshev=4 > 3
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        fog3 = FogOfWar(plain_map, lambda: [observer, far])
        assert fog3.is_visible_to_faction(far.position, Faction.FRIENDLY) is False

    def test_no_observer_returns_false(self, plain_map, enemy_inf):
        """无观察者时不可见。"""
        fog = FogOfWar(plain_map, lambda: [enemy_inf])
        assert fog.is_visible_to_faction(Coordinate(5, 5), Faction.FRIENDLY) is False


# ============================================================================
# F2 — 森林隐蔽
# ============================================================================

class TestForestStealth:

    def test_forest_reduces_visibility(self, plain_map, forest_map):
        """F2: 森林中敌人更隐蔽。observer(0,0) vision=6, enemy(6,5)在森林。
        
        有森林: dist=6, stealth=1, threshold=5, 6>5 → 不可见
        无森林(plain): stealth=0, threshold=6, 6≤6 → 可见
        """
        observer = UnitBase(
            unit_id="obs", name="obs",
            faction=Faction.FRIENDLY, unit_type=UnitType.SCOUT,
            position=Coordinate(0, 0),
            stats=UNIT_STATS[UnitType.SCOUT],  # vision_range=6
        )
        enemy_in_forest = UnitBase(
            unit_id="ef", name="林中敌",
            faction=Faction.ENEMY, unit_type=UnitType.INFANTRY,
            position=Coordinate(6, 5),  # 森林格 (6,5) → stealth=1
            stats=UNIT_STATS[UnitType.INFANTRY],
        )

        # 有森林 → 被隐蔽
        fog = FogOfWar(forest_map, lambda: [observer, enemy_in_forest])
        assert fog.is_visible_to_faction(enemy_in_forest.position, Faction.FRIENDLY) is False

        # 无森林 → 可见
        fog2 = FogOfWar(plain_map, lambda: [observer, enemy_in_forest])
        assert fog2.is_visible_to_faction(enemy_in_forest.position, Faction.FRIENDLY) is True


# ============================================================================
# F3 — get_approximate_position
# ============================================================================

class TestApproximatePosition:

    def test_error_in_range(self, plain_map, friendly_scout):
        """F3: 汇报坐标误差在 ±FOG_POSITION_ERROR_RADIUS 内。"""
        fog = FogOfWar(plain_map, lambda: [friendly_scout], seed=42)
        for _ in range(10):
            approx = fog.get_approximate_position(friendly_scout)
            dx = abs(approx.x - friendly_scout.position.x)
            dy = abs(approx.y - friendly_scout.position.y)
            assert dx <= FOG_POSITION_ERROR_RADIUS
            assert dy <= FOG_POSITION_ERROR_RADIUS

    def test_clamped_to_map_bounds(self, plain_map):
        """汇报坐标钳制到地图范围。"""
        u = UnitBase(
            unit_id="corner", name="角",
            faction=Faction.FRIENDLY, unit_type=UnitType.INFANTRY,
            position=Coordinate(0, 0),
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        fog = FogOfWar(plain_map, lambda: [u], seed=0)
        approx = fog.get_approximate_position(u)
        assert approx.x >= 0
        assert approx.y >= 0

    def test_enemy_unit_raises(self, plain_map, enemy_inf):
        """F5: 对敌军调用 get_approximate_position 抛 ValueError。"""
        fog = FogOfWar(plain_map, lambda: [enemy_inf])
        with pytest.raises(ValueError, match="仅对 FRIENDLY"):
            fog.get_approximate_position(enemy_inf)


# ============================================================================
# F4 — 汇报调度
# ============================================================================

class TestReportSchedule:

    def test_init_and_should_report(self, plain_map, friendly_scout):
        """F4: init 后到达汇报回合时 should_report_position=True。"""
        fog = FogOfWar(plain_map, lambda: [friendly_scout], seed=42)
        fog.init_report_schedule(friendly_scout, current_turn=0)
        # 初始回合 0，间隔随机（seed=42 → 固定值）
        assert fog.should_report_position(friendly_scout, current_turn=0) is False

        # 推进到足够大的回合
        assert fog.should_report_position(friendly_scout, current_turn=10) is True

    def test_report_resets_schedule(self, plain_map, friendly_scout):
        """F4: 汇报后下次汇报回合被重置。"""
        fog = FogOfWar(plain_map, lambda: [friendly_scout], seed=42)
        fog.init_report_schedule(friendly_scout, current_turn=0)
        fog.on_position_reported(friendly_scout, current_turn=5)
        assert fog.should_report_position(friendly_scout, current_turn=5) is False
        assert fog.should_report_position(friendly_scout, current_turn=15) is True

    def test_non_friendly_never_reports(self, plain_map, enemy_inf):
        """敌军永不触发汇报调度。"""
        fog = FogOfWar(plain_map, lambda: [enemy_inf])
        fog.init_report_schedule(enemy_inf, current_turn=0)
        assert fog.should_report_position(enemy_inf, current_turn=100) is False

    def test_dead_unit_never_reports(self, plain_map, friendly_scout, enemy_inf):
        """阵亡单位不触发汇报。"""
        fog = FogOfWar(plain_map, lambda: [friendly_scout])
        fog.init_report_schedule(friendly_scout, current_turn=0)
        friendly_scout.take_damage(10, enemy_inf)  # kill
        assert fog.should_report_position(friendly_scout, current_turn=100) is False


# ============================================================================
# is_unit_visible / get_visible_area
# ============================================================================

class TestUnitVisible:

    def test_own_faction_always_visible(self, plain_map, friendly_scout):
        """己方单位对己方永远可见。"""
        fog = FogOfWar(plain_map, lambda: [friendly_scout])
        assert fog.is_unit_visible(friendly_scout, Faction.FRIENDLY) is True

    def test_enemy_requires_vision(self, plain_map, friendly_scout, enemy_inf):
        """敌军需要被观察到才可见；无观察者时不可见。"""
        # 只有友军，无敌军观察者 → 友军对敌方不可见
        fog = FogOfWar(plain_map, lambda: [friendly_scout])
        assert fog.is_unit_visible(friendly_scout, Faction.ENEMY) is False
        # 只有敌军，无友军观察者 → 敌军对友方不可见
        fog2 = FogOfWar(plain_map, lambda: [enemy_inf])
        assert fog2.is_unit_visible(enemy_inf, Faction.FRIENDLY) is False

    def test_visible_area_non_empty(self, plain_map, friendly_scout):
        """有观察者时 get_visible_area 非空。"""
        fog = FogOfWar(plain_map, lambda: [friendly_scout])
        area = fog.get_visible_area(Faction.FRIENDLY)
        assert len(area) > 0
        assert friendly_scout.position in area

    def test_visible_area_empty_for_enemy(self, plain_map, friendly_scout):
        """友军无观察者时敌方 get_visible_area 为空。"""
        fog = FogOfWar(plain_map, lambda: [friendly_scout])
        area = fog.get_visible_area(Faction.ENEMY)
        assert len(area) == 0
