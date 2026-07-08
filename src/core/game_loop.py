"""
BlindCommand 游戏主循环 — IGameLoop + IGameState 的具体实现
===============================================================
本模块提供 `GameLoop` 类：组装地图、单位、范围检索、迷雾；
驱动 8 阶段回合时序（DESIGN.md §6.1）；维护回合数与游戏结果；
提供只读状态查询（IGameState）供 #3 指令执行。

关键设计（CORE_SPEC.md §8）：
- #3 拥有的阶段（指令处理、战斗结算、AI 决策）通过构造注入的可调用钩子接入
- #2 不 import src/battle/，不 import src/ui/
- start() 为阻塞式循环（CP-1 命令行用）；GUI 模式下 #4 逐回合调用 run_turn()
- 胜负判定：全歼 / 回合上限 + 订阅 HQ_CAPTURED 事件

版本：v0.2.0（对齐 CORE_SPEC.md §8，CP-2 升级：首次发现追踪 + 动态单位注册）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from src.core.constants import (
    MAX_TURNS,
    MAX_UNITS_PER_FACTION,
    MAX_UNITS_TOTAL,
    Coordinate,
    Faction,
    GameEventType,
    GameOverPayload,
    GameResult,
    HqCapturedPayload,
    PositionReportPayload,
)
from src.core.event_bus import event_bus
from src.core.fog_of_war import FogOfWar
from src.core.interfaces import (
    IFogOfWar,
    ICommander,
    IGameLoop,
    IGameState,
    IMap,
    IRangeQuery,
    IUnit,
)
from src.core.range_utils import RangeQuery

logger = logging.getLogger(__name__)


class GameLoop(IGameLoop, IGameState):
    """游戏主循环与只读状态查询。

    组装 Map、FogOfWar、RangeQuery 和单位注册表，驱动 8 阶段回合。
    #3 通过构造注入钩子接入指令处理、AI、战斗阶段。
    """

    # ── __init__ ───────────────────────────────────────────────────────

    def __init__(
        self,
        game_map: IMap,
        units: list[IUnit],
        commander: ICommander | None = None,
        combat_resolver: Callable[[IGameState], None] | None = None,
        ai_decider: Callable[[IGameState], None] | None = None,
    ) -> None:
        """构造主循环。

        Args:
            game_map: 地图实例
            units: 初始单位列表（双方全部）
            commander: #3 指令管理系统（可空，CP-1 前无）
            combat_resolver: #3 战斗结算钩子，签名 (IGameState) -> None
            ai_decider: #3 AI 决策钩子，签名 (IGameState) -> None

        Raises:
            ValueError: 若 units 中有重复 unit_id
        """
        self._map = game_map
        self._commander = commander
        self._combat_resolver = combat_resolver
        self._ai_decider = ai_decider

        # 单位注册表
        self._units: dict[str, IUnit] = {}
        for u in units:
            if u.unit_id in self._units:
                raise ValueError(f"重复的 unit_id: {u.unit_id}")
            self._units[u.unit_id] = u

        # 子模块
        self._range_query: IRangeQuery = RangeQuery(game_map, self._live_units)
        self._fog = FogOfWar(game_map, self._live_units)

        # 回合与状态
        self._current_turn: int = 0
        self._result: Optional[GameResult] = None
        self._result_reason_str: str = ""  # Sprint 3: 存储游戏结局的实际原因
        self._paused: bool = False
        self._running: bool = False

        # CP-2：已发现敌军追踪（unit_id 集合），避免重复广播 ENEMY_SPOTTED
        self._spotted_enemies: set[str] = set()

        # 初始化友军汇报调度
        for u in units:
            if u.faction == Faction.FRIENDLY:
                self._fog.init_report_schedule(u, self._current_turn)

        # 订阅 HQ 占领事件（#3 广播）
        event_bus.subscribe(GameEventType.HQ_CAPTURED, self._on_hq_captured)

    # ── 工厂方法：从 JSON 文件一键组装（CP-2，供 #5 集成）────────────

    @classmethod
    def from_map_file(
        cls,
        map_path: str | Path,
        *,
        commander: ICommander | None = None,
        combat_resolver: Callable[[IGameState], None] | None = None,
        ai_decider: Callable[[IGameState], None] | None = None,
    ) -> GameLoop:
        """从地图 JSON 文件一键创建 GameLoop（CP-2 新增）。

        自动完成：加载地形 → 创建 GameMap → 根据 unit_config 创建 UnitBase 实例
        → 放置到地图 → 组装 GameLoop。供 #5 在 main.py 中快速集成。

        Args:
            map_path: 地图 JSON 文件路径（如 data/maps/map_01.json）
            commander: #3 指令管理系统（可空）
            combat_resolver: #3 战斗结算钩子
            ai_decider: #3 AI 决策钩子

        Returns:
            组装完成的 GameLoop 实例，已包含双方单位

        Raises:
            FileNotFoundError: 地图文件不存在
            ValueError: JSON 格式错误
        """
        import json

        from src.core.constants import UNIT_STATS, Coordinate, Faction, UnitType
        from src.core.map import GameMap
        from src.core.unit_base import UnitBase

        path = Path(map_path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # 1. 创建地图（直接使用已解析的 data，避免二次读文件）
        terrain: list[list[int]] = data["terrain"]
        friendly_hq = Coordinate(**data["friendly_hq"])
        enemy_hq = Coordinate(**data["enemy_hq"])
        game_map = GameMap(terrain, friendly_hq, enemy_hq)

        # 2. 创建双方单位
        units: list[IUnit] = []
        for faction_key, faction in [("friendly_units", Faction.FRIENDLY),
                                      ("enemy_units", Faction.ENEMY)]:
            for cfg in data.get(faction_key, []):
                try:
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
                except KeyError as e:
                    raise ValueError(
                        f"地图文件 {map_path} 中单位配置缺少必要字段: {e}"
                    ) from e
                if not game_map.place_unit(unit, unit.position):
                    logger.warning(
                        "from_map_file: 无法将单位 %s 放置到 %s，跳过该单位",
                        unit.unit_id, unit.position
                    )
                    continue
                units.append(unit)

        # 3. 组装 GameLoop
        return cls(
            game_map=game_map,
            units=units,
            commander=commander,
            combat_resolver=combat_resolver,
            ai_decider=ai_decider,
        )

    # ── IGameLoop：回合驱动 ───────────────────────────────────────────

    def start(self) -> None:
        """启动阻塞式回合循环（CP-1 命令行用）。GUI 模式下 #4 应调用 run_turn()。"""
        self._running = True
        self._paused = False
        while self._running and self._result is None:
            if self._paused:
                import time
                time.sleep(0.1)
                continue
            self.run_turn()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def run_turn(self) -> Optional[GameResult]:
        """执行一回合的 8 阶段逻辑（如已完成则直接返回结果）。

        Returns:
            GameResult 若本回合触发游戏结束；否则 None
        """
        if self._result is not None:
            return self._result

        self._current_turn += 1

        # ── 阶段 0：回合开始 ─────────────────────────────────────
        event_bus.emit(GameEventType.TURN_START, None)

        # ── 阶段 1：指令出队（#3）─────────────────────────────────
        if self._commander is not None:
            self._commander.process_command_queue(self._current_turn)
            # 注：COMMAND_ARRIVED 事件的 payload 构造与 emit 由 #3 负责
            # 此处仅调用 process，事件由 #3 在其内部 emit

        # ── 阶段 2：AI 决策（#3）───────────────────────────────────
        if self._ai_decider is not None:
            try:
                self._ai_decider(self)
            except Exception:
                logger.exception("AI 决策阶段异常（不中断主循环）")

        # ── 阶段 3：移动结算 ─────────────────────────────────────
        # 本层负责清除已阵亡单位的占用（由后面的 cleanup 统一处理）

        # ── 阶段 4：侦察 / 敌情检测 ──────────────────────────────
        self._detect_enemy_spotted()

        # ── 阶段 5：战斗结算（#3）─────────────────────────────────
        if self._combat_resolver is not None:
            try:
                self._combat_resolver(self)
            except Exception:
                logger.exception("战斗结算阶段异常（不中断主循环）")

        # ── 阶段 6：清理阵亡单位 ─────────────────────────────────
        self._cleanup_dead_units()

        # ── 阶段 7：友军位置汇报 ─────────────────────────────────
        self._report_friendly_positions()

        # ── 阶段 8：胜负判定 ─────────────────────────────────────
        self._result = self.check_victory_conditions()
        if self._result is not None:
            # Sprint 3: 若 _result_reason_str 尚未由 _on_hq_captured 设置，
            # 则使用 check_victory_conditions 对应的默认原因
            if not self._result_reason_str:
                self._result_reason_str = self._default_reason(self._result)
            event_bus.emit(GameEventType.GAME_OVER, GameOverPayload(
                turn=self._current_turn,
                result=self._result.value,
                reason=self._result_reason_str,
            ))

        event_bus.emit(GameEventType.TURN_END, None)
        return self._result

    # ── IGameLoop：查询 ────────────────────────────────────────────────

    def get_current_turn(self) -> int:
        return self._current_turn

    def get_all_units(self, faction: Optional[Faction] = None) -> list[IUnit]:
        if faction is None:
            return [u for u in self._units.values() if u.is_alive]
        return [u for u in self._units.values()
                if u.is_alive and u.faction == faction]

    def get_game_result(self) -> Optional[GameResult]:
        return self._result

    def check_victory_conditions(self) -> Optional[GameResult]:
        """检查胜负条件（全歼 / 回合上限）。

        HQ 占领胜负由 HQ_CAPTURED 事件触发 _on_hq_captured 置位，
        本方法不在内部重复判定占领状态。
        """
        if self._result is not None:
            return self._result

        friendly = [u for u in self._units.values()
                     if u.faction == Faction.FRIENDLY and u.is_alive]
        enemy = [u for u in self._units.values()
                  if u.faction == Faction.ENEMY and u.is_alive]

        if not friendly:
            return GameResult.DEFEAT
        if not enemy:
            return GameResult.VICTORY
        if self._current_turn >= MAX_TURNS:
            return GameResult.DRAW

        return None

    # ── IGameState：只读查询 ───────────────────────────────────────────

    def get_unit_by_id(self, unit_id: str) -> Optional[IUnit]:
        unit = self._units.get(unit_id)
        if unit is not None and not unit.is_alive:
            return None  # 不返回已阵亡单位
        return unit

    def get_map(self) -> IMap:
        return self._map

    def get_range_query(self) -> IRangeQuery:
        return self._range_query

    def get_fog(self) -> IFogOfWar:
        """获取迷雾/视野管理器（CP-2 新增，供 #4 UI 查询可见性）。

        Returns:
            FogOfWar 实例，提供 is_visible_to_faction / is_unit_visible 等查询
        """
        return self._fog

    # 注：get_current_turn 已在 IGameLoop 部分实现（复用）

    # ── CP-2：动态单位注册（供 #3 UnitManager 集成）──────────────────

    def register_unit(self, unit: IUnit) -> bool:
        """运行时注册新单位（CP-2 新增）。

        #3 的 UnitManager 创建单位后调用此方法将单位纳入 GameLoop 管理。
        自动初始化友军汇报调度、将单位放置到地图。

        Sprint 3: 增加 MAX_UNITS_PER_FACTION / MAX_UNITS_TOTAL 上限检查。

        Args:
            unit: 待注册的单位实例

        Returns:
            True 如果注册成功

        Raises:
            ValueError: 若 unit_id 重复或超过单位数量上限
        """
        if unit.unit_id in self._units:
            raise ValueError(f"重复的 unit_id: {unit.unit_id}")

        # Sprint 3: 单位数量上限检查（对齐 CORE_SPEC constants）
        faction_count = sum(
            1 for u in self._units.values() if u.faction == unit.faction and u.is_alive
        )
        total_count = sum(1 for u in self._units.values() if u.is_alive)
        if faction_count >= MAX_UNITS_PER_FACTION:
            raise ValueError(
                f"阵营 {unit.faction.value} 已达单阵营上限 {MAX_UNITS_PER_FACTION}"
            )
        if total_count >= MAX_UNITS_TOTAL:
            raise ValueError(f"总单位数已达全局上限 {MAX_UNITS_TOTAL}")

        self._units[unit.unit_id] = unit

        # 放置到地图
        if not self._map.place_unit(unit, unit.position):
            # 放置失败（如被占），从注册表回退
            del self._units[unit.unit_id]
            return False

        # 友军初始化汇报调度
        if unit.faction == Faction.FRIENDLY:
            self._fog.init_report_schedule(unit, self._current_turn)

        logger.debug("注册单位: %s (%s) @ %s", unit.unit_id, unit.name, unit.position)
        return True

    def unregister_unit(self, unit_id: str) -> Optional[IUnit]:
        """运行时移除单位（CP-2 新增）。

        从注册表移除、从地图移除、取消指令队列。

        Args:
            unit_id: 待移除的单位 ID

        Returns:
            被移除的单位，若不存在返回 None
        """
        unit = self._units.pop(unit_id, None)
        if unit is None:
            return None

        self._map.remove_unit(unit)
        if self._commander is not None:
            self._commander.cancel_all_commands(unit_id)

        # 清理迷雾系统的汇报调度条目
        if unit.faction == Faction.FRIENDLY:
            self._fog.remove_report_schedule(unit_id)

        logger.debug("注销单位: %s (%s)", unit.unit_id, unit.name)
        return unit

    # ── 内部：单位生命周期 ────────────────────────────────────────────

    def _live_units(self) -> list[IUnit]:
        """返回所有存活单位（供 RangeQuery / FogOfWar 的 units_provider）。"""
        return [u for u in self._units.values() if u.is_alive]

    def _cleanup_dead_units(self) -> None:
        """移除地图上已阵亡单位的占用，取消其指令队列。

        Sprint 3: 同时清理 _spotted_enemies 和 FogOfWar 汇报调度条目。
        """
        for u in list(self._units.values()):
            if not u.is_alive:
                self._map.remove_unit(u)
                if self._commander is not None:
                    self._commander.cancel_all_commands(u.unit_id)
                # Sprint 3: 清理已阵亡单位的追踪条目
                self._spotted_enemies.discard(u.unit_id)
                # Sprint 3: 清理 FogOfWar 汇报调度
                if u.faction == Faction.FRIENDLY:
                    self._fog.remove_report_schedule(u.unit_id)

    # ── 内部：阶段 4 敌情检测 ─────────────────────────────────────────

    def _detect_enemy_spotted(self) -> None:
        """遍历友军，检测视野内新出现的敌人并广播 ENEMY_SPOTTED（CP-2 升级）。

        CP-2 改进（对齐 CORE_SPEC.md §8.5）：
        - 维护 _spotted_enemies 集合，仅对「首次发现」的敌军广播事件
        - 检测视野内**所有**敌军（而非仅最近一个）
        - 每回合广播所有新发现的敌军（若有）
        """
        from src.core.constants import EnemySpottedPayload

        for u in self._live_units():
            if u.faction != Faction.FRIENDLY:
                continue

            # 视野内所有敌军（排除已发现的）
            enemies_in_sight = self._range_query.get_units_in_range(
                center=u.position,
                radius=u.vision_range,
                faction=Faction.ENEMY,
            )
            for enemy in enemies_in_sight:
                if enemy.unit_id not in self._spotted_enemies:
                    self._spotted_enemies.add(enemy.unit_id)
                    event_bus.emit(
                        GameEventType.ENEMY_SPOTTED,
                        EnemySpottedPayload(
                            turn=self._current_turn,
                            reporter_id=u.unit_id,
                            reporter_name=u.name,
                            enemy_type=enemy.unit_type.value,
                            enemy_count=1,
                            location=enemy.position.to_tuple(),
                        ),
                    )

    # ── 内部：阶段 7 位置汇报 ─────────────────────────────────────────

    def _report_friendly_positions(self) -> None:
        """对每个应汇报的友军，生成 PositionReportPayload 并广播，然后推进调度。

        Sprint 3: 合并 has_enemy_in_range + find_nearest_enemy 为一次扫描（PERF-G1）。
        """
        for u in self._live_units():
            if u.faction != Faction.FRIENDLY:
                continue
            if not self._fog.should_report_position(u, self._current_turn):
                continue

            approx = self._fog.get_approximate_position(u)

            # Sprint 3: 一次扫描获取最近敌人 + 推导 has_enemy（避免重复扫描）
            nearest = self._range_query.find_nearest_enemy(u)
            has_enemy = nearest is not None

            enemy_info = ""
            if nearest is not None:
                enemy_info = f"发现{nearest.unit_type.value}×1"

            event_bus.emit(GameEventType.POSITION_REPORT, PositionReportPayload(
                turn=self._current_turn,
                unit_id=u.unit_id,
                unit_name=u.name,
                reported_x=approx.x,
                reported_y=approx.y,
                has_enemy_nearby=has_enemy,
                enemy_info=enemy_info,
            ))
            self._fog.on_position_reported(u, self._current_turn)

    # ── 内部：HQ 占领胜负 ─────────────────────────────────────────────

    def _on_hq_captured(self, payload: HqCapturedPayload) -> None:
        """HQ_CAPTURED 事件回调：立即设置游戏结果。

        Sprint 3: 使用枚举比较替代字符串比较，并存储实际结局原因。
        """
        if self._result is not None:
            return  # 已结束，忽略重复

        # Sprint 3: 使用 Faction 枚举进行安全比较（QUAL-G4）
        try:
            capturer = Faction(payload.capturer_faction)
        except ValueError:
            logger.warning("HQ_CAPTURED 事件中无效阵营: %s", payload.capturer_faction)
            return

        # 验证被占领的 HQ 坐标是否与地图上记录的 HQ 坐标一致
        captured_location = Coordinate(*payload.hq_location)
        friendly_hq = self._map.get_faction_hq_location(Faction.FRIENDLY)
        enemy_hq = self._map.get_faction_hq_location(Faction.ENEMY)
        if friendly_hq is None or enemy_hq is None:
            logger.warning("HQ_CAPTURED: 地图未设置 HQ 坐标，忽略事件")
            return
        if captured_location != friendly_hq and captured_location != enemy_hq:
            logger.warning(
                "HQ_CAPTURED 事件坐标 %s 与任一 HQ 坐标（友: %s, 敌: %s）不匹配，忽略",
                captured_location, friendly_hq, enemy_hq
            )
            return

        if capturer == Faction.FRIENDLY:
            self._result = GameResult.VICTORY
            self._result_reason_str = f"占领敌军指挥所（{payload.capturer_name}）"
        else:
            self._result = GameResult.DEFEAT
            self._result_reason_str = f"指挥所沦陷（被 {payload.capturer_name} 占领）"

    # ── 内部：结果文本 ────────────────────────────────────────────────

    @staticmethod
    def _default_reason(result: GameResult) -> str:
        """返回结局的默认人类可读原因（全歼/回合上限）。

        Sprint 3: 重命名自 _result_reason，仅用于 check_victory_conditions 触发的结局。
        HQ 占领结局的原因由 _on_hq_captured 直接设置 _result_reason_str。
        """
        reasons = {
            GameResult.VICTORY: "全歼敌军",
            GameResult.DEFEAT: "全军覆没",
            GameResult.DRAW: f"达到回合上限（{MAX_TURNS} 回合）",
        }
        return reasons.get(result, str(result))
