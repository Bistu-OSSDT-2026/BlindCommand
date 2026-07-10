"""
BlindCommand RTT 实时引擎 — IEngine + IGameState 的具体实现
=============================================================
替代旧 GameLoop（回合制）。60fps tick，8 步骤主循环。

关键设计（RTT_SPEC.md）：
- 单位永不渲染（UI 只显示地形+标记+汇报圈）
- 连续移动（float 坐标，dt 推进）
- 自适应 AI tick
- 攻击锁机制
- 位置汇报定时触发

版本: v1.0 — RTT
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Callable, Optional

from src.core.constants import (
    AI_TICK_COMBAT,
    AI_TICK_EASY,
    AI_TICK_HARD,
    AI_TICK_IDLE,
    COMBAT_ENGAGE_DELAY,
    COMBAT_ROUND_INTERVAL,
    REPORT_INTERVAL_MAX,
    REPORT_INTERVAL_MIN,
    Coordinate,
    Faction,
    GameEventType,
    GameResult,
    HqCapturedPayload,
    PositionReportPayload,
)
from src.core.event_bus import event_bus
from src.core.fog_of_war import FogOfWar
from src.core.interfaces import (
    ICommander,
    IEngine,
    IGameState,
    IMap,
    IRangeQuery,
    IUnit,
)
from src.core.range_utils import RangeQuery

logger = logging.getLogger(__name__)


class RealTimeEngine(IEngine, IGameState):
    """RTT 实时引擎。

    组装 Map、FogOfWar、RangeQuery、单位注册表，驱动 8 步骤主循环。
    #3 通过构造注入钩子接入战斗结算和 AI。
    """

    # ── __init__ ───────────────────────────────────────────────────────

    def __init__(
        self,
        game_map: IMap,
        units: list[IUnit],
        commander: ICommander | None = None,
        combat_resolver: Callable[[IUnit, IUnit, float], None] | None = None,
        ai_decider: Callable[[IGameState], None] | None = None,
        difficulty: str = "中等",
        seed: int | None = None,
    ) -> None:
        self._map = game_map
        self._commander = commander
        self._combat_resolver = combat_resolver
        self._ai_decider = ai_decider
        self._rng = random.Random(seed)

        # 单位注册表
        self._units: dict[str, IUnit] = {}
        for u in units:
            if u.unit_id in self._units:
                raise ValueError(f"重复的 unit_id: {u.unit_id}")
            self._units[u.unit_id] = u

        # 子模块
        self._range_query: IRangeQuery = RangeQuery(game_map, self._live_units)
        self._fog = FogOfWar(game_map, self._live_units, seed=seed)

        # 时间
        self._elapsed: float = 0.0
        self._ai_last_tick: float = 0.0
        self._diff = difficulty

        self._combat_last_round: float = 0.0

        # 回合兼容
        self._result: Optional[GameResult] = None
        self._paused: bool = False
        self._running: bool = False

        # 攻击锁: unit_pair → engage_time
        self._combat_locks: dict[tuple[str, str], float] = {}

        # 战斗活跃列表
        self._active_combats: list[tuple[IUnit, IUnit]] = []

        # ── 首轮汇报标记 ──────────────────────────────────────────
        self._initial_reported = False

        # ── 首轮汇报标记 ──────────────────────────────────────────
        self._initial_reported = False

        # 初始化汇报调度
        for u in units:
            if u.faction == Faction.FRIENDLY:
                self._fog.init_report_schedule(u, 0)

        # 订阅 HQ 占领
        event_bus.subscribe(GameEventType.HQ_CAPTURED, self._on_hq_captured)

    # ── 工厂方法 ──────────────────────────────────────────────────────

    @classmethod
    def from_map_file(
        cls,
        map_path: str | Path,
        *,
        commander: ICommander | None = None,
        combat_resolver: Callable[[IUnit, IUnit, float], None] | None = None,
        ai_decider: Callable[[IGameState], None] | None = None,
        seed: int | None = None,
    ) -> RealTimeEngine:
        import json

        from src.core.constants import UNIT_STATS, Faction, UnitType
        from src.core.map import GameMap
        from src.core.unit_base import UnitBase

        path = Path(map_path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        game_map = GameMap.from_map_file(path)

        units: list[IUnit] = []
        for faction_key, faction in [("friendly_units", Faction.FRIENDLY),
                                      ("enemy_units", Faction.ENEMY)]:
            for cfg in data.get(faction_key, []):
                ut = UnitType(cfg["unit_type"])
                stats = UNIT_STATS[ut]
                unit = UnitBase(
                    unit_id=cfg["unit_id"],
                    name=cfg["name"],
                    faction=faction,
                    unit_type=ut,
                    position=Coordinate(cfg["start_x"], cfg["start_y"]),
                    stats=stats,
                    game_map=game_map,
                )
                game_map.place_unit(unit, unit.position)
                units.append(unit)

        return cls(
            game_map=game_map,
            units=units,
            commander=commander,
            combat_resolver=combat_resolver,
            ai_decider=ai_decider,
            seed=seed,
        )

    # ── IEngine ────────────────────────────────────────────────────────

    def get_elapsed_time(self) -> float:
        return self._elapsed

    def get_all_units(self, faction: Optional[Faction] = None) -> list[IUnit]:
        if faction is None:
            return [u for u in self._units.values() if u.is_alive]
        return [u for u in self._units.values()
                if u.is_alive and u.faction == faction]

    def get_game_result(self) -> Optional[GameResult]:
        return self._result

    def check_victory_conditions(self) -> Optional[GameResult]:
        if self._result is not None:
            return self._result
        friendly = [u for u in self._units.values()
                     if u.faction == Faction.FRIENDLY and u.is_alive and not u.is_hq]
        enemy = [u for u in self._units.values()
                  if u.faction == Faction.ENEMY and u.is_alive and not u.is_hq]
        if not friendly:
            return GameResult.DEFEAT
        if not enemy:
            return GameResult.VICTORY
        return None

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ── IGameState ─────────────────────────────────────────────────────

    def get_unit_by_id(self, unit_id: str) -> Optional[IUnit]:
        return self._units.get(unit_id)

    def get_map(self) -> IMap:
        return self._map

    def get_range_query(self) -> IRangeQuery:
        return self._range_query

    def get_fog(self) -> FogOfWar:
        return self._fog

    # ── 主循环 ─────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        """每帧 tick（60fps）。8 步骤主循环。"""
        if self._paused or self._result is not None:
            return

        # 步骤 1: 前置时序
        self._elapsed += dt

        # 步骤 2: 指令出队 + 执行
        if self._commander is not None:
            self._commander.process_command_queue(self._elapsed)
            # 执行每个友军单位的第一条待执行指令
            for u in self._live_units():
                if hasattr(self._commander, 'execute_pending'):
                    self._commander.execute_pending(u, self)

        # 步骤 3: AI tick
        self._ai_tick()

        # 步骤 4: 物理运动更新
        self._update_movement(dt)

        # 步骤 5: 遭遇检测与攻击锁
        self._detect_engagements()

        # 步骤 6: 周期战斗结算
        self._combat_tick()

        # 步骤 7: 位置汇报
        self._report_friendly_positions()

        # 步骤 8: 胜负判定
        self._result = self.check_victory_conditions()
        if self._result is not None:
            event_bus.emit(GameEventType.GAME_OVER, None)

    # ── 步骤 3: AI ────────────────────────────────────────────────────

    def _ai_tick(self) -> None:
        if self._ai_decider is None:
            return
        has_combat = bool(self._active_combats)
        if self._diff == "简单":
            base = AI_TICK_EASY
        elif self._diff == "困难":
            base = AI_TICK_HARD
        else:
            base = AI_TICK_IDLE
        interval = AI_TICK_COMBAT if has_combat else base
        if self._elapsed - self._ai_last_tick >= interval:
            self._ai_last_tick = self._elapsed
            try:
                self._ai_decider(self)
            except Exception:
                logger.exception("AI tick 异常")

    # ── 步骤 4: 移动 ──────────────────────────────────────────────────

    def _update_movement(self, dt: float) -> None:
        for u in self._live_units():
            if hasattr(u, 'update_movement'):
                was_moving = getattr(u, 'is_moving', False)
                u.update_movement(dt)
                is_still_moving = getattr(u, 'is_moving', False)
                # 移动中遭遇敌方 → 停止（双方攻击范围都检测）
                if is_still_moving:
                    enemies = [e for e in self._live_units()
                               if e.faction != u.faction and e.is_alive]
                    for e in enemies:
                        ex, ey = e.position.x, e.position.y
                        ux, uy = u.position.x, u.position.y
                        if max(abs(ex - ux), abs(ey - uy)) <= max(u.attack_range, e.attack_range):
                            u._moving = False
                            u._path = []
                            if u.faction == Faction.FRIENDLY:
                                event_bus.emit(GameEventType.POSITION_REPORT, PositionReportPayload(
                                    turn=0, unit_id=u.unit_id, unit_name=u.name,
                                    reported_x=ux, reported_y=uy,
                                    has_enemy_nearby=True, enemy_info="途中遭遇敌军，停止移动",
                                ))
                            break
                # 移动完成 → 汇报位置
                if was_moving and not is_still_moving and u.faction == Faction.FRIENDLY:
                    approx = self._fog.get_approximate_position(u)
                    event_bus.emit(GameEventType.POSITION_REPORT, PositionReportPayload(
                        turn=0, unit_id=u.unit_id, unit_name=u.name,
                        reported_x=approx.x, reported_y=approx.y,
                        has_enemy_nearby=False, enemy_info="",
                    ))

    # ── 步骤 5: 遭遇检测 ──────────────────────────────────────────────

    def _detect_engagements(self) -> None:
        """检测敌我距离，锁定攻击队列。"""
        live = self._live_units()
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                if a.faction == b.faction:
                    continue
                if not a.is_alive or not b.is_alive:
                    continue
                ax, ay = a.position.x, a.position.y
                bx, by = b.position.x, b.position.y
                dist = max(abs(ax - bx), abs(ay - by))
                if dist <= max(a.attack_range, b.attack_range):
                    pair_key = self._combat_pair_key(a, b)
                    if pair_key not in self._combat_locks:
                        self._combat_locks[pair_key] = self._elapsed
                        self._active_combats.append((a, b))

    def _combat_pair_key(self, a: IUnit, b: IUnit) -> tuple[str, str]:
        return (min(a.unit_id, b.unit_id), max(a.unit_id, b.unit_id))

    # ── 步骤 6: 战斗结算 ──────────────────────────────────────────────

    def _combat_tick(self) -> None:
        if self._elapsed - self._combat_last_round < COMBAT_ROUND_INTERVAL:
            return
        self._combat_last_round = self._elapsed

        expired: list[tuple[str, str]] = []
        for a, b in self._active_combats:
            pair_key = self._combat_pair_key(a, b)
            locked_at = self._combat_locks.get(pair_key, 0)
            if self._elapsed - locked_at < COMBAT_ENGAGE_DELAY:
                continue
            if not a.is_alive or not b.is_alive:
                expired.append(pair_key)
                continue
            if self._combat_resolver is not None:
                was_alive_a = a.is_alive
                was_alive_b = b.is_alive
                msg = self._combat_resolver(a, b, self._elapsed)
                if not a.is_alive and was_alive_a:
                    from src.core.constants import UnitKilledPayload
                    event_bus.emit(GameEventType.UNIT_KILLED, UnitKilledPayload(
                        turn=0, unit_id=a.unit_id, unit_name=a.name,
                        unit_type=a.unit_type.value, faction=a.faction.value,
                        killer_id=b.unit_id, killer_name=b.name,
                        actual_x=a.position.x, actual_y=a.position.y,
                        reported_x=0, reported_y=0,
                    ))
                    if a.is_hq:
                        from src.core.constants import HqCapturedPayload
                        event_bus.emit(GameEventType.HQ_CAPTURED, HqCapturedPayload(
                            turn=0, capturer_id=b.unit_id, capturer_name=b.name,
                            capturer_faction=b.faction.value,
                            hq_location=a.position.to_tuple(),
                        ))
                if not b.is_alive and was_alive_b:
                    from src.core.constants import UnitKilledPayload
                    event_bus.emit(GameEventType.UNIT_KILLED, UnitKilledPayload(
                        turn=0, unit_id=b.unit_id, unit_name=b.name,
                        unit_type=b.unit_type.value, faction=b.faction.value,
                        killer_id=a.unit_id, killer_name=a.name,
                        actual_x=b.position.x, actual_y=b.position.y,
                        reported_x=0, reported_y=0,
                    ))
                    if b.is_hq:
                        from src.core.constants import HqCapturedPayload
                        event_bus.emit(GameEventType.HQ_CAPTURED, HqCapturedPayload(
                            turn=0, capturer_id=a.unit_id, capturer_name=a.name,
                            capturer_faction=a.faction.value,
                            hq_location=b.position.to_tuple(),
                        ))
                if msg:
                    from src.core.constants import BattleResultPayload
                    event_bus.emit(GameEventType.BATTLE_RESULT, BattleResultPayload(
                        turn=0, attacker_id=a.unit_id, attacker_name=a.name,
                        attacker_faction=a.faction.value, attacker_hp_before=0,
                        attacker_hp_after=0, defender_id=b.unit_id,
                        defender_name=b.name, defender_faction=b.faction.value,
                        defender_hp_before=0, defender_hp_after=0,
                        damage_to_defender=0, damage_to_attacker=0,
                        attacker_killed=False, defender_killed=False,
                        location=a.position.to_tuple(), outcome="",
                    ))
                    # 战报直接追加
                    if hasattr(self, '_battle_log_cb') and self._battle_log_cb:
                        self._battle_log_cb(msg)
                # HQ 被攻击播报
                if a.is_hq and a.faction == Faction.FRIENDLY:
                    event_bus.emit(GameEventType.HQ_UNDER_ATTACK, None)
                if b.is_hq and b.faction == Faction.FRIENDLY:
                    event_bus.emit(GameEventType.HQ_UNDER_ATTACK, None)

        for k in expired:
            self._combat_locks.pop(k, None)
        self._active_combats = [
            (a, b) for a, b in self._active_combats
            if self._combat_pair_key(a, b) in self._combat_locks
        ]

    # ── 步骤 7: 位置汇报 ──────────────────────────────────────────────

    def _report_friendly_positions(self) -> None:
        """开局一次性汇报所有友军位置。之后不重复——由移动完成/战斗触发汇报。"""
        if self._initial_reported:
            return
        self._initial_reported = True
        for u in self._live_units():
            if u.faction != Faction.FRIENDLY or u.is_hq:
                continue
            approx = self._fog.get_approximate_position(u)
            event_bus.emit(GameEventType.POSITION_REPORT, PositionReportPayload(
                turn=0, unit_id=u.unit_id, unit_name=u.name,
                reported_x=approx.x, reported_y=approx.y,
                has_enemy_nearby=False, enemy_info="",
            ))

    # ── 内部 ───────────────────────────────────────────────────────────

    def _live_units(self) -> list[IUnit]:
        return [u for u in self._units.values() if u.is_alive]

    def _on_hq_captured(self, payload: HqCapturedPayload) -> None:
        if self._result is not None:
            return
        if payload.capturer_faction == Faction.FRIENDLY.value:
            self._result = GameResult.VICTORY
        else:
            self._result = GameResult.DEFEAT

    def register_unit(self, unit: IUnit) -> bool:
        if unit.unit_id in self._units:
            raise ValueError(f"重复 unit_id: {unit.unit_id}")
        self._units[unit.unit_id] = unit
        if not self._map.place_unit(unit, unit.position):
            del self._units[unit.unit_id]
            return False
        if unit.faction == Faction.FRIENDLY:
            self._fog._next_report_turn[unit.unit_id] = self._elapsed + self._rng.uniform(
                REPORT_INTERVAL_MIN, REPORT_INTERVAL_MAX
            )
        return True

    def unregister_unit(self, unit_id: str) -> Optional[IUnit]:
        unit = self._units.pop(unit_id, None)
        if unit is None:
            return None
        self._map.remove_unit(unit)
        if self._commander is not None:
            self._commander.cancel_all_commands(unit_id)
        return unit
