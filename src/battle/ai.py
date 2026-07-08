"""
敌军 AI 决策系统 — 行为树驱动的自动决策（Sprint 3 增强版）
===========================================================
本模块提供 `EnemyAI` 类：每回合为所有存活的敌军单位运行行为树，
通过 Commander 下达指令（走相同的 CommandQueue 延迟系统）。

Sprint 3 增强：
    - AI1 炮兵保持距离 (Kiting)：炮兵检测到近身敌人时先撤退再远程攻击
    - AI2 协同围攻：多个敌军优先集火同一目标
    - AI3 地形利用：默认移动/巡逻时优先选择高防御地形

行为树优先级（从高到低）：
    1. 溃逃（HP < 20%）→ RETREAT 向己方 HQ
    2. 炮兵保持距离（近身有敌 + 可后退）→ RETREAT 拉开
    3. 战斗（攻击范围内有敌人）→ ATTACK 最近敌人
    4. 保卫（己方 HQ 附近有敌人）→ MOVE 回防 HQ
    5. 默认 → 50% MOVE 向敌方 HQ（优选地形）/ 50% PATROL 当前区域

依赖:
    src/core/constants.py   — COMBAT_ROUT_HP_RATIO, Faction, Coordinate, CommandType
    src/core/interfaces.py  — IUnit, IMap, IRangeQuery, IGameState
    src/battle/commander.py — Commander
    src/battle/unit_manager.py — UnitManager

版本: v0.2.0 — Sprint 3
"""

from __future__ import annotations

import logging
import random
from typing import Optional

from src.battle.commander import Commander
from src.battle.unit_manager import UnitManager
from src.core.constants import (
    COMBAT_ROUT_HP_RATIO,
    CommandType,
    Coordinate,
    Faction,
    get_terrain_props,
)
from src.core.interfaces import IGameState, IMap, IRangeQuery, IUnit

logger = logging.getLogger(__name__)

# ── AI 内部常量 ─────────────────────────────────────────────────────────

_KITE_SAFE_DISTANCE: int = 2        # 炮兵保持的最小安全距离
_COORDINATED_ATTACK_RADIUS: int = 5 # 协同围攻的协调范围
_HQ_DEFEND_RADIUS: int = 5          # 保卫 HQ 的检测半径


class EnemyAI:
    """敌军 AI 决策系统。

    每回合由 GameLoop 在阶段 2（AI 决策）通过 ai_decider 钩子调用 decide_all()。
    为每个存活敌军运行行为树，通过 Commander.issue_command() 下达指令。

    Sprint 3 增强：
        - 炮兵自动保持距离（避免近战劣势）
        - 多单位协同集火同一目标
        - 移动/巡逻时优先选择有利地形
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
            game_map: 地图接口（#2 实现，用于获取 HQ 坐标、地形查询）
            commander: 指令系统（AI 通过它下达指令）
            seed: 随机种子（测试用）
        """
        self._unit_manager = unit_manager
        self._range_query = range_query
        self._map = game_map
        self._commander = commander
        self._rng = random.Random(seed)

        logger.info("EnemyAI 初始化完成 (Sprint 3 增强版)")

    # ── 主入口 ──────────────────────────────────────────────────────────

    def decide_all(self, game_state: IGameState) -> None:
        """为所有存活的敌军单位决策并下达指令。

        由 GameLoop 在阶段 2 调用（作为 ai_decider 钩子）。

        Sprint 3 增强（AI2 协同围攻）：
            先收集所有友军可见的敌人，统计每个敌人的被关注度，
            供后续决策时优先集火防御力最低的敌人。

        Args:
            game_state: 当前游戏状态（IGameState 查询接口）
        """
        current_turn = game_state.get_current_turn()
        enemies = self._unit_manager.get_units_by_faction(Faction.ENEMY)
        if not enemies:
            return

        # ── AI2：收集可见敌人并统计被关注度，用于协同围攻 ──────
        threat_map: dict[str, int] = {}          # enemy_id → 关注此敌的友军数
        visible_enemies: dict[str, IUnit] = {}    # enemy_id → IUnit

        for unit in enemies:
            if not unit.is_alive:
                continue
            # 统计每个敌军单位视野内的友军
            friends_in_sight = self._range_query.get_units_in_range(
                center=unit.position,
                radius=unit.vision_range,
                faction=Faction.FRIENDLY,
            )
            for friend in friends_in_sight:
                threat_map[friend.unit_id] = threat_map.get(friend.unit_id, 0) + 1
                visible_enemies[friend.unit_id] = friend

        # 找出最有价值的目标（被关注最多 = 最孤立/最弱）
        primary_target: Optional[IUnit] = None
        if threat_map:
            # 优先选择被关注最多的友军（协同集火）
            max_threat = max(threat_map.values())
            candidates = [uid for uid, count in threat_map.items() if count == max_threat]
            # 若有多个，选防御力最低的
            best_id = min(
                candidates,
                key=lambda uid: visible_enemies[uid].defense,
            )
            primary_target = visible_enemies[best_id]
            logger.debug(
                "AI2 协同围攻: 主目标=%s (被%d单位关注, 防御=%d)",
                primary_target.name,
                max_threat,
                primary_target.defense,
            )

        # ── 为每个敌军单位决策 ──────────────────────────────────
        for unit in enemies:
            if not unit.is_alive:
                continue

            try:
                cmd_type, params = self.decide_for_unit(
                    unit, current_turn, primary_target
                )
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
            except Exception:
                logger.exception("AI 决策异常: %s", unit.name)

    # ── 单单位决策 ──────────────────────────────────────────────────────

    def decide_for_unit(
        self,
        unit: IUnit,
        current_turn: int,
        primary_target: Optional[IUnit] = None,
    ) -> tuple[CommandType | None, dict]:
        """为单个敌军单位做出决策（行为树）。

        Sprint 3 增强（AI1 炮兵保持距离）：
            若单位是炮兵(attack_range>1)，且近身有敌人，优先后撤拉开距离。

        Args:
            unit: 敌军单位
            current_turn: 当前回合数
            primary_target: AI2 协同围攻的主目标（可为 None）

        Returns:
            (指令类型, 参数字典)；若无需行动返回 (None, {})
        """
        # ── 优先级 1：溃逃 ────────────────────────────────────────
        if unit.hp_ratio < COMBAT_ROUT_HP_RATIO and not unit.is_hq:
            direction = self._direction_toward_own_hq(unit)
            if direction:
                return (CommandType.RETREAT, {"direction": direction})

        # ── 优先级 1.5（AI1）：炮兵保持距离 ──────────────────────
        if self._is_ranged_unit(unit):
            kite_result = self._try_kite(unit)
            if kite_result is not None:
                return kite_result

        # ── 优先级 2：战斗 ────────────────────────────────────────
        if self._range_query.has_enemy_in_range(unit, unit.attack_range):
            target = self._pick_attack_target(unit, primary_target)
            if target is not None:
                return (
                    CommandType.ATTACK,
                    {"x": target.position.x, "y": target.position.y},
                )

        # ── 优先级 3：保卫 HQ ─────────────────────────────────────
        own_hq = self._unit_manager.get_hq(Faction.ENEMY)
        if own_hq is not None and own_hq.is_alive:
            if self._range_query.has_enemy_in_range(own_hq, radius=_HQ_DEFEND_RADIUS):
                return (
                    CommandType.MOVE,
                    {"x": own_hq.position.x, "y": own_hq.position.y},
                )

        # ── 优先级 4：默认行动 ────────────────────────────────────
        if self._rng.random() < 0.5:
            # 向敌方 HQ 推进（AI3：优先选择有利地形）
            enemy_hq_coord = self._map.get_faction_hq_location(Faction.FRIENDLY)
            if enemy_hq_coord is not None:
                # 尝试选择一个高防御中间目标
                preferred = self._pick_terrain_preferred_target(unit, enemy_hq_coord)
                return (CommandType.MOVE, {"x": preferred.x, "y": preferred.y})

        # 巡逻当前区域（AI3：路径偏向有利地形）
        patrol_path = self._generate_patrol_path(unit)
        return (CommandType.PATROL, {"path": patrol_path})

    # ── AI1：炮兵保持距离 ──────────────────────────────────────────────

    @staticmethod
    def _is_ranged_unit(unit: IUnit) -> bool:
        """判断是否远程单位（攻击范围 > 1）。"""
        return unit.attack_range > 1

    def _try_kite(self, unit: IUnit) -> tuple[CommandType, dict] | None:
        """若近身有敌人且可后退，返回 RETREAT 指令以拉开距离。

        Args:
            unit: 远程单位（炮兵）

        Returns:
            RETREAT 指令元组，无需风筝时返回 None
        """
        # 查找攻击范围内的所有敌人
        enemies = self._range_query.get_units_in_range(
            center=unit.position,
            radius=unit.attack_range,
            faction=Faction.FRIENDLY,
            exclude_ids={unit.unit_id},
        )
        if not enemies:
            return None

        # 检查是否有近身敌人（距离 < KITE_SAFE_DISTANCE）
        close_enemies = [
            e for e in enemies
            if unit.position.chebyshev_distance(e.position) < _KITE_SAFE_DISTANCE
        ]
        if not close_enemies:
            return None  # 所有敌人在安全距离外，可以直接攻击

        # 计算远离最近敌人的方向
        nearest = min(
            close_enemies,
            key=lambda e: unit.position.chebyshev_distance(e.position),
        )
        direction = self._direction_away_from(unit, nearest)
        if direction is None:
            return None  # 无处可退

        logger.debug(
            "AI1 炮兵风筝: %s 检测到近身敌人 %s (距离=%d)，向 %s 撤退",
            unit.name,
            nearest.name,
            unit.position.chebyshev_distance(nearest.position),
            direction,
        )
        return (CommandType.RETREAT, {"direction": direction})

    def _direction_away_from(self, unit: IUnit, enemy: IUnit) -> str | None:
        """计算从敌人远离的方向，优先可通行格。

        Args:
            unit: 当前单位
            enemy: 要远离的敌人

        Returns:
            方向字符串，无有效方向返回 None
        """
        dx = unit.position.x - enemy.position.x
        dy = unit.position.y - enemy.position.y

        # 将差值转换为八方向
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

        # 组合方向
        candidates: list[str] = []
        if dir_y and dir_x:
            candidates = [dir_y + dir_x, dir_y, dir_x]  # 对角线优先
        elif dir_y:
            candidates = [dir_y]
        elif dir_x:
            candidates = [dir_x]
        else:
            candidates = ["N"]  # 同格，默认向北

        # 选择可通行的第一个方向
        for d_str in candidates:
            direction = self._parse_direction(d_str)
            if direction is None:
                continue
            next_coord = Coordinate(
                unit.position.x + direction.value[0],
                unit.position.y + direction.value[1],
            )
            if self._map.is_passable(next_coord):
                return d_str

        return None

    # ── AI2：协同围攻辅助 ──────────────────────────────────────────────

    def _pick_attack_target(
        self,
        unit: IUnit,
        primary_target: Optional[IUnit] = None,
    ) -> Optional[IUnit]:
        """选择攻击目标（AI2 协同围攻：优先集火主目标）。

        Args:
            unit: 攻击方
            primary_target: AI2 指定的协同围攻主目标

        Returns:
            攻击目标，无目标返回 None
        """
        # 若指定了主目标且在自己的攻击范围内，优先攻击
        if primary_target is not None and primary_target.is_alive:
            if unit.can_attack(primary_target):
                return primary_target

        # 否则攻击最近敌人
        return self._range_query.find_nearest_enemy(unit)

    # ── AI3：地形利用 ─────────────────────────────────────────────────

    def _pick_terrain_preferred_target(
        self, unit: IUnit, ultimate_goal: Coordinate
    ) -> Coordinate:
        """在向目标推进时，选择一个中间目标以利用有利地形。

        在 unit.speed 步内搜索防御加成最高的可通行格，
        同时靠近 ultimate_goal。

        Args:
            unit: 当前单位
            ultimate_goal: 最终目的地（如敌方 HQ）

        Returns:
            建议的中间目标坐标
        """
        best_coord = ultimate_goal
        best_score = -1

        for dx in range(-unit.speed, unit.speed + 1):
            for dy in range(-unit.speed, unit.speed + 1):
                nx = unit.position.x + dx
                ny = unit.position.y + dy
                if not (0 <= nx < self._map.width and 0 <= ny < self._map.height):
                    continue

                coord = Coordinate(nx, ny)
                if not self._map.is_passable(coord):
                    continue
                if coord == unit.position:
                    continue

                # 评分：防御加成 + 向目标靠近的奖励
                def_bonus = self._map.get_defense_bonus(coord)
                dist_to_goal = coord.chebyshev_distance(ultimate_goal)
                # 防御加成权重 > 距离（AI 更看重生存）
                score = def_bonus * 3 + max(0, 10 - dist_to_goal)

                if score > best_score:
                    best_score = score
                    best_coord = coord

        return best_coord

    def _generate_patrol_path(self, unit: IUnit) -> list[list[int]]:
        """为巡逻指令生成随机路径（AI3：路径偏向有利地形）。

        Sprint 3 增强：
            - 优先选择防御加成高的地块
            - 确保路径至少 2 个点
            - 不可通行格重试

        Args:
            unit: 当前单位

        Returns:
            路径坐标列表 [[x1, y1], [x2, y2], ...]
        """
        path: list[list[int]] = [[unit.position.x, unit.position.y]]
        cx, cy = unit.position.x, unit.position.y

        num_extra = self._rng.randint(1, 3)
        max_retries = 5  # AI3: 不可通行格重试

        for _ in range(num_extra):
            for _ in range(max_retries):
                dx = self._rng.randint(-3, 3)
                dy = self._rng.randint(-3, 3)
                nx = max(0, min(self._map.width - 1, cx + dx))
                ny = max(0, min(self._map.height - 1, cy + dy))

                coord = Coordinate(nx, ny)
                if not self._map.is_passable(coord):
                    continue

                # AI3: 偏向高防御地形
                def_bonus = self._map.get_defense_bonus(coord)
                if def_bonus >= 1 or self._rng.random() < 0.6:
                    path.append([nx, ny])
                    cx, cy = nx, ny
                    break

        # 确保至少 2 个点（PATROL 要求）
        if len(path) < 2:
            # 添加一个安全相邻格
            for d in [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, -1)]:
                nx, ny = cx + d[0], cy + d[1]
                if 0 <= nx < self._map.width and 0 <= ny < self._map.height:
                    coord = Coordinate(nx, ny)
                    if self._map.is_passable(coord):
                        path.append([nx, ny])
                        break

        return path

    # ── 内部：方向计算 ──────────────────────────────────────────────────

    def _direction_toward_own_hq(self, unit: IUnit) -> str | None:
        """计算单位朝向己方 HQ 的撤退方向。

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
            return dir_y + dir_x
        if dir_x:
            return dir_x
        if dir_y:
            return dir_y
        return "N"

    @staticmethod
    def _parse_direction(direction_str: str):
        """解析方向字符串为 Direction 枚举。

        Args:
            direction_str: "N"/"NE"/"E"/"SE"/"S"/"SW"/"W"/"NW"

        Returns:
            Direction 枚举值，无效时返回 None
        """
        from src.core.constants import Direction

        direction_map: dict[str, Direction] = {
            "N": Direction.N, "NE": Direction.NE,
            "E": Direction.E, "SE": Direction.SE,
            "S": Direction.S, "SW": Direction.SW,
            "W": Direction.W, "NW": Direction.NW,
        }
        return direction_map.get(direction_str.upper())
