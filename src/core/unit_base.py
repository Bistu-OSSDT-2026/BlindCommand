"""
BlindCommand Unit 基类 — IUnit 接口的具体实现 (RTT)
=====================================================
本模块提供 `UnitBase` 类，支持连续移动（float 坐标 + dt 推进）。

职责：
- 持有单位全部属性
- take_damage（纯扣血原语）
- RTT 连续移动：set_destination + update_movement(dt)
- attack_target / can_attack / get_state_report

版本：v0.2.0 — RTT
"""

from __future__ import annotations

import logging
import math

from src.core.constants import (
    COMBAT_MIN_DAMAGE,
    SECONDS_PER_TILE_BASE,
    UNIT_DISPLAY_NAMES,
    Coordinate,
    Faction,
    UnitStats,
    UnitType,
)
from src.core.interfaces import IMap, IUnit

logger = logging.getLogger(__name__)


class UnitBase(IUnit):
    """单位基类（RTT）。"""

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
        if game_map is not None and not game_map.is_within_bounds(position):
            raise ValueError(f"单位 {unit_id} 初始坐标 {position} 越界")

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
        self._terrain_defense_bonus: int = 0

        # ── RTT 连续移动 ──────────────────────────────────────────
        self._float_x: float = float(position.x)
        self._float_y: float = float(position.y)
        self._path: list[Coordinate] = []
        self._path_index: int = 0
        self._tile_progress: float = 0.0  # 当前格内进度 [0,1)
        self._destination: Coordinate | None = None
        self._moving: bool = False

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
    def float_position(self) -> tuple[float, float]:
        """浮点坐标（RTT 连续移动用）。"""
        return (self._float_x, self._float_y)

    @property
    def max_hp(self) -> int:
        return self._max_hp

    @property
    def current_hp(self) -> int:
        return self._current_hp

    @property
    def attack(self) -> int:
        return self._base_attack

    @property
    def defense(self) -> int:
        if self._terrain_defense_bonus != 0 or self._game_map is None:
            return self._base_defense + self._terrain_defense_bonus
        bonus = self._game_map.get_defense_bonus(self._position)
        return self._base_defense + bonus

    @property
    def speed(self) -> int:
        return self._speed

    @property
    def seconds_per_tile(self) -> float:
        """每格移动耗时（秒）。公式: 6 / speed。"""
        if self._speed == 0:
            return float('inf')
        return SECONDS_PER_TILE_BASE / self._speed

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

    @property
    def is_moving(self) -> bool:
        return self._moving

    @property
    def hp_ratio(self) -> float:
        return self._current_hp / self._max_hp if self._max_hp > 0 else 0.0

    @property
    def terrain_defense_bonus(self) -> int:
        return self._terrain_defense_bonus

    @terrain_defense_bonus.setter
    def terrain_defense_bonus(self, value: int) -> None:
        self._terrain_defense_bonus = value

    # ── RTT 移动 ──────────────────────────────────────────────────────

    def set_destination(self, target: Coordinate) -> bool:
        """设置移动目标。计算路径，开始连续移动。

        Returns:
            True 如果目标可达
        """
        if not self._is_alive or self._is_hq:
            return False
        if self._game_map is None:
            return False
        if not self._game_map.is_within_bounds(target):
            return False
        if target == self._position:
            self._moving = False
            self._path = []
            return True

        path = self._game_map.find_path(self._position, target, 999)
        if not path:
            return False

        self._path = path
        self._path_index = 1  # 跳过起点
        self._tile_progress = 0.0
        self._destination = target
        self._moving = True
        return True

    def update_movement(self, dt: float) -> None:
        """每帧推进连续移动。

        Args:
            dt: 本帧时间（秒）
        """
        if not self._moving or not self._path or self._path_index >= len(self._path):
            self._moving = False
            return

        advance = dt / self.seconds_per_tile
        self._tile_progress += advance

        while self._tile_progress >= 1.0 and self._path_index < len(self._path):
            self._tile_progress -= 1.0
            next_coord = self._path[self._path_index]
            if self._game_map is not None:
                if not self._game_map.move_unit(self, self._position, next_coord):
                    # 被阻塞，停止
                    self._moving = False
                    self._path = []
                    return
            self._position = next_coord
            self._float_x = float(next_coord.x)
            self._float_y = float(next_coord.y)
            self._path_index += 1

        if self._path_index >= len(self._path):
            self._moving = False
            self._path = []
            self._tile_progress = 0.0
            return

        # 更新浮点坐标
        if self._path_index < len(self._path):
            target_coord = self._path[self._path_index]
            frac = self._tile_progress
            self._float_x = self._position.x + (target_coord.x - self._position.x) * frac
            self._float_y = self._position.y + (target_coord.y - self._position.y) * frac

    # ── 操作方法 ──────────────────────────────────────────────────────

    def take_damage(self, amount: int, source: IUnit) -> int:
        if not self._is_alive:
            return 0
        if amount < 0:
            raise ValueError(f"伤害值不能为负，收到 {amount}")
        applied = min(amount, self._current_hp)
        self._current_hp -= applied
        if self._current_hp == 0:
            self._is_alive = False
            self._moving = False
            self._path = []
        return applied

    def move_to(self, target: Coordinate) -> bool:
        """teleport 移动（兼容旧代码，测试用）。"""
        if not self._is_alive:
            return False
        if self._game_map is None:
            self._position = target
            self._float_x = float(target.x)
            self._float_y = float(target.y)
            return True
        if not self._game_map.is_within_bounds(target):
            return False
        if self._position == target:
            return True
        path = self._game_map.find_path(self._position, target, self._speed)
        if not path or path[-1] != target:
            return False
        if self._game_map.move_unit(self, self._position, target):
            self._position = target
            self._float_x = float(target.x)
            self._float_y = float(target.y)
            return True
        return False

    def attack_target(self, target: IUnit) -> int:
        if not self.can_attack(target):
            return 0
        raw = max(COMBAT_MIN_DAMAGE, self.attack - target.defense)
        return target.take_damage(raw, self)

    def can_attack(self, target: IUnit) -> bool:
        if not self._is_alive or not target.is_alive:
            return False
        if self._attack_range == 0:
            return False
        if target.faction == self._faction:
            return False
        dist = self._position.chebyshev_distance(target.position)
        return dist <= self._attack_range

    def get_state_report(self) -> str:
        status = "存活" if self._is_alive else "阵亡"
        hp_pct = int(self._current_hp / self._max_hp * 100) if self._max_hp else 0
        return (
            f"{self._name}（{UNIT_DISPLAY_NAMES[self._unit_type]}）"
            f" [{status}] HP {self._current_hp}/{self._max_hp} ({hp_pct}%)"
        )
