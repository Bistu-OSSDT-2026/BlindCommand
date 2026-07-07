"""
兵种子类 — 基于 IUnit 接口的五个兵种实现。

本模块在 #2 交付 UnitBase 之前，直接实现 IUnit 接口作为 Unit 基类。
待 src/core/unit_base.py 就绪后，将 Unit 改为继承 UnitBase 即可。

兵种列表:
    - Infantry  (步兵): 均衡型，克骑兵 (×1.5)
    - Cavalry   (骑兵): 高速型，克炮兵 (×1.5)
    - Artillery (炮兵): 远程型，克步兵 (×1.5)，攻击范围 3
    - Scout     (侦察兵): 视野型，视野 6，无克制
    - HQ        (指挥所): 固定型，不可移动/攻击，可被占领

依赖:
    src/core/interfaces.py — IUnit 接口
    src/core/constants.py  — UNIT_STATS, 游戏规则常量

版本: v0.1.0
"""

from __future__ import annotations

from src.core.constants import (
    COMBAT_CRITICAL_HP_RATIO,
    COMBAT_HEALTHY_HP_RATIO,
    COMBAT_MIN_DAMAGE,
    UNIT_DISPLAY_NAMES,
    UNIT_STATS,
    Coordinate,
    Faction,
    UnitType,
)
from src.core.interfaces import IUnit

# ============================================================================
# Unit 基类 — 直接实现 IUnit 接口
# ============================================================================


class Unit(IUnit):
    """单位基类，实现 IUnit 接口。

    注意: 此基类在 #2 交付 UnitBase 后将改为继承 UnitBase。
    当前直接实现 IUnit 以保证并行开发可行性。
    """

    def __init__(
        self,
        unit_id: str,
        name: str,
        faction: Faction,
        unit_type: UnitType,
        position: Coordinate,
        max_hp: int,
        attack: int,
        defense: int,
        speed: int,
        attack_range: int,
        vision_range: int,
    ) -> None:
        """初始化单位。

        Args:
            unit_id: 全局唯一标识
            name: 人类可读名称
            faction: 所属阵营
            unit_type: 兵种类型
            position: 初始坐标
            max_hp: 最大血量
            attack: 攻击力
            defense: 基础防御力
            speed: 每回合可移动格数
            attack_range: 攻击范围（0=不可攻击）
            vision_range: 视野范围（0=无视野）
        """
        self._unit_id = unit_id
        self._name = name
        self._faction = faction
        self._unit_type = unit_type
        self._position = position
        self._max_hp = max_hp
        self._current_hp = max_hp
        self._attack = attack
        self._defense = defense
        self._speed = speed
        self._attack_range = attack_range
        self._vision_range = vision_range
        self._is_alive = True
        self._terrain_defense_bonus: int = 0  # 地形加成，由 battle_system 更新

    # ── 只读属性 ──────────────────────────────────────────────────────────

    @property
    def unit_id(self) -> str:
        """全局唯一标识。"""
        return self._unit_id

    @property
    def name(self) -> str:
        """人类可读名称。"""
        return self._name

    @property
    def faction(self) -> Faction:
        """所属阵营。"""
        return self._faction

    @property
    def unit_type(self) -> UnitType:
        """兵种类型。"""
        return self._unit_type

    @property
    def position(self) -> Coordinate:
        """当前坐标。"""
        return self._position

    @property
    def max_hp(self) -> int:
        """最大血量。"""
        return self._max_hp

    @property
    def current_hp(self) -> int:
        """当前血量。"""
        return self._current_hp

    @property
    def attack(self) -> int:
        """攻击力。"""
        return self._attack

    @property
    def defense(self) -> int:
        """防御力（含地形加成后的最终值）。"""
        return self._defense + self._terrain_defense_bonus

    @property
    def base_defense(self) -> int:
        """基础防御力（不含地形加成）。"""
        return self._defense

    @property
    def terrain_defense_bonus(self) -> int:
        """当前地形防御加成。"""
        return self._terrain_defense_bonus

    @terrain_defense_bonus.setter
    def terrain_defense_bonus(self, value: int) -> None:
        """设置地形防御加成（由 battle_system 在结算前设置）。"""
        self._terrain_defense_bonus = value

    @property
    def speed(self) -> int:
        """每回合可移动格数。"""
        return self._speed

    @property
    def attack_range(self) -> int:
        """攻击范围（格数），0 表示不可攻击。"""
        return self._attack_range

    @property
    def vision_range(self) -> int:
        """视野范围（格数），0 表示无视野。"""
        return self._vision_range

    @property
    def is_alive(self) -> bool:
        """是否存活。"""
        return self._is_alive

    @property
    def is_hq(self) -> bool:
        """是否为指挥所单位。"""
        return self._unit_type == UnitType.HQ

    @property
    def hp_ratio(self) -> float:
        """当前血量比例 (0.0 ~ 1.0)。"""
        return self._current_hp / self._max_hp if self._max_hp > 0 else 0.0

    # ── 操作方法 ──────────────────────────────────────────────────────────

    def take_damage(self, amount: int, source: IUnit) -> int:
        """受到伤害。

        Args:
            amount: 原始伤害值
            source: 伤害来源单位

        Returns:
            实际造成的伤害值（受限于当前 HP）
        """
        if not self._is_alive:
            return 0

        actual = min(amount, self._current_hp)
        self._current_hp -= actual

        if self._current_hp <= 0:
            self._current_hp = 0
            self._is_alive = False

        return actual

    def move_to(self, target: Coordinate) -> bool:
        """移动到目标坐标。

        Args:
            target: 目标坐标

        Returns:
            True 如果移动成功
        """
        if self._speed == 0:
            return False
        self._position = target
        return True

    def attack_target(self, target: IUnit) -> int:
        """攻击目标单位。

        基础实现：计算伤害 → 施加伤害 → 返回伤害值。
        子类可重写以实现特殊攻击逻辑。

        Args:
            target: 被攻击的单位

        Returns:
            实际造成的伤害值

        Raises:
            ValueError: 若攻击范围为 0（不可攻击）
        """
        if self._attack_range == 0:
            raise ValueError(f"{self._name} 不可攻击（attack_range=0）")
        if not target.is_alive:
            return 0

        raw_damage = max(COMBAT_MIN_DAMAGE, self._attack - target.defense)
        return target.take_damage(raw_damage, self)

    def can_attack(self, target: IUnit) -> bool:
        """判断是否可以攻击目标。

        条件：自身可攻击 + 目标存活 + 阵营敌对 + 距离在攻击范围内。

        Args:
            target: 目标单位

        Returns:
            True 如果可以攻击
        """
        if self._attack_range == 0:
            return False
        if not target.is_alive:
            return False
        if self._faction == target.faction:
            return False
        dist = self._position.chebyshev_distance(target.position)
        return dist <= self._attack_range

    def get_state_report(self) -> str:
        """生成单位状态报告（用于战报）。

        Returns:
            格式化的状态文本
        """
        if not self._is_alive:
            return f"{self._name} 已阵亡"

        hp_ratio = self.hp_ratio
        if hp_ratio >= COMBAT_HEALTHY_HP_RATIO:
            status = "状态良好"
        elif hp_ratio >= COMBAT_CRITICAL_HP_RATIO:
            status = "轻微受损"
        else:
            status = "损失惨重"

        type_name = UNIT_DISPLAY_NAMES.get(self._unit_type, str(self._unit_type))
        return (
            f"{self._name}({type_name}) "
            f"HP:{self._current_hp}/{self._max_hp} "
            f"[{status}]"
            f" @({self._position.x},{self._position.y})"
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"id={self._unit_id!r}, name={self._name!r}, "
            f"hp={self._current_hp}/{self._max_hp}, "
            f"pos=({self._position.x},{self._position.y}), "
            f"alive={self._is_alive})"
        )


# ============================================================================
# 兵种子类 — 继承 Unit，只重写 attack_target 和构造逻辑
# ============================================================================


class Infantry(Unit):
    """步兵 — 均衡型近战单位，克制骑兵 (×1.5)。"""

    def __init__(
        self, unit_id: str, name: str, faction: Faction, start_pos: Coordinate
    ) -> None:
        stats = UNIT_STATS[UnitType.INFANTRY]
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.INFANTRY,
            position=start_pos,
            max_hp=stats.max_hp,
            attack=stats.attack,
            defense=stats.defense,
            speed=stats.speed,
            attack_range=stats.attack_range,
            vision_range=stats.vision_range,
        )

    def attack_target(self, target: IUnit) -> int:
        """步兵标准近战攻击。"""
        return super().attack_target(target)


class Cavalry(Unit):
    """骑兵 — 高速近战单位，克制炮兵 (×1.5)。速度全兵种最快 (6)。"""

    def __init__(
        self, unit_id: str, name: str, faction: Faction, start_pos: Coordinate
    ) -> None:
        stats = UNIT_STATS[UnitType.CAVALRY]
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.CAVALRY,
            position=start_pos,
            max_hp=stats.max_hp,
            attack=stats.attack,
            defense=stats.defense,
            speed=stats.speed,
            attack_range=stats.attack_range,
            vision_range=stats.vision_range,
        )

    def attack_target(self, target: IUnit) -> int:
        """骑兵标准近战攻击。"""
        return super().attack_target(target)


class Artillery(Unit):
    """炮兵 — 远程攻击单位（范围 3），克制步兵 (×1.5)。

    特性：远程先手。当攻击距离 > 1 时，先手攻击且防御方不反击。
    """

    def __init__(
        self, unit_id: str, name: str, faction: Faction, start_pos: Coordinate
    ) -> None:
        stats = UNIT_STATS[UnitType.ARTILLERY]
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.ARTILLERY,
            position=start_pos,
            max_hp=stats.max_hp,
            attack=stats.attack,
            defense=stats.defense,
            speed=stats.speed,
            attack_range=stats.attack_range,
            vision_range=stats.vision_range,
        )

    @property
    def is_ranged_attack(self) -> bool:
        """是否可发起远程先手攻击。"""
        return self._attack_range > 1

    def attack_target(self, target: IUnit) -> int:
        """炮兵远程攻击。

        攻击距离 > 1 时为先手远程攻击（不触发反击的逻辑由 battle_system 处理）。
        """
        return super().attack_target(target)


class Scout(Unit):
    """侦察兵 — 视野型轻装单位，视野最广 (6)，无兵种克制。

    战斗力弱（攻击 1），主要用于侦察和扩大视野。
    """

    def __init__(
        self, unit_id: str, name: str, faction: Faction, start_pos: Coordinate
    ) -> None:
        stats = UNIT_STATS[UnitType.SCOUT]
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.SCOUT,
            position=start_pos,
            max_hp=stats.max_hp,
            attack=stats.attack,
            defense=stats.defense,
            speed=stats.speed,
            attack_range=stats.attack_range,
            vision_range=stats.vision_range,
        )

    def attack_target(self, target: IUnit) -> int:
        """侦察兵近战攻击（战斗力弱）。"""
        return super().attack_target(target)


class HQ(Unit):
    """指挥所 — 固定型单位，不可移动/攻击，可被占领。

    血量最高 (30)，防御最高 (3)，是胜利条件的关键目标。
    被敌军步兵连续占领 2 回合即导致失败。
    """

    def __init__(
        self, unit_id: str, name: str, faction: Faction, start_pos: Coordinate
    ) -> None:
        stats = UNIT_STATS[UnitType.HQ]
        super().__init__(
            unit_id=unit_id,
            name=name,
            faction=faction,
            unit_type=UnitType.HQ,
            position=start_pos,
            max_hp=stats.max_hp,
            attack=stats.attack,
            defense=stats.defense,
            speed=stats.speed,
            attack_range=stats.attack_range,
            vision_range=stats.vision_range,
        )

    def move_to(self, target: Coordinate) -> bool:
        """指挥所不可移动。"""
        return False

    def attack_target(self, target: IUnit) -> int:
        """指挥所不可攻击。

        Raises:
            ValueError: 始终抛出
        """
        raise ValueError(f"{self._name} 是指挥所，不可攻击")

    def can_attack(self, target: IUnit) -> bool:
        """指挥所不可攻击。"""
        return False
