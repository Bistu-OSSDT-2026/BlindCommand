"""
RangeQuery 单元测试 — 对齐 CORE_SPEC.md §9.3
===============================================
覆盖：范围检索、阵营过滤、最近敌人、空结果。
"""

from __future__ import annotations

import pytest

from src.core.constants import (
    UNIT_STATS,
    Coordinate,
    Faction,
    UnitType,
)
from src.core.range_utils import RangeQuery
from src.core.unit_base import UnitBase

# ── 辅助 ──────────────────────────────────────────────────────────────

def _make_unit(uid: str, x: int, y: int, faction: Faction, utype: UnitType) -> UnitBase:
    return UnitBase(
        unit_id=uid, name=uid,
        faction=faction, unit_type=utype,
        position=Coordinate(x, y),
        stats=UNIT_STATS[utype],
    )


@pytest.fixture
def unit_set():
    """9 个单位布局：
         (0,0) F-infantry  (1,0) F-cavalry   (2,0) F-scout
         (0,1) E-infantry  (1,1) E-cavalry   (2,1) E-scout
         (0,2) E-artillery (1,2) F-artillery (2,2) F-HQ
    """
    units = [
        _make_unit("f_inf",  0, 0, Faction.FRIENDLY, UnitType.INFANTRY),
        _make_unit("f_cav",  1, 0, Faction.FRIENDLY, UnitType.CAVALRY),
        _make_unit("f_sct",  2, 0, Faction.FRIENDLY, UnitType.SCOUT),
        _make_unit("f_art",  1, 2, Faction.FRIENDLY, UnitType.ARTILLERY),
        _make_unit("f_hq",   2, 2, Faction.FRIENDLY, UnitType.HQ),
        _make_unit("e_inf",  0, 1, Faction.ENEMY, UnitType.INFANTRY),
        _make_unit("e_cav",  1, 1, Faction.ENEMY, UnitType.CAVALRY),
        _make_unit("e_sct",  2, 1, Faction.ENEMY, UnitType.SCOUT),
        _make_unit("e_art",  0, 2, Faction.ENEMY, UnitType.ARTILLERY),
    ]
    return {u.unit_id: u for u in units}


@pytest.fixture
def rq(unit_set):
    return RangeQuery(game_map=None, units_provider=lambda: list(unit_set.values()))


# ============================================================================
# R1 — get_units_in_range
# ============================================================================

class TestGetUnitsInRange:

    def test_radius_1_returns_eight_neighbors(self, rq):
        """R1: radius=1 返回八邻域所有单位，按距离+id 排序。"""
        # 中心 (1,1)（敌军骑兵位置）→ 八邻域 = 8 个格子，都有单位
        result = rq.get_units_in_range(center=Coordinate(1, 1), radius=1)
        # 9 个单位中心在 (1,1)，距离 0 的自己，距离 1 的 8 个
        assert len(result) == 9

    def test_radius_0_returns_only_self(self, rq):
        """radius=0 仅返回中心位置上的单位。"""
        result = rq.get_units_in_range(center=Coordinate(0, 0), radius=0)
        ids = [u.unit_id for u in result]
        assert ids == ["f_inf"]

    def test_sorted_by_distance_then_id(self, rq):
        """按距离升序、同距按 unit_id 字典序。"""
        result = rq.get_units_in_range(center=Coordinate(0, 0), radius=2)
        dists = [u.position.chebyshev_distance(Coordinate(0, 0)) for u in result]
        assert dists == sorted(dists)
        # 同距组内 ID 有序
        for i in range(len(result) - 1):
            d1 = result[i].position.chebyshev_distance(Coordinate(0, 0))
            d2 = result[i + 1].position.chebyshev_distance(Coordinate(0, 0))
            if d1 == d2:
                assert result[i].unit_id < result[i + 1].unit_id

    def test_faction_filter(self, rq):
        """R2: faction 过滤仅返回指定阵营。"""
        friendly = rq.get_units_in_range(
            center=Coordinate(1, 1), radius=2, faction=Faction.FRIENDLY
        )
        assert all(u.faction == Faction.FRIENDLY for u in friendly)
        enemy = rq.get_units_in_range(
            center=Coordinate(1, 1), radius=2, faction=Faction.ENEMY
        )
        assert all(u.faction == Faction.ENEMY for u in enemy)

    def test_exclude_ids(self, rq):
        """排除指定 unit_id。"""
        result = rq.get_units_in_range(
            center=Coordinate(1, 1), radius=1, exclude_ids={"e_cav", "f_inf"}
        )
        ids = {u.unit_id for u in result}
        assert "e_cav" not in ids
        assert "f_inf" not in ids

    def test_negative_radius_returns_empty(self, rq):
        assert rq.get_units_in_range(Coordinate(1, 1), radius=-1) == []

    def test_dead_units_excluded(self, rq, unit_set):
        """阵亡单位不出现在结果中（INV-3）。"""
        unit_set["f_inf"].take_damage(10, unit_set["e_inf"])
        result = rq.get_units_in_range(center=Coordinate(0, 0), radius=2)
        ids = {u.unit_id for u in result}
        assert "f_inf" not in ids


# ============================================================================
# R3 — find_nearest_enemy / has_enemy_in_range
# ============================================================================

class TestNearestEnemy:

    def test_find_nearest_enemy_found(self, rq):
        """R3: 找到视野内最近的敌人。"""
        f_inf = [u for u in rq._units_provider() if u.unit_id == "f_inf"][0]
        nearest = rq.find_nearest_enemy(f_inf)
        assert nearest is not None
        assert nearest.faction == Faction.ENEMY
        # e_inf(0,1) 与 e_cav(1,1) 距(0,0)均为 1，按 unit_id 字典序 e_cav < e_inf
        assert nearest.position.chebyshev_distance(Coordinate(0, 0)) == 1

    def test_find_nearest_enemy_none(self, rq):
        """没有敌人时返回 None。"""
        # 把一个友军移到敌军视野外
        tmp = _make_unit("isolated", 10, 10, Faction.FRIENDLY, UnitType.INFANTRY)
        rq2 = RangeQuery(None, lambda: [tmp])
        assert rq2.find_nearest_enemy(tmp) is None

    def test_has_enemy_in_range_true(self, rq):
        f_inf = [u for u in rq._units_provider() if u.unit_id == "f_inf"][0]
        assert rq.has_enemy_in_range(f_inf, radius=1) is True   # e_inf at (0,1)

    def test_has_enemy_in_range_false(self, rq):
        """radius=0 只查同格，同格只有己方。"""
        f_inf = [u for u in rq._units_provider() if u.unit_id == "f_inf"][0]
        assert rq.has_enemy_in_range(f_inf, radius=0) is False

    def test_has_enemy_in_range_detects_enemy(self, rq):
        """radius=1 能检测到相邻敌人。"""
        tmp = _make_unit("tmp", 3, 3, Faction.FRIENDLY, UnitType.SCOUT)
        enm = _make_unit("enm", 3, 4, Faction.ENEMY, UnitType.SCOUT)
        rq2 = RangeQuery(None, lambda: [tmp, enm])
        assert rq2.has_enemy_in_range(tmp, radius=1) is True
        assert rq2.has_enemy_in_range(tmp, radius=0) is False
