"""
UnitBase 单元测试 — 对齐 CORE_SPEC.md §9.1
============================================
覆盖：扣血逻辑、阵亡、幂等、地形防御、can_attack 判定。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.constants import COMBAT_MIN_DAMAGE, UNIT_STATS, Coordinate, Faction, UnitType
from src.core.interfaces import IMap
from src.core.unit_base import UnitBase

# ── 测试夹具 ──────────────────────────────────────────────────────────

@pytest.fixture
def infantry_stats():
    return UNIT_STATS[UnitType.INFANTRY]


@pytest.fixture
def cavalry_stats():
    return UNIT_STATS[UnitType.CAVALRY]


@pytest.fixture
def friendly_infantry(infantry_stats) -> UnitBase:
    return UnitBase(
        unit_id="test_friendly_01",
        name="测试步兵",
        faction=Faction.FRIENDLY,
        unit_type=UnitType.INFANTRY,
        position=Coordinate(5, 5),
        stats=infantry_stats,
    )


@pytest.fixture
def enemy_infantry(infantry_stats) -> UnitBase:
    return UnitBase(
        unit_id="test_enemy_01",
        name="敌军步兵",
        faction=Faction.ENEMY,
        unit_type=UnitType.INFANTRY,
        position=Coordinate(6, 5),
        stats=infantry_stats,
    )


@pytest.fixture
def mock_map_with_defense_bonus():
    """返回一个 mock IMap，get_defense_bonus 返回固定值 2（山地）。"""
    m = MagicMock(spec=IMap)
    m.get_defense_bonus.return_value = 2
    m.is_within_bounds.return_value = True
    return m


# ============================================================================
# U1 — take_damage 正常扣血，返回值 = 实际扣血
# ============================================================================

class TestTakeDamage:

    def test_reduces_hp_and_returns_applied(self, friendly_infantry, enemy_infantry):
        """U1: 正常扣血，返回实际扣血量。"""
        hp_before = friendly_infantry.current_hp
        damage = 5
        applied = friendly_infantry.take_damage(damage, enemy_infantry)

        assert applied == damage
        assert friendly_infantry.current_hp == hp_before - damage
        assert friendly_infantry.is_alive is True

    def test_damage_exceeding_remaining_hp(self, friendly_infantry, enemy_infantry):
        """扣血超过剩余 HP 时，返回值 = 剩余 HP（不超出）。"""
        friendly_infantry.take_damage(8, enemy_infantry)  # HP 10 → 2
        applied = friendly_infantry.take_damage(5, enemy_infantry)  # 剩余 2

        assert applied == 2
        assert friendly_infantry.current_hp == 0
        assert friendly_infantry.is_alive is False

    def test_damage_zero(self, friendly_infantry, enemy_infantry):
        """扣血 0 时 HP 不变。"""
        applied = friendly_infantry.take_damage(0, enemy_infantry)
        assert applied == 0
        assert friendly_infantry.current_hp == friendly_infantry.max_hp

    def test_negative_damage_raises(self, friendly_infantry, enemy_infantry):
        """负数伤害应抛 ValueError。"""
        with pytest.raises(ValueError, match="伤害值不能为负"):
            friendly_infantry.take_damage(-1, enemy_infantry)


# ============================================================================
# U2 — 血量打到 0 → is_alive=False
# ============================================================================

class TestDeath:

    def test_exact_kill_sets_alive_false(self, friendly_infantry, enemy_infantry):
        """U2: 恰好打掉全部 HP → is_alive=False。"""
        friendly_infantry.take_damage(10, enemy_infantry)
        assert friendly_infantry.current_hp == 0
        assert friendly_infantry.is_alive is False

    def test_overkill_still_dead(self, friendly_infantry, enemy_infantry):
        """过量伤害也判定为阵亡。"""
        friendly_infantry.take_damage(999, enemy_infantry)
        assert friendly_infantry.is_alive is False


# ============================================================================
# U3 — 对已阵亡单位 take_damage 幂等
# ============================================================================

class TestIdempotent:

    def test_damage_on_dead_unit_noop(self, friendly_infantry, enemy_infantry):
        """U3: 对已阵亡单位扣血，返回 0 且 HP 不变。"""
        friendly_infantry.take_damage(10, enemy_infantry)  # 阵亡
        applied = friendly_infantry.take_damage(5, enemy_infantry)

        assert applied == 0
        assert friendly_infantry.current_hp == 0


# ============================================================================
# U4 — defense 属性含地形加成
# ============================================================================

class TestDefenseWithTerrain:

    def test_defense_without_map_is_bare(self, infantry_stats):
        """无 Map 引用时 defense = 基础防御。"""
        u = UnitBase(
            unit_id="t1", name="x",
            faction=Faction.FRIENDLY,
            unit_type=UnitType.INFANTRY,
            position=Coordinate(0, 0),
            stats=infantry_stats,
            game_map=None,
        )
        assert u.defense == infantry_stats.defense

    def test_defense_with_map_includes_bonus(self, infantry_stats, mock_map_with_defense_bonus):
        """U4: 有 Map 引用且地形防御 +2 时，defense = base + 2。"""
        u = UnitBase(
            unit_id="t2", name="x",
            faction=Faction.FRIENDLY,
            unit_type=UnitType.INFANTRY,
            position=Coordinate(0, 0),
            stats=infantry_stats,
            game_map=mock_map_with_defense_bonus,
        )
        expected = infantry_stats.defense + 2
        assert u.defense == expected
        mock_map_with_defense_bonus.get_defense_bonus.assert_called_with(u.position)


# ============================================================================
# U5 — can_attack 各种不起效情形
# ============================================================================

class TestCanAttack:

    def test_cannot_attack_same_faction(self, friendly_infantry):
        """同阵营不可攻击。"""
        ally = UnitBase(
            unit_id="ally", name="a",
            faction=Faction.FRIENDLY,
            unit_type=UnitType.INFANTRY,
            position=Coordinate(6, 5),
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        assert friendly_infantry.can_attack(ally) is False

    def test_cannot_attack_out_of_range(self, friendly_infantry, enemy_infantry):
        """超距（attack_range=1 时距离 2 格）不可攻击。"""
        far_enemy = UnitBase(
            unit_id="far", name="b",
            faction=Faction.ENEMY,
            unit_type=UnitType.INFANTRY,
            position=Coordinate(10, 5),  # chebyshev dist 5 > 1
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        assert friendly_infantry.can_attack(far_enemy) is False

    def test_hq_cannot_attack(self):
        """HQ 的 attack_range=0，恒不可攻击。"""
        hq_stats = UNIT_STATS[UnitType.HQ]
        hq = UnitBase(
            unit_id="hq", name="h",
            faction=Faction.FRIENDLY,
            unit_type=UnitType.HQ,
            position=Coordinate(0, 0),
            stats=hq_stats,
        )
        target = UnitBase(
            unit_id="t", name="t",
            faction=Faction.ENEMY,
            unit_type=UnitType.INFANTRY,
            position=Coordinate(0, 0),
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        assert hq.can_attack(target) is False
        assert hq.attack_range == 0

    def test_can_attack_normal_case(self, friendly_infantry, enemy_infantry):
        """正常相邻敌对不同阵营：可以攻击。"""
        neighbor_enemy = UnitBase(
            unit_id="nb", name="e",
            faction=Faction.ENEMY,
            unit_type=UnitType.INFANTRY,
            position=Coordinate(6, 5),  # chebyshev dist 1
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        assert friendly_infantry.can_attack(neighbor_enemy) is True


# ============================================================================
# attack_target 默认实现
# ============================================================================

class TestAttackTarget:

    def test_default_attack_deals_damage(self, friendly_infantry):
        """默认 attack_target 造成 max(1, atk-def) 伤害。"""
        target = UnitBase(
            unit_id="t", name="t",
            faction=Faction.ENEMY,
            unit_type=UnitType.INFANTRY,
            position=Coordinate(6, 5),  # adjacent
            stats=UNIT_STATS[UnitType.INFANTRY],
        )
        atk = friendly_infantry.attack       # 3
        df = target.defense                   # 2
        expected = max(COMBAT_MIN_DAMAGE, atk - df)  # max(1, 1) = 1

        dmg = friendly_infantry.attack_target(target)
        assert dmg == expected
        assert target.current_hp == target.max_hp - expected


# ============================================================================
# get_state_report
# ============================================================================

class TestGetStateReport:

    def test_alive_report(self, friendly_infantry):
        report = friendly_infantry.get_state_report()
        assert "存活" in report
        assert "测试步兵" in report
        assert "步兵" in report
        assert "HP 10/10" in report

    def test_dead_report(self, friendly_infantry, enemy_infantry):
        friendly_infantry.take_damage(10, enemy_infantry)
        report = friendly_infantry.get_state_report()
        assert "阵亡" in report
        assert "HP 0/10" in report
