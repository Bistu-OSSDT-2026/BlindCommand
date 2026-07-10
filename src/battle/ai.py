"""
RTT 敌军 AI — 兵种差异化 + 协同 + 战况判断 + 难度分层
=========================================================
简单: 向HQ推进 + 撤退
中等: + HQ优先攻击 + 集火
困难: + 炮兵距离保持 + 包夹 + 回防 + 撤退反扑
"""

from __future__ import annotations

import logging
import random

from src.core.constants import (
    COMBAT_ROUT_CHANCE,
    COMBAT_ROUT_HP_RATIO,
    CommandType,
    Coordinate,
    Faction,
    UnitType,
)
from src.core.interfaces import ICommander, IGameState, IMap, IRangeQuery, IUnit

logger = logging.getLogger(__name__)

_DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


class EnemyAI:
    """RTT 敌军 AI。"""

    def __init__(
        self, game_map: IMap, range_query: IRangeQuery,
        commander: ICommander, difficulty: str = "中等", seed: int | None = None,
    ) -> None:
        self._map = game_map
        self._rq = range_query
        self._commander = commander
        self._diff = difficulty
        self._rng = random.Random(seed)
        # 撤退过的单位（困难：撤退后反扑）
        self._retreated: set[str] = set()
        self._last_pos: dict[str, Coordinate] = {}
        self._stuck_count: dict[str, int] = {}

    def decide_all(self, game_state: IGameState) -> None:
        current_time = game_state.get_elapsed_time()
        all_units = []
        friendly = []
        if hasattr(game_state, 'get_all_units'):
            all_units = game_state.get_all_units(Faction.ENEMY)
            friendly = game_state.get_all_units(Faction.FRIENDLY)

        alive = [u for u in all_units if u.is_alive]
        alive_f = [u for u in friendly if u.is_alive]
        advantage = len(alive) > len(alive_f) * 1.3
        disadvantage = len(alive) < len(alive_f) * 0.7

        for unit in alive:
            if unit.is_hq:
                continue
            try:
                self._decide_one(unit, current_time, advantage, disadvantage, alive_f)
            except Exception:
                logger.exception("AI 决策异常: %s", unit.name)

    def _decide_one(
        self, unit: IUnit, t: float, advantage: bool, disadvantage: bool,
        enemies: list[IUnit],
    ) -> None:
        # ── 防卡检测 ───────────────────────────────────────────
        uid = unit.unit_id
        prev = self._last_pos.get(uid)
        if prev is not None and prev == unit.position:
            self._stuck_count[uid] = self._stuck_count.get(uid, 0) + 1
        else:
            self._stuck_count[uid] = 0
        self._last_pos[uid] = unit.position
        stuck = self._stuck_count.get(uid, 0) >= 2

        # ── 1. 低血量撤退 ───────────────────────────────────────
        if unit.hp_ratio < COMBAT_ROUT_HP_RATIO and not unit.is_hq:
            if self._rng.random() < COMBAT_ROUT_CHANCE:
                hq = self._map.get_faction_hq_location(unit.faction)
                if hq:
                    self._retreated.add(unit.unit_id)
                    self._issue(unit, CommandType.RETREAT,
                                {"direction": self._dir_to(unit, hq)}, t)
                    return

        # ── 困难：撤退后反扑 ──────────────────────────────────────
        if self._diff == "困难" and unit.unit_id in self._retreated:
            if unit.hp_ratio > 0.5 and not self._rq.has_enemy_in_range(unit, unit.attack_range):
                self._retreated.discard(unit.unit_id)
                # 反扑
                enemy_hq = self._map.get_faction_hq_location(
                    Faction.FRIENDLY if unit.faction == Faction.ENEMY else Faction.ENEMY)
                if enemy_hq:
                    self._issue(unit, CommandType.MOVE,
                                {"direction": self._dir_to(unit, enemy_hq), "distance": 3}, t)
                    return

        # ── 2. 战斗中不动 ────────────────────────────────────────
        if self._rq.has_enemy_in_range(unit, unit.attack_range):
            return

        # ── 3. 劣势 → 收缩 ───────────────────────────────────────
        if disadvantage:
            hq = self._map.get_faction_hq_location(unit.faction)
            if hq:
                self._issue(unit, CommandType.MOVE,
                            {"direction": self._dir_to(unit, hq), "distance": 3}, t)
                return

        # ── 困难：回防己方HQ ──────────────────────────────────────
        if self._diff == "困难":
            own_hq = self._map.get_faction_hq_location(unit.faction)
            if own_hq:
                for e in enemies:
                    if not e.is_alive:
                        continue
                    if max(abs(e.position.x - own_hq.x), abs(e.position.y - own_hq.y)) <= 4:
                        self._issue(unit, CommandType.MOVE,
                                    {"direction": self._dir_to(unit, own_hq), "distance": 4}, t)
                        return

        # ── 4. 敌方 HQ ───────────────────────────────────────────
        enemy_hq = self._map.get_faction_hq_location(
            Faction.FRIENDLY if unit.faction == Faction.ENEMY else Faction.ENEMY)
        if enemy_hq is None:
            return

        dist_to_hq = max(abs(unit.position.x - enemy_hq.x),
                         abs(unit.position.y - enemy_hq.y))

        # 靠近 HQ → 直接压上
        if dist_to_hq <= 3:
            self._issue(unit, CommandType.MOVE,
                        {"direction": self._dir_to(unit, enemy_hq), "distance": 1}, t)
            return

        # ── 5. 兵种差异化（卡住时随机方向） ────────────────────────
        ut = unit.unit_type
        if stuck:
            direction = self._rng.choice(_DIRS)
            self._issue(unit, CommandType.MOVE,
                        {"direction": direction, "distance": self._rng.randint(2, 4)}, t)
            return

        if ut == UnitType.CAVALRY:
            if self._diff in ("中等", "困难"):
                flank_dir = self._flank_dir(unit, enemy_hq)
                self._issue(unit, CommandType.MOVE,
                            {"direction": flank_dir, "distance": self._rng.randint(3, 5)}, t)
            else:
                self._issue(unit, CommandType.MOVE,
                            {"direction": self._dir_to(unit, enemy_hq),
                             "distance": self._rng.randint(3, 5)}, t)

        elif ut == UnitType.ARTILLERY:
            if self._diff == "困难" and dist_to_hq <= unit.attack_range + 1:
                return  # 保持射程，不前进
            self._issue(unit, CommandType.MOVE,
                        {"direction": self._dir_to(unit, enemy_hq), "distance": 2}, t)

        elif ut == UnitType.SCOUT:
            # 偏向敌方 HQ，但加随机偏移
            base_dir = self._dir_to(unit, enemy_hq)
            idx = _DIRS.index(base_dir) if base_dir in _DIRS else 0
            offset = self._rng.choice([-1, 0, 1])
            patrol_dir = _DIRS[(idx + offset) % 8]
            self._issue(unit, CommandType.MOVE,
                        {"direction": patrol_dir, "distance": self._rng.randint(3, 5)}, t)

        else:  # Infantry
            direction = self._dir_to(unit, enemy_hq)
            dist = self._rng.randint(2, 4) if advantage else self._rng.randint(3, 5)
            self._issue(unit, CommandType.MOVE,
                        {"direction": direction, "distance": dist}, t)

    def _flank_dir(self, unit: IUnit, target: Coordinate) -> str:
        base = self._dir_to(unit, target)
        idx = _DIRS.index(base) if base in _DIRS else 0
        offset = 1 if self._rng.random() < 0.5 else -1  # 45° 偏转
        return _DIRS[(idx + offset) % 8]

    def _dir_to(self, unit: IUnit, target: Coordinate) -> str:
        dx = target.x - unit.position.x
        dy = target.y - unit.position.y
        if dx == 0 and dy == 0:
            return "N"
        ax, ay = abs(dx), abs(dy)
        if ax > 2 * ay:
            return "E" if dx > 0 else "W"
        if ay > 2 * ax:
            return "S" if dy > 0 else "N"
        parts = []
        if dy < 0: parts.append("N")
        if dy > 0: parts.append("S")
        if dx < 0: parts.append("W")
        if dx > 0: parts.append("E")
        return "".join(parts) if parts else "N"

    def _issue(self, unit, cmd_type, params, current_time):
        self._commander.issue_command(unit.unit_id, cmd_type, params, current_time)
