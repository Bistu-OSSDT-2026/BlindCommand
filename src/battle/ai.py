"""
敌军 AI 决策系统 — 行为树驱动的自动决策
=========================================
本模块提供 `EnemyAI` 类：每回合为所有存活的敌军单位运行行为树，
通过 Commander 下达指令（走相同的 CommandQueue 延迟系统）。

行为树优先级（从高到低）：
    1. 溃逃（HP < 20%）→ RETREAT 向己方 HQ
    2. 战斗（攻击范围内有敌人）→ ATTACK 最近敌人
    3. 保卫（己方 HQ 附近有敌人）→ MOVE 回防 HQ
    4. 默认 → 50% MOVE 向敌方 HQ / 50% PATROL 当前区域

依赖:
    src/core/constants.py   — COMBAT_ROUT_HP_RATIO, Faction, Coordinate, CommandType
    src/core/interfaces.py  — IUnit, IMap, IRangeQuery
    src/battle/commander.py — Commander
    src/battle/unit_manager.py — UnitManager

版本: v0.1.0
"""

from __future__ import annotations

import logging
import random

from src.battle.commander import Commander
from src.battle.unit_manager import UnitManager
from src.core.constants import (
    COMBAT_ROUT_HP_RATIO,
    CommandType,
    Coordinate,
    Faction,
)
from src.core.interfaces import IGameState, IMap, IRangeQuery, IUnit

logger = logging.getLogger(__name__)

# HQ 防御半径：AI 单位在此半径内有敌军时回防 HQ
AI_HQ_DEFENSE_RADIUS = 5


class EnemyAI:
    """敌军 AI 决策系统。

    每回合由 GameLoop 在阶段 2（AI 决策）通过 ai_decider 钩子调用 decide_all()。
    为每个存活敌军运行行为树，通过 Commander.issue_command() 下达指令。
    """

    # ── __init__ ───────────────────────────────────────────────────────

    def __init__(
        self,
        unit_manager: UnitManager,
        range_query: IRangeQuery,
        game_map: IMap,
        commander: Commander,
        seed: int | None = None,
    ) -> None:
        """初始化 AI 决策系统。

        Args:
            unit_manager: 单位管理器（获取存活敌军、HQ 等）
            range_query: 范围检索接口（#2 实现，用于索敌）
            game_map: 地图接口（#2 实现，用于获取 HQ 坐标）
            commander: 指令系统（AI 通过它下达指令）
            seed: 随机种子（测试用，用于 PATROL 方向选择等）
        """
        self._unit_manager = unit_manager
        self._range_query = range_query
        self._map = game_map
        self._commander = commander
        self._rng = random.Random(seed)

        logger.info("EnemyAI 初始化完成")

    # ── 主入口 ──────────────────────────────────────────────────────────

    def decide_all(self, game_state: IGameState) -> None:
        """为所有存活的敌军单位决策并下达指令。

        由 GameLoop 在阶段 2 调用（作为 ai_decider 钩子）。
        GameLoop 将自身作为 IGameState 传入。

        Args:
            game_state: 当前游戏状态（IGameState 查询接口）
        """
        current_turn = game_state.get_current_turn()
        enemies = self._unit_manager.get_units_by_faction(Faction.ENEMY)
        if not enemies:
            return

        for unit in enemies:
            if not unit.is_alive:
                continue

            try:
                cmd_type, params = self.decide_for_unit(unit, current_turn)
                if cmd_type is not None:
                    self._commander.issue_command(
                        unit_id=unit.unit_id,
                        command_type=cmd_type,
                        params=params,
                        current_turn=current_turn,
                    )
                    logger.debug(
                        "AI: %s → %s params=%s",
                        unit.name,
                        cmd_type.value,
                        params,
                    )
            except (ValueError, TypeError, AttributeError) as e:
                logger.exception(
                    "AI 决策异常: %s (type=%s, msg=%s)",
                    unit.name,
                    type(e).__name__,
                    e,
                )

    # ── 单单位决策 ──────────────────────────────────────────────────────

    def decide_for_unit(
        self, unit: IUnit, current_turn: int
    ) -> tuple[CommandType | None, dict]:
        """为单个敌军单位做出决策（行为树）。

        Args:
            unit: 敌军单位
            current_turn: 当前回合数（备用，暂未使用）

        Returns:
            (指令类型, 参数字典)；若无需行动返回 (None, {})
        """
        # ── 优先级 1：溃逃 ────────────────────────────────────────
        if unit.hp_ratio < COMBAT_ROUT_HP_RATIO and not unit.is_hq:
            direction = self._direction_toward_own_hq(unit)
            if direction:
                return (CommandType.RETREAT, {"direction": direction})

        # ── 优先级 2：战斗 ────────────────────────────────────────
        if self._range_query.has_enemy_in_range(unit, unit.attack_range):
            enemy = self._range_query.find_nearest_enemy(unit)
            if enemy is not None:
                # 检查 Commander 是否支持战斗结算
                if not self._commander.has_combat_resolver:
                    logger.warning(
                        "AI: %s 攻击范围内有敌人但 Commander 无 combat_resolver，"
                        "回退为向敌人移动",
                        unit.name,
                    )
                    return (
                        CommandType.MOVE,
                        {"x": enemy.position.x, "y": enemy.position.y},
                    )
                return (
                    CommandType.ATTACK,
                    {"x": enemy.position.x, "y": enemy.position.y},
                )

        # ── 优先级 3：保卫 HQ ─────────────────────────────────────
        own_hq = self._unit_manager.get_hq(Faction.ENEMY)
        if own_hq is not None and own_hq.is_alive:
            if self._range_query.has_enemy_in_range(own_hq, radius=AI_HQ_DEFENSE_RADIUS):
                # 回防 HQ
                return (
                    CommandType.MOVE,
                    {"x": own_hq.position.x, "y": own_hq.position.y},
                )

        # ── 优先级 4：默认行动 ────────────────────────────────────
        if self._rng.random() < 0.5:
            # 向敌方 HQ 推进
            enemy_hq_coord = self._map.get_faction_hq_location(Faction.FRIENDLY)
            if enemy_hq_coord is not None:
                return (
                    CommandType.MOVE,
                    {"x": enemy_hq_coord.x, "y": enemy_hq_coord.y},
                )

        # 巡逻当前区域
        patrol_path = self._generate_patrol_path(unit)
        return (CommandType.PATROL, {"path": patrol_path})

    # ── 内部：方向计算 ──────────────────────────────────────────────────

    def _direction_toward_own_hq(self, unit: IUnit) -> str | None:
        """计算单位朝向己方 HQ 的撤退方向。

        坐标系统约定：y=0 为顶部，y 增大方向为向下（屏幕坐标系）。
        dy > 0 表示 HQ 在下方 → 方向 "S"（南）。
        dy < 0 表示 HQ 在上方 → 方向 "N"（北）。

        Args:
            unit: 当前单位

        Returns:
            方向字符串（"N"/"S"/"E"/"W"/...），若无法确定返回 None
        """
        hq_coord = self._map.get_faction_hq_location(unit.faction)
        if hq_coord is None:
            return None

        dx = hq_coord.x - unit.position.x
        dy = hq_coord.y - unit.position.y

        # 转换为八方向中最接近的
        dir_x = ""
        dir_y = ""

        if dx > 0:
            dir_x = "E"
        elif dx < 0:
            dir_x = "W"

        if dy > 0:
            dir_y = "S"
        elif dy < 0:
            dir_y = "N"

        if dir_x and dir_y:
            return dir_y + dir_x  # "NE", "NW", "SE", "SW"
        if dir_x:
            return dir_x
        if dir_y:
            return dir_y
        return "N"  # 默认向北

    def _generate_patrol_path(self, unit: IUnit) -> list[list[int]]:
        """为巡逻指令生成随机路径（2~4 个点）。

        Args:
            unit: 当前单位

        Returns:
            路径坐标列表 [[x1, y1], [x2, y2], ...]
        """
        path: list[list[int]] = [[unit.position.x, unit.position.y]]

        num_extra = self._rng.randint(1, 3)
        cx, cy = unit.position.x, unit.position.y

        for _ in range(num_extra):
            dx = self._rng.randint(-3, 3)
            dy = self._rng.randint(-3, 3)
            nx = max(0, min(self._map.width - 1, cx + dx))
            ny = max(0, min(self._map.height - 1, cy + dy))
            # 确保是可通行格
            coord = Coordinate(nx, ny)
            if self._map.is_passable(coord):
                path.append([nx, ny])
                cx, cy = nx, ny

        # 确保至少 2 个巡逻点（不足时添加一个随机相邻可通行格）
        if len(path) < 2:
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                nx = max(0, min(self._map.width - 1, cx + dx))
                ny = max(0, min(self._map.height - 1, cy + dy))
                coord = Coordinate(nx, ny)
                if self._map.is_passable(coord) and [nx, ny] not in path:
                    path.append([nx, ny])
                    break

        return path
