"""
BlindCommand Unit 基类 — IUnit 接口的具体实现
================================================
本模块提供 `UnitBase` 类，作为所有兵种的父类（#3 的 Infantry / Cavalry / ... 继承它）。

职责：
- 持有单位全部属性（血量、攻防、坐标、阵营、兵种等）
- take_damage（纯扣血原语，完整伤害公式由 #3 计算）
- move_to（全或无移动，委托 Map 寻路）
- attack_target（最小默认实现，克制/反击/先手由 #3 重写）
- can_attack / get_state_report

约束：
- 不直接 emit 事件（阵亡/受伤事件由 #3 battle_system 广播）
- 不依赖 src/battle/ 或 src/ui/

版本：v0.1.0（对齐 CORE_SPEC.md §3）
"""

from __future__ import annotations

import logging

from src.core.constants import (
    COMBAT_MIN_DAMAGE,
    UNIT_DISPLAY_NAMES,
    Faction,
    Coordinate,
    UnitStats,
    UnitType,
)
from src.core.interfaces import IMap, IUnit

logger = logging.getLogger(__name__)


class UnitBase(IUnit):
    """单位基类，实现 IUnit 接口的全部属性与操作方法。

    #3 应继承本类并可能重写 attack_target、get_state_report 等
    以实现兵种特化逻辑。

    Attributes:
        _game_map: 可选 Map 引用，仅 move_to / defense(bonus) 依赖；
                   无 Map 时 move_to 直接更新坐标（测试模式）。
    """

    # ── __init__ ───────────────────────────────────────────────────────

    def __init__(
        self,
        unit_id: str,
        name: str,
        faction: Faction,
        unit_type: UnitType,
        position: Coordinate,
        stats: UnitStats,
        game_map: IMap | None = None,
    ) -> None:
        """初始化单位实例。

        Args:
            unit_id: 全局唯一标识，如 'friendly_infantry_01'
            name: 人类可读名称，如 '第一步兵连'
            faction: 所属阵营
            unit_type: 兵种类型
            position: 初始坐标（若传入 game_map 则校验越界）
            stats: 兵种属性模板（通常从 UNIT_STATS[unit_type] 取）
            game_map: 可选 Map 引用，启用 move_to 路径验证与地形防御加成

        Raises:
            ValueError: 若 game_map 非 None 且 position 越界
        """
        if game_map is not None and not game_map.is_within_bounds(position):
            raise ValueError(
                f"单位 {unit_id} 初始坐标 {position} 越界"
            )

        self._unit_id = unit_id
        self._name = name
        self._faction = faction
        self._unit_type = unit_type
        self._position = position

        self._max_hp = stats.max_hp
        self._current_hp = stats.max_hp
        self._base_attack = stats.attack
        self._base_defense = stats.defense
        self._speed = stats.speed
        self._attack_range = stats.attack_range
        self._vision_range = stats.vision_range
        self._is_hq = stats.is_hq
        self._is_alive = True

        self._game_map = game_map

    # ── 只读属性 ──────────────────────────────────────────────────────

    @property
    def unit_id(self) -> str:
        return self._unit_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def faction(self) -> Faction:
        return self._faction

    @property
    def unit_type(self) -> UnitType:
        return self._unit_type

    @property
    def position(self) -> Coordinate:
        return self._position

    @property
    def max_hp(self) -> int:
        return self._max_hp

    @property
    def current_hp(self) -> int:
        return self._current_hp

    @property
    def attack(self) -> int:
        """基础攻击力（不含克制倍率，克制归 #3）。"""
        return self._base_attack

    @property
    def defense(self) -> int:
        """最终防御力 = 基础防御 + 当前所在地形防御加成。

        地形加成由 #2 计算（本层），#3 读此属性即可获得含地形防御。
        无 Map 引用时（测试模式）返回裸基础防御。
        """
        if self._game_map is None:
            return self._base_defense
        bonus = self._game_map.get_defense_bonus(self._position)
        return self._base_defense + bonus

    @property
    def speed(self) -> int:
        return self._speed

    @property
    def attack_range(self) -> int:
        return self._attack_range

    @property
    def vision_range(self) -> int:
        return self._vision_range

    @property
    def is_alive(self) -> bool:
        return self._is_alive

    @property
    def is_hq(self) -> bool:
        return self._is_hq

    # ── 操作方法 ──────────────────────────────────────────────────────

    def take_damage(self, amount: int, source: IUnit) -> int:
        """受到伤害（纯扣血原语，对齐 CORE_SPEC.md C-1）。

        传入的 amount 应为 #3 battle_system 用完整伤害公式计算后的最终值
        （已扣除防御、已乘克制倍率与地形修正）。本方法仅负责扣减 current_hp、
        阵亡判定，并返回实际扣血量。

        Args:
            amount: 最终伤害值（#3 计算后传入）
            source: 伤害来源单位

        Returns:
            实际扣血量 = min(amount, 扣血前 current_hp)

        Raises:
            ValueError: 若 amount < 0
        """
        if not self._is_alive:
            return 0
        if amount < 0:
            raise ValueError(f"伤害值不能为负，收到 {amount}（来源: {source.unit_id}）")

        applied = min(amount, self._current_hp)
        self._current_hp -= applied

        if self._current_hp == 0:
            self._is_alive = False
            logger.debug("单位 %s (%s) 阵亡", self._name, self._unit_id)

        return applied

    def move_to(self, target: Coordinate) -> bool:
        """移动到 target（全或无语义，对齐 CORE_SPEC.md C-7）。

        仅当目标在 speed 步数内可达时才移动并返回 True；
        若不可达或 max_steps 不足，不移动并返回 False。

        Args:
            target: 目标坐标

        Returns:
            True 当且仅当已真正抵达 target
        """
        if not self._is_alive:
            return False

        # 无 Map 模式（测试/自测）：直接跳跃
        if self._game_map is None:
            self._position = target
            return True

        if not self._game_map.is_within_bounds(target):
            return False
        if self._position == target:
            return True

        path = self._game_map.find_path(self._position, target, self._speed)
        if not path or path[-1] != target:
            # 不可达 或 步数不够（全或无，不部分移动）
            return False

        if self._game_map.move_unit(self, self._position, target):
            self._position = target
            return True
        return False

    def attack_target(self, target: IUnit) -> int:
        """默认近战攻击（最小实现，对齐 CORE_SPEC.md C-2）。

        伤害 = max(COMBAT_MIN_DAMAGE, self.attack - target.defense)。
        不含兵种克制、反击、先手——这些由 #3 的 battle_system /
        兵种子类重写实现。

        Args:
            target: 被攻击的单位

        Returns:
            对目标实际造成的伤害；若无法攻击返回 0
        """
        if not self.can_attack(target):
            return 0

        raw = max(COMBAT_MIN_DAMAGE, self.attack - target.defense)
        return target.take_damage(raw, self)

    def can_attack(self, target: IUnit) -> bool:
        """判断是否可以攻击目标。

        条件：自身存活、目标存活、不同阵营、攻击范围 > 0、
              切比雪夫距离 ≤ attack_range。

        Args:
            target: 潜在目标

        Returns:
            True 如果可以攻击
        """
        if not self._is_alive or not target.is_alive:
            return False
        if self._attack_range == 0:
            return False
        if target.faction == self._faction:
            return False
        dist = self._position.chebyshev_distance(target.position)
        return dist <= self._attack_range

    def get_state_report(self) -> str:
        """生成用于战报的人类可读状态文本。

        Returns:
            格式：'{名称}（{兵种中文}） [{存活/阵亡}] HP {cur}/{max} ({pct}%)'
        """
        status = "存活" if self._is_alive else "阵亡"
        hp_pct = int(self._current_hp / self._max_hp * 100) if self._max_hp else 0
        return (
            f"{self._name}（{UNIT_DISPLAY_NAMES[self._unit_type]}）"
            f" [{status}] HP {self._current_hp}/{self._max_hp} ({hp_pct}%)"
        )
