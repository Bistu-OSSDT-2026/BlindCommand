"""
基础自测 — 验证 Phase 0 全局常量完整性
========================================
每个开发人员提交代码前，本地运行：pytest tests/ -v
CI 在每次 push/PR 时自动运行。
"""

import pytest

from src.core.constants import (
    COMBAT_MIN_DAMAGE,
    COMBAT_TYPE_ADVANTAGE_MULT,
    COMMAND_DELAY_MAX,
    COMMAND_DELAY_MIN,
    EVENT_PAYLOAD_MAP,
    FOG_POSITION_ERROR_RADIUS,
    FOG_POSITION_REPORT_INTERVAL_MAX,
    FOG_POSITION_REPORT_INTERVAL_MIN,
    GameEventType,
    MAP_DEFAULT_HEIGHT,
    MAP_DEFAULT_WIDTH,
    MAP_MAX_SIZE,
    MAP_MIN_SIZE,
    MAX_TURNS,
    TERRAIN_IMAGE_FILES,
    TerrainType,
    TERRAIN_PROPS,
    TERRAIN_SYMBOLS,
    TYPE_ADVANTAGE,
    UNIT_DISPLAY_NAMES,
    UNIT_STATS,
    UnitType,
    Coordinate,
    get_advantage_multiplier,
    get_move_cost,
    is_passable,
)


# ============================================================================
# 枚举完整性
# ============================================================================

class TestUnitTypeCompleteness:
    """每种 UnitType 必须有完整的配置。"""

    def test_every_unit_type_has_stats(self):
        for ut in UnitType:
            assert ut in UNIT_STATS, f"UNIT_STATS 缺少 {ut}"

    def test_every_unit_type_has_display_name(self):
        for ut in UnitType:
            assert ut in UNIT_DISPLAY_NAMES, f"UNIT_DISPLAY_NAMES 缺少 {ut}"


class TestTerrainTypeCompleteness:
    """每种 TerrainType 必须有完整的配置。"""

    def test_every_terrain_has_props(self):
        for tt in TerrainType:
            assert tt in TERRAIN_PROPS, f"TERRAIN_PROPS 缺少 {tt}"

    def test_every_terrain_has_symbol(self):
        for tt in TerrainType:
            assert tt in TERRAIN_SYMBOLS, f"TERRAIN_SYMBOLS 缺少 {tt}"

    def test_every_terrain_has_image_file(self):
        for tt in TerrainType:
            assert tt in TERRAIN_IMAGE_FILES, f"TERRAIN_IMAGE_FILES 缺少 {tt}"


class TestEventPayloadCompleteness:
    """每种 GameEventType 必须有载荷映射。"""

    def test_every_event_type_has_payload_map(self):
        for event_type in GameEventType:
            assert event_type in EVENT_PAYLOAD_MAP, (
                f"EVENT_PAYLOAD_MAP 缺少 {event_type}"
            )


# ============================================================================
# 数值合理性
# ============================================================================

class TestNumericalSanity:
    """数值范围合理性检查。"""

    def test_combat_type_advantage_above_one(self):
        assert COMBAT_TYPE_ADVANTAGE_MULT > 1.0, "克制倍率必须 > 1.0"

    def test_combat_min_damage_positive(self):
        assert COMBAT_MIN_DAMAGE >= 1, "最小伤害必须 ≥ 1"

    def test_command_delay_order(self):
        assert COMMAND_DELAY_MIN <= COMMAND_DELAY_MAX, (
            f"延迟最小值({COMMAND_DELAY_MIN}) ≤ 最大值({COMMAND_DELAY_MAX})"
        )

    def test_fog_report_interval_order(self):
        assert FOG_POSITION_REPORT_INTERVAL_MIN <= FOG_POSITION_REPORT_INTERVAL_MAX

    def test_fog_error_radius_non_negative(self):
        assert FOG_POSITION_ERROR_RADIUS >= 0

    def test_map_size_order(self):
        assert MAP_MIN_SIZE <= MAP_DEFAULT_WIDTH <= MAP_MAX_SIZE
        assert MAP_MIN_SIZE <= MAP_DEFAULT_HEIGHT <= MAP_MAX_SIZE

    def test_max_turns_positive(self):
        assert MAX_TURNS > 0


# ============================================================================
# 兵种数值
# ============================================================================

class TestUnitStats:
    """兵种属性合理性。"""

    def test_all_units_have_positive_hp(self):
        for ut, stats in UNIT_STATS.items():
            assert stats.max_hp > 0, f"{ut} 血量必须 > 0，当前 {stats.max_hp}"

    def test_combat_units_have_positive_speed(self):
        """非 HQ 兵种应该能移动。"""
        for ut, stats in UNIT_STATS.items():
            if not stats.is_hq:
                assert stats.speed > 0, f"{ut} 速度必须 > 0"

    def test_hq_cannot_attack(self):
        hq_stats = UNIT_STATS[UnitType.HQ]
        assert hq_stats.attack == 0, "指挥所攻击力必须为 0"
        assert hq_stats.attack_range == 0, "指挥所攻击范围必须为 0"

    def test_hq_is_marked_as_hq(self):
        assert UNIT_STATS[UnitType.HQ].is_hq is True


# ============================================================================
# 克制关系
# ============================================================================

class TestTypeAdvantage:
    """兵种克制关系检查。"""

    def test_advantage_is_symmetric_triangle(self):
        """验证三角克制：步→骑 骑→炮 炮→步。"""
        assert get_advantage_multiplier(UnitType.INFANTRY, UnitType.CAVALRY) == 1.5
        assert get_advantage_multiplier(UnitType.CAVALRY, UnitType.ARTILLERY) == 1.5
        assert get_advantage_multiplier(UnitType.ARTILLERY, UnitType.INFANTRY) == 1.5

    def test_no_self_advantage(self):
        """同兵种之间无克制。"""
        for ut in UnitType:
            assert get_advantage_multiplier(ut, ut) == 1.0, f"{ut} 不应克制自身"

    def test_non_advantage_returns_one(self):
        """无克制关系的组合返回 1.0。"""
        assert get_advantage_multiplier(UnitType.INFANTRY, UnitType.ARTILLERY) == 1.0
        assert get_advantage_multiplier(UnitType.SCOUT, UnitType.CAVALRY) == 1.0

    def test_advantage_table_only_contains_valid_types(self):
        """TYPE_ADVANTAGE 中不包含未定义的兵种。"""
        for attacker, defenders in TYPE_ADVANTAGE.items():
            assert attacker in UnitType, f"无效攻击方 {attacker}"
            for defender in defenders:
                assert defender in UnitType, f"无效防御方 {defender}"


# ============================================================================
# 地形
# ============================================================================

class TestTerrainProps:
    """地形属性合理性。"""

    def test_plain_is_passable(self):
        assert is_passable(TerrainType.PLAIN.value)

    def test_river_is_impassable(self):
        assert not is_passable(TerrainType.RIVER.value)

    def test_bridge_is_passable(self):
        assert is_passable(TerrainType.BRIDGE.value)

    def test_move_cost_river_is_negative(self):
        assert get_move_cost(TerrainType.RIVER.value) == -1


# ============================================================================
# Coordinate 数据类
# ============================================================================

class TestCoordinate:
    """坐标操作。"""

    def test_manhattan_distance(self):
        assert Coordinate(0, 0).manhattan_distance(Coordinate(3, 4)) == 7

    def test_chebyshev_distance(self):
        assert Coordinate(0, 0).chebyshev_distance(Coordinate(3, 4)) == 4

    def test_addition(self):
        result = Coordinate(3, 4) + Coordinate(1, 2)
        assert result == Coordinate(4, 6)

    def test_subtraction(self):
        result = Coordinate(3, 4) - Coordinate(1, 2)
        assert result == Coordinate(2, 2)

    def test_immutable(self):
        c = Coordinate(1, 2)
        with pytest.raises(Exception):
            c.x = 5  # type: ignore[misc]
