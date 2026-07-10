"""
兵种子类测试 — 验证 Unit 基类与 5 个兵种的正确性。

覆盖:
    - 兵种创建与属性验证
    - take_damage / 阵亡逻辑
    - can_attack 范围判定
    - get_state_report 格式
    - HQ 特殊行为（不可攻击/移动）
    - UnitManager 工厂方法与查询

运行: pytest tests/battle/test_units.py -v
"""

from __future__ import annotations

import pytest

from src.battle.unit_manager import _create_unit_instance
from src.battle.units import HQ, Artillery, Cavalry, Infantry, Scout, Unit
from src.core.constants import UNIT_DISPLAY_NAMES, UNIT_STATS, Coordinate, Faction, UnitType

# ============================================================================
# 测试夹具
# ============================================================================


def _make_coord(x: int = 5, y: int = 5) -> Coordinate:
    """快捷创建坐标。"""
    return Coordinate(x, y)


def _make_infantry(
    unit_id: str = "test_inf_01",
    name: str = "测试步兵",
    faction: Faction = Faction.FRIENDLY,
    x: int = 5,
    y: int = 5,
) -> Infantry:
    """快捷创建步兵实例。"""
    return Infantry(unit_id=unit_id, name=name, faction=faction, start_pos=_make_coord(x, y))


def _make_cavalry(
    unit_id: str = "test_cav_01",
    name: str = "测试骑兵",
    faction: Faction = Faction.FRIENDLY,
    x: int = 5,
    y: int = 5,
) -> Cavalry:
    return Cavalry(unit_id=unit_id, name=name, faction=faction, start_pos=_make_coord(x, y))


def _make_artillery(
    unit_id: str = "test_art_01",
    name: str = "测试炮兵",
    faction: Faction = Faction.FRIENDLY,
    x: int = 5,
    y: int = 5,
) -> Artillery:
    return Artillery(unit_id=unit_id, name=name, faction=faction, start_pos=_make_coord(x, y))


def _make_scout(
    unit_id: str = "test_sct_01",
    name: str = "测试侦察兵",
    faction: Faction = Faction.FRIENDLY,
    x: int = 5,
    y: int = 5,
) -> Scout:
    return Scout(unit_id=unit_id, name=name, faction=faction, start_pos=_make_coord(x, y))


def _make_hq(
    unit_id: str = "test_hq_01",
    name: str = "测试指挥所",
    faction: Faction = Faction.FRIENDLY,
    x: int = 5,
    y: int = 5,
) -> HQ:
    return HQ(unit_id=unit_id, name=name, faction=faction, start_pos=_make_coord(x, y))


def _make_enemy_infantry(
    unit_id: str = "test_enemy_01",
    x: int = 6,
    y: int = 5,
) -> Infantry:
    """快捷创建相邻敌军步兵。"""
    return Infantry(
        unit_id=unit_id, name="敌军测试步兵", faction=Faction.ENEMY, start_pos=_make_coord(x, y)
    )


# ============================================================================
# 测试 1: 兵种创建与属性验证
# ============================================================================


class TestUnitCreation:
    """测试 5 种兵种的创建与属性正确性。"""

    def test_create_infantry_has_correct_stats(self) -> None:
        """步兵创建的属性应与 UNIT_STATS[INFANTRY] 一致。"""
        unit = _make_infantry()
        stats = UNIT_STATS[UnitType.INFANTRY]

        assert unit.unit_type == UnitType.INFANTRY
        assert unit.max_hp == stats.max_hp
        assert unit.current_hp == stats.max_hp  # 初始满血
        assert unit.attack == stats.attack
        assert unit.base_defense == stats.defense
        assert unit.speed == stats.speed
        assert unit.attack_range == stats.attack_range
        assert unit.vision_range == stats.vision_range
        assert unit.is_alive is True
        assert unit.is_hq is False

    def test_create_cavalry_has_correct_stats(self) -> None:
        """骑兵属性验证。"""
        unit = _make_cavalry()
        stats = UNIT_STATS[UnitType.CAVALRY]

        assert unit.unit_type == UnitType.CAVALRY
        assert unit.max_hp == stats.max_hp
        assert unit.speed == 6  # 全兵种最快
        assert unit.attack == 4
        assert unit.is_hq is False

    def test_create_artillery_has_correct_stats(self) -> None:
        """炮兵属性验证 — 攻击范围 3，远程单位。"""
        unit = _make_artillery()

        assert unit.unit_type == UnitType.ARTILLERY
        assert unit.attack_range == 3
        assert unit.is_ranged_attack is True
        assert unit.speed == 1  # 全兵种最慢
        assert unit.is_hq is False

    def test_create_scout_has_correct_stats(self) -> None:
        """侦察兵属性验证 — 视野 6。"""
        unit = _make_scout()

        assert unit.unit_type == UnitType.SCOUT
        assert unit.vision_range == 6  # 视野最广
        assert unit.attack == 1  # 攻击最弱
        assert unit.is_hq is False

    def test_create_hq_has_correct_stats(self) -> None:
        """指挥所属性验证 — 不可移动/攻击。"""
        unit = _make_hq()

        assert unit.unit_type == UnitType.HQ
        assert unit.max_hp == 30
        assert unit.attack == 0
        assert unit.attack_range == 0
        assert unit.speed == 0
        assert unit.vision_range == 0
        assert unit.is_hq is True

    def test_create_all_unit_types(self) -> None:
        """验证 5 种兵种均可成功创建且属性有效。"""
        units: list[Unit] = [
            _make_infantry("inf_1"),
            _make_cavalry("cav_1"),
            _make_artillery("art_1"),
            _make_scout("sct_1"),
            _make_hq("hq_1"),
        ]

        for unit in units:
            assert unit.is_alive
            assert unit.current_hp > 0
            assert unit.position.x >= 0
            assert unit.position.y >= 0

    def test_create_unit_with_factory_function(self) -> None:
        """_create_unit_instance 工厂函数可创建所有兵种。"""
        for ut in UnitType:
            unit = _create_unit_instance(
                unit_type=ut,
                unit_id=f"factory_{ut.value}",
                name=f"工厂{UNIT_DISPLAY_NAMES[ut]}",
                faction=Faction.FRIENDLY,
                position=_make_coord(),
            )
            assert unit.unit_type == ut
            assert unit.is_alive


# ============================================================================
# 测试 2: HQ 特殊行为
# ============================================================================


class TestHQSpecialBehavior:
    """指挥所特殊行为：不可攻击、不可移动。"""

    def test_hq_cannot_attack(self) -> None:
        """HQ.attack_target() 应抛出 ValueError。"""
        hq = _make_hq()
        enemy = _make_enemy_infantry()

        with pytest.raises(ValueError, match="不可攻击"):
            hq.attack_target(enemy)

    def test_hq_cannot_move(self) -> None:
        """HQ.move_to() 应返回 False。"""
        hq = _make_hq()
        result = hq.move_to(_make_coord(10, 10))
        assert result is False
        # 坐标不变
        assert hq.position == _make_coord(5, 5)

    def test_hq_can_attack_always_false(self) -> None:
        """HQ.can_attack() 对任何目标返回 False。"""
        hq = _make_hq()
        enemy = _make_enemy_infantry()

        assert hq.can_attack(enemy) is False

    def test_hq_is_hq_true(self) -> None:
        """只有 HQ 的 is_hq 为 True。"""
        assert _make_hq().is_hq is True
        assert _make_infantry().is_hq is False
        assert _make_cavalry().is_hq is False
        assert _make_artillery().is_hq is False
        assert _make_scout().is_hq is False


# ============================================================================
# 测试 3: take_damage 与阵亡逻辑
# ============================================================================


class TestTakeDamage:
    """伤害结算与阵亡判定。"""

    def test_take_damage_reduces_hp(self) -> None:
        """受到伤害应正确扣减 HP。"""
        unit = _make_infantry()
        attacker = _make_enemy_infantry()
        initial_hp = unit.current_hp

        actual = unit.take_damage(5, attacker)

        assert actual == 5
        assert unit.current_hp == initial_hp - 5
        assert unit.is_alive is True

    def test_take_damage_kills_unit(self) -> None:
        """HP 降为 0 时单位阵亡。"""
        unit = _make_infantry()
        attacker = _make_enemy_infantry()

        unit.take_damage(unit.current_hp, attacker)

        assert unit.current_hp == 0
        assert unit.is_alive is False

    def test_take_damage_overkill_clamped(self) -> None:
        """溢出伤害不会让 HP 为负。"""
        unit = _make_infantry()
        attacker = _make_enemy_infantry()

        actual = unit.take_damage(999, attacker)

        assert actual == unit.max_hp  # 最多扣到 0
        assert unit.current_hp == 0
        assert unit.is_alive is False

    def test_take_damage_on_dead_unit_returns_zero(self) -> None:
        """已阵亡单位再次受到伤害返回 0。"""
        unit = _make_infantry()
        attacker = _make_enemy_infantry()
        unit.take_damage(unit.max_hp, attacker)  # 杀死
        assert unit.is_alive is False

        actual = unit.take_damage(10, attacker)
        assert actual == 0

    def test_hp_ratio_calculation(self) -> None:
        """hp_ratio 属性计算正确。"""
        unit = _make_infantry()  # max_hp=10
        attacker = _make_enemy_infantry()

        assert unit.hp_ratio == 1.0
        unit.take_damage(3, attacker)
        assert unit.hp_ratio == 0.7
        unit.take_damage(4, attacker)
        assert unit.hp_ratio == 0.3
        unit.take_damage(3, attacker)
        assert unit.hp_ratio == 0.0


# ============================================================================
# 测试 4: 攻击范围判定
# ============================================================================


class TestCanAttack:
    """can_attack 范围与条件判定。"""

    def test_can_attack_adjacent_enemy(self) -> None:
        """相邻敌人应在攻击范围内。"""
        unit = _make_infantry(x=5, y=5)
        enemy = _make_enemy_infantry(x=6, y=5)  # 距离 1

        assert unit.can_attack(enemy) is True

    def test_can_attack_diagonal_enemy(self) -> None:
        """对角相邻敌人应在攻击范围内（切比雪夫距离=1）。"""
        unit = _make_infantry(x=5, y=5)
        enemy = _make_enemy_infantry(x=6, y=6)  # 对角，切比雪夫距离=1

        assert unit.can_attack(enemy) is True

    def test_can_attack_out_of_range(self) -> None:
        """距离超过攻击范围的敌人不可攻击。"""
        unit = _make_infantry(x=5, y=5)  # range=1
        enemy = _make_enemy_infantry(x=8, y=5)  # 距离 3

        assert unit.can_attack(enemy) is False

    def test_can_attack_same_faction_false(self) -> None:
        """同阵营不可攻击。"""
        unit = _make_infantry(faction=Faction.FRIENDLY)
        friendly = _make_infantry("friend_2", faction=Faction.FRIENDLY, x=6, y=5)

        assert unit.can_attack(friendly) is False

    def test_can_attack_dead_target_false(self) -> None:
        """已阵亡目标不可攻击。"""
        unit = _make_infantry(x=5, y=5)
        enemy = _make_enemy_infantry(x=6, y=5)
        attacker_for_kill = _make_enemy_infantry("killer", x=10, y=10)
        enemy.take_damage(enemy.max_hp, attacker_for_kill)

        assert enemy.is_alive is False
        assert unit.can_attack(enemy) is False

    def test_artillery_can_attack_at_range_3(self) -> None:
        """炮兵可攻击距离 3 的目标。"""
        arty = _make_artillery(x=5, y=5)  # range=3
        enemy = _make_enemy_infantry(x=8, y=5)  # 距离 3

        assert arty.can_attack(enemy) is True

    def test_artillery_cannot_attack_at_range_4(self) -> None:
        """炮兵不可攻击距离 4 的目标。"""
        arty = _make_artillery(x=5, y=5)  # range=3
        enemy = _make_enemy_infantry(x=9, y=5)  # 距离 4

        assert arty.can_attack(enemy) is False


# ============================================================================
# 测试 5: attack_target 攻击流程
# ============================================================================


class TestAttackTarget:
    """attack_target 攻击结算。"""

    def test_attack_target_deals_damage(self) -> None:
        """攻击应对目标造成伤害。"""
        unit = _make_infantry(x=5, y=5)
        enemy = _make_enemy_infantry(x=6, y=5)

        damage = unit.attack_target(enemy)

        # 步兵攻3 vs 步兵防2: raw = max(1, 3-2) = 1
        assert damage >= 1
        assert enemy.current_hp < enemy.max_hp

    def test_attack_target_kills_weak_enemy(self) -> None:
        """伤害足够时应击杀目标。"""
        unit = _make_cavalry(x=5, y=5)  # attack=4
        enemy = _make_enemy_infantry(x=6, y=5)  # defense=2, HP=10

        # 多次攻击直到击杀
        for _ in range(10):
            if not enemy.is_alive:
                break
            unit.attack_target(enemy)

        assert enemy.is_alive is False

    def test_attack_target_minimum_damage(self) -> None:
        """防御力高于攻击力时，伤害仍为 COMBAT_MIN_DAMAGE (1)。"""
        # 侦察兵攻击=1, 步兵防御=2, raw = max(1, 1-2) = 1
        unit = _make_scout(x=5, y=5)
        enemy = _make_enemy_infantry(x=6, y=5)

        damage = unit.attack_target(enemy)
        assert damage == 1

    def test_attack_target_dead_target_returns_zero(self) -> None:
        """攻击已阵亡目标返回 0。"""
        unit = _make_infantry(x=5, y=5)
        enemy = _make_enemy_infantry(x=6, y=5)
        killer = _make_enemy_infantry("killer", x=10, y=10)
        enemy.take_damage(enemy.max_hp, killer)

        damage = unit.attack_target(enemy)
        assert damage == 0


# ============================================================================
# 测试 6: get_state_report 状态报告
# ============================================================================


class TestGetStateReport:
    """get_state_report 文本格式。"""

    def test_get_state_report_contains_name_and_type(self) -> None:
        """报告应包含单位名称和兵种。"""
        unit = _make_infantry(name="第一步兵连")
        report = unit.get_state_report()

        assert "第一步兵连" in report
        type_name = UNIT_DISPLAY_NAMES[UnitType.INFANTRY]
        assert type_name in report

    def test_get_state_report_contains_hp(self) -> None:
        """报告应包含 HP 信息。"""
        unit = _make_infantry()
        report = unit.get_state_report()

        assert f"HP:{unit.current_hp}/{unit.max_hp}" in report

    def test_get_state_report_healthy_status(self) -> None:
        """HP >= 70% 显示'状态良好'。"""
        unit = _make_infantry()
        # 初始满血
        report = unit.get_state_report()
        assert "状态良好" in report

    def test_get_state_report_damaged_status(self) -> None:
        """70% > HP >= 30% 显示'轻微受损'。"""
        unit = _make_infantry()
        attacker = _make_enemy_infantry()
        # HP 10→6 (60%)
        unit.take_damage(4, attacker)
        report = unit.get_state_report()
        assert "轻微受损" in report

    def test_get_state_report_critical_status(self) -> None:
        """HP < 30% 显示'损失惨重'。"""
        unit = _make_infantry()
        attacker = _make_enemy_infantry()
        # HP 10→2 (20%)
        unit.take_damage(8, attacker)
        report = unit.get_state_report()
        assert "损失惨重" in report

    def test_get_state_report_dead(self) -> None:
        """阵亡后显示'已阵亡'。"""
        unit = _make_infantry()
        attacker = _make_enemy_infantry()
        unit.take_damage(unit.max_hp, attacker)

        report = unit.get_state_report()
        assert "已阵亡" in report


# ============================================================================
# 测试 7: Unit 基类通用行为
# ============================================================================


class TestUnitBaseBehavior:
    """Unit 基类的通用行为测试。"""

    def test_unit_repr(self) -> None:
        """__repr__ 应包含关键信息。"""
        unit = _make_infantry(unit_id="inf_01", name="测试")
        r = repr(unit)

        assert "Infantry" in r
        assert "inf_01" in r
        assert "测试" in r

    def test_move_to_updates_position(self) -> None:
        """move_to 应更新坐标。"""
        unit = _make_infantry(x=5, y=5)
        target = _make_coord(10, 12)

        result = unit.move_to(target)

        assert result is True
        assert unit.position == target

    def test_terrain_defense_bonus(self) -> None:
        """地形加成影响 defense 属性。"""
        unit = _make_infantry()
        base_def = unit.base_defense

        assert unit.defense == base_def  # 初始无加成
        assert unit.terrain_defense_bonus == 0

        unit.terrain_defense_bonus = 2
        assert unit.defense == base_def + 2
        assert unit.terrain_defense_bonus == 2

    def test_artillery_is_ranged_attack(self) -> None:
        """炮兵的 is_ranged_attack 应为 True。"""
        arty = _make_artillery()
        assert arty.is_ranged_attack is True

        # Infantry 通过基类 attack_range 判断是否为远程（attack_range=1 → 非远程）
