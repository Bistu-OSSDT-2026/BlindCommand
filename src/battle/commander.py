"""
指令解析与执行系统 — ICommander 接口的具体实现
================================================
本模块提供 `Command` 数据类和 `Commander` 类，实现玩家 7 种指令的
解析、验证、传达延迟与逐回合执行。

指令类型：
    MOVE / ATTACK / HOLD / SCOUT / RETREAT / CAPTURE / PATROL

关键设计：
    - 指令通过 CommandQueue 经历 1~3 回合通信延迟后到达
    - 持续指令（HOLD / PATROL）返回 False 直到被覆盖
    - CAPTURE 占领需要连续停留 CAPTURE_REQUIRED_TURNS 回合
    - 阵亡单位的指令自动取消（订阅 UNIT_KILLED 事件）
    - 战斗结算通过构造注入的 combat_resolver 回调（解耦 BattleSystem）

依赖:
    src/core/interfaces.py  — ICommander, ICommand, IGameState, IMap, IRangeQuery
    src/core/constants.py   — CommandType, 事件载荷, 游戏规则常量
    src/core/event_bus.py   — 事件广播
    src/battle/command_queue.py — CommandQueue
    src/battle/unit_manager.py  — UnitManager

版本: v0.1.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.battle.command_queue import CommandQueue
from src.battle.unit_manager import UnitManager
from src.core.constants import (
    CAPTURE_INTERRUPTIBLE,
    CAPTURE_REQUIRED_TURNS,
    CommandType,
    Coordinate,
    Direction,
    Faction,
    GameEventType,
    TerrainType,
    UnitType,
    CommandArrivedPayload,
    CommandSentPayload,
    EnemySpottedPayload,
    HqCapturedPayload,
)
from src.core.event_bus import event_bus
from src.core.interfaces import ICommand, ICommander, IGameState, IMap, IRangeQuery, IUnit

logger = logging.getLogger(__name__)

# 战斗结算回调类型： (attacker, defender, current_turn) -> result_payload | None
CombatResolver = Callable[[IUnit, IUnit, int], Any]

# ── 指令机制内部常量 ──────────────────────────────────────────────────

_HOLD_DEFENSE_BONUS: int = 1        # HOLD 驻守时临时防御加成
_SCOUT_VISION_BONUS: int = 2        # SCOUT 侦察时视野临时扩大的格数
_RETREAT_SPEED_BONUS: int = 2       # RETREAT 撤退时额外移动格数


# ============================================================================
# Command — 单条指令数据类
# ============================================================================


@dataclass
class Command:
    """单条指令的完整数据。

    实现 ICommand 接口的方法（不继承 ABC 以避免 dataclass 与抽象属性冲突）。
    execute() 委托给 Commander 提供的回调，以实现指令类型分发与状态管理。
    """

    command_type: CommandType
    target_unit_id: str
    params: dict = field(default_factory=dict)
    issued_turn: int = 0
    arrival_turn: int = 0
    _executor: Callable[[Command, IUnit, IGameState], bool] | None = field(
        default=None, repr=False, compare=False
    )

    # ── ICommand 兼容方法 ────────────────────────────────────────────

    def execute(self, unit: IUnit, game_state: IGameState) -> bool:
        """执行指令。

        委托给 Commander 提供的 _executor 回调，
        实现 7 种指令的分派与状态管理。

        Args:
            unit: 执行指令的单位
            game_state: 当前游戏状态（IGameState 查询接口）

        Returns:
            True 如果指令执行完成（不再需要继续），False 如果还需下回合继续
        """
        if self._executor is None:
            logger.warning("Command %s 无 executor，跳过执行", self.command_type.value)
            return True
        return self._executor(self, unit, game_state)

    def get_human_description(self) -> str:
        """返回人类可读的指令描述（用于战报）。

        Returns:
            如 "MOVE → (10, 5)" 或 "HOLD — 原地驻守"
        """
        cmd = self.command_type.value
        if self.command_type == CommandType.MOVE:
            return f"{cmd} → ({self.params.get('x', '?')}, {self.params.get('y', '?')})"
        if self.command_type == CommandType.ATTACK:
            return f"{cmd} → ({self.params.get('x', '?')}, {self.params.get('y', '?')})"
        if self.command_type == CommandType.SCOUT:
            return f"{cmd} 方向 {self.params.get('direction', '?')}"
        if self.command_type == CommandType.RETREAT:
            return f"{cmd} 方向 {self.params.get('direction', '?')}"
        if self.command_type == CommandType.CAPTURE:
            return f"{cmd} → ({self.params.get('x', '?')}, {self.params.get('y', '?')})"
        if self.command_type == CommandType.PATROL:
            path = self.params.get("path", [])
            return f"{cmd} 路径 {len(path)} 点"
        if self.command_type == CommandType.HOLD:
            return f"{cmd} — 原地驻守"
        return f"{cmd}"


# 将 Command 注册为 ICommand 的虚拟子类（不继承以避免 dataclass-ABC 冲突）
ICommand.register(Command)


# ============================================================================
# Commander — 指令管理与传达系统
# ============================================================================


class Commander(ICommander):
    """指令管理与传达系统。

    职责:
        - 解析玩家指令参数，创建 Command 实例
        - 将指令放入 CommandQueue（经历通信延迟）
        - 每回合处理到期指令并执行
        - 管理占领计数器、指令覆盖/取消
        - 广播 COMMAND_SENT / COMMAND_ARRIVED / COMMAND_EXPIRED / HQ_CAPTURED 事件

    由 GameLoop 在阶段 1（指令出队）调用 process_command_queue()。
    """

    # ── __init__ ───────────────────────────────────────────────────────

    def __init__(
        self,
        unit_manager: UnitManager,
        game_map: IMap,
        command_queue: CommandQueue | None = None,
        combat_resolver: CombatResolver | None = None,
        range_query: IRangeQuery | None = None,
        seed: int | None = None,
    ) -> None:
        """初始化指令系统。

        Args:
            unit_manager: 单位管理器（用于 kill_unit、get_hq 等）
            game_map: 地图接口（#2 实现，用于 find_path / move_unit）
            command_queue: 延迟队列（若 None 则创建默认队列）
            combat_resolver: 战斗结算回调，签名 (attacker, defender, turn) -> payload|None
            range_query: 范围检索接口（#2 实现，用于 SCOUT 侦察 / ATTACK 索敌等）
            seed: 随机种子（用于 CommandQueue 延迟的可重现测试）
        """
        self._unit_manager = unit_manager
        self._map = game_map
        self._queue = command_queue if command_queue is not None else CommandQueue(seed=seed)
        self._combat_resolver = combat_resolver
        self._range_query = range_query

        # 占领计数器：unit_id → 已连续停留回合数
        self._capture_progress: dict[str, int] = {}
        # 上一回合各单位的位置（用于检测是否被打断）
        self._last_positions: dict[str, Coordinate] = {}
        # 上一回合各单位的 HP（用于检测占领是否被攻击打断）
        self._last_hp: dict[str, int] = {}
        # PATROL 状态：unit_id → {"path": [...], "index": int, "forward": bool}
        self._patrol_state: dict[str, dict] = {}
        # HOLD 中的单位集合（用于防御加成管理）
        self._hold_units: set[str] = set()

        # 订阅 UNIT_KILLED → 自动清除阵亡单位指令
        event_bus.subscribe(GameEventType.UNIT_KILLED, self._on_unit_killed)

        logger.info(
            "Commander 初始化完成 (units=%d, queue_size=%d)",
            unit_manager.count_alive(),
            self._queue.size,
        )

    # ── ICommander：下达指令 ──────────────────────────────────────────

    def issue_command(
        self,
        unit_id: str,
        command_type: CommandType,
        params: dict | None = None,
        current_turn: int = 0,
    ) -> bool:
        """向指定单位下达指令。指令进入传达队列，经历通信延迟后到达。

        若单位已有待执行指令，旧指令将被覆盖并广播 COMMAND_EXPIRED。

        Args:
            unit_id: 目标单位 ID
            command_type: 指令类型
            params: 指令参数（如 {"x": 10, "y": 5} 或 {"direction": "N"}）
            current_turn: 当前回合数（用于设置 issued_turn 和 arrival_turn）

        Returns:
            True 如果指令有效（单位存在且存活）
        """
        unit = self._unit_manager.get_unit_by_id(unit_id)
        if unit is None or not unit.is_alive:
            logger.warning("issue_command: 单位 %s 不存在或已阵亡", unit_id)
            return False

        # HQ 不可执行移动类指令
        if unit.is_hq and command_type in (
            CommandType.MOVE,
            CommandType.ATTACK,
            CommandType.SCOUT,
            CommandType.RETREAT,
            CommandType.PATROL,
        ):
            logger.info("issue_command: HQ %s 不可执行 %s", unit_id, command_type.value)
            return False

        params = params or {}

        # 指令覆盖：清除旧指令 + 清除关联状态
        self._queue.cancel_for_unit(unit_id)
        self._capture_progress.pop(unit_id, None)
        self._patrol_state.pop(unit_id, None)
        self._hold_units.discard(unit_id)

        # 创建指令并入队
        cmd = Command(
            command_type=command_type,
            target_unit_id=unit_id,
            params=params,
            issued_turn=current_turn,
            arrival_turn=0,
        )
        # 绑定 executor
        cmd._executor = self._dispatch

        arrival = self._queue.enqueue(cmd, current_turn)

        # 广播 COMMAND_SENT
        event_bus.emit(
            GameEventType.COMMAND_SENT,
            CommandSentPayload(
                turn=current_turn,
                target_unit_id=unit_id,
                target_unit_name=unit.name,
                command_type=command_type.value,
                params=cmd.get_human_description(),
                estimated_arrival_turn=arrival,
            ),
        )

        logger.info(
            "指令已入队: %s → %s, 预计 %d 回合到达",
            unit.name,
            command_type.value,
            arrival,
        )
        return True

    # ── ICommander：处理队列 ──────────────────────────────────────────

    def process_command_queue(self, current_turn: int) -> list[ICommand]:
        """处理传达队列，返回本回合到期的指令列表并执行。

        由 GameLoop 每回合在阶段 1 调用。

        Args:
            current_turn: 当前回合数

        Returns:
            本回合到期的指令列表（已执行）
        """
        due_cmds = self._queue.pop_due_commands(current_turn)
        if not due_cmds:
            return []

        executed: list[ICommand] = []
        for cmd in due_cmds:
            unit = self._unit_manager.get_unit_by_id(cmd.target_unit_id)
            if unit is None or not unit.is_alive:
                # 单位已阵亡 → 指令作废
                event_bus.emit(GameEventType.COMMAND_EXPIRED, None)
                logger.info("指令作废: %s 已阵亡", cmd.target_unit_id)
                continue

            # 从 Commander 持有的引用构造 IGameState
            game_state = _SimpleGameState(
                game_map=self._map,
                unit_manager=self._unit_manager,
                range_query=self._range_query,
                current_turn=current_turn,
            )

            # 执行指令
            finished = cmd.execute(unit, game_state)

            # 广播 COMMAND_ARRIVED
            event_bus.emit(
                GameEventType.COMMAND_ARRIVED,
                CommandArrivedPayload(
                    turn=current_turn,
                    target_unit_id=unit.unit_id,
                    target_unit_name=unit.name,
                    command_type=cmd.command_type.value,
                ),
            )

            # 持续指令（HOLD / PATROL）未完成，重新入队下回合继续
            if not finished:
                self._queue.enqueue(cmd, current_turn)
            else:
                executed.append(cmd)

            # 若单位在指令执行中阵亡，取消后续
            if not unit.is_alive:
                self.cancel_all_commands(unit.unit_id)

        # 更新位置和 HP 快照（用于下回合占领打断检测）
        for u in self._unit_manager.get_alive_units():
            self._last_positions[u.unit_id] = u.position
            self._last_hp[u.unit_id] = u.current_hp

        return executed

    # ── ICommander：查询 / 取消 ───────────────────────────────────────

    def get_pending_commands(self, unit_id: str) -> list[ICommand]:
        """获取某单位待执行的指令队列。

        Args:
            unit_id: 单位唯一标识

        Returns:
            待执行指令列表
        """
        return list(self._queue.get_pending_for_unit(unit_id))

    def cancel_all_commands(self, unit_id: str) -> None:
        """取消某单位的所有未执行指令（阵亡时调用）。

        Args:
            unit_id: 单位唯一标识
        """
        pending = self._queue.get_pending_for_unit(unit_id)
        self._queue.cancel_for_unit(unit_id)
        # 清除占领、巡逻、驻守状态
        self._capture_progress.pop(unit_id, None)
        self._patrol_state.pop(unit_id, None)
        self._hold_units.discard(unit_id)
        # 清除死单位的位置/HP 快照（避免内存泄漏）
        self._last_positions.pop(unit_id, None)
        self._last_hp.pop(unit_id, None)
        if pending:
            event_bus.emit(GameEventType.COMMAND_EXPIRED, None)
            logger.info("已取消 %s 的 %d 条待执行指令", unit_id, len(pending))

    # ── 内部：指令分派 ────────────────────────────────────────────────

    def _dispatch(self, cmd: Command, unit: IUnit, game_state: IGameState) -> bool:
        """根据指令类型分派到对应的执行方法。

        Args:
            cmd: 待执行指令
            unit: 目标单位
            game_state: 游戏状态

        Returns:
            True 如果指令完成，False 如果需要继续
        """
        handlers: dict[CommandType, Callable[[Command, IUnit, IGameState], bool]] = {
            CommandType.MOVE: self._execute_move,
            CommandType.ATTACK: self._execute_attack,
            CommandType.HOLD: self._execute_hold,
            CommandType.SCOUT: self._execute_scout,
            CommandType.RETREAT: self._execute_retreat,
            CommandType.CAPTURE: self._execute_capture,
            CommandType.PATROL: self._execute_patrol,
        }

        handler = handlers.get(cmd.command_type)
        if handler is None:
            logger.warning("未知指令类型: %s", cmd.command_type)
            return True

        return handler(cmd, unit, game_state)

    # ── 指令执行：MOVE ─────────────────────────────────────────────────

    def _execute_move(
        self, cmd: Command, unit: IUnit, game_state: IGameState
    ) -> bool:
        """MOVE — 向目标坐标移动。

        路径由 IMap.find_path 计算，每回合移动最多 unit.speed 步。
        若到达目标返回 True，否则返回 False（下回合继续）。
        """
        tx = cmd.params.get("x", -1)
        ty = cmd.params.get("y", -1)
        target = Coordinate(tx, ty)

        game_map = game_state.get_map()

        if not game_map.is_within_bounds(target) or not game_map.is_passable(target):
            logger.info("MOVE: 目标 (%d,%d) 不可达", tx, ty)
            return True  # 目标非法，放弃指令

        if unit.position == target:
            return True  # 已到达

        path = game_map.find_path(unit.position, target, unit.speed)
        if not path:
            return True  # 不可达，放弃

        # 逐格移动
        steps_taken = 0
        for i, next_coord in enumerate(path):
            if i == 0:
                continue  # 跳过起点
            if steps_taken >= unit.speed:
                break

            # 检测途中是否有敌人（停止移动）
            rq = game_state.get_range_query()
            if rq is not None and rq.has_enemy_in_range(unit, unit.attack_range):
                logger.info("MOVE: %s 途中遇敌，停止移动", unit.name)
                break

            if not game_map.move_unit(unit, unit.position, next_coord):
                break

            # 更新单位坐标（Unit.move_to 是简易 teleport，此处直接设）
            self._set_unit_position(unit, next_coord)
            steps_taken += 1

            if unit.position == target:
                return True

        return unit.position == target

    # ── 指令执行：ATTACK ───────────────────────────────────────────────

    def _execute_attack(
        self, cmd: Command, unit: IUnit, game_state: IGameState
    ) -> bool:
        """ATTACK — 向目标区域进击，途中遇敌即战。

        先向目标移动，途中检测敌人 → 调用 combat_resolver 结算战斗。
        接敌或到达目标后返回 True。
        """
        tx = cmd.params.get("x", -1)
        ty = cmd.params.get("y", -1)
        target = Coordinate(tx, ty)

        game_map = game_state.get_map()
        rq = game_state.get_range_query()

        # 先检查当前攻击范围内是否有敌人
        if rq is not None and rq.has_enemy_in_range(unit, unit.attack_range):
            return self._engage_nearest_enemy(unit, game_state)

        # 向目标移动
        if not game_map.is_within_bounds(target) or not game_map.is_passable(target):
            return True

        if unit.position == target:
            return True

        path = game_map.find_path(unit.position, target, unit.speed)
        if not path:
            return True

        for i, next_coord in enumerate(path):
            if i == 0:
                continue

            # 移动前检测敌人
            if rq is not None and rq.has_enemy_in_range(unit, unit.attack_range):
                return self._engage_nearest_enemy(unit, game_state)

            if not game_map.move_unit(unit, unit.position, next_coord):
                break
            self._set_unit_position(unit, next_coord)

            # 移动后再次检测
            if rq is not None and rq.has_enemy_in_range(unit, unit.attack_range):
                return self._engage_nearest_enemy(unit, game_state)

            if unit.position == target:
                return True

        return True

    # ── 指令执行：HOLD ─────────────────────────────────────────────────

    def _execute_hold(
        self, cmd: Command, unit: IUnit, game_state: IGameState
    ) -> bool:
        """HOLD — 原地驻守，遇敌自动反击。持续指令，始终返回 False。"""
        rq = game_state.get_range_query()
        if rq is not None and rq.has_enemy_in_range(unit, unit.attack_range):
            self._engage_nearest_enemy(unit, game_state)

        # 驻守加成：+1 临时防御（仅本回合有效，不累积）
        if hasattr(unit, 'terrain_defense_bonus'):
            game_map = game_state.get_map()
            base_bonus = game_map.get_defense_bonus(unit.position)
            unit.terrain_defense_bonus = base_bonus + _HOLD_DEFENSE_BONUS
            self._hold_units.add(unit.unit_id)

        return False  # 持续指令

    # ── 指令执行：SCOUT ────────────────────────────────────────────────

    def _execute_scout(
        self, cmd: Command, unit: IUnit, game_state: IGameState
    ) -> bool:
        """SCOUT — 向指定方向侦察移动，扩大视野，发现敌人但不交战。"""
        direction_str = cmd.params.get("direction", "N")
        direction = self._parse_direction(direction_str)
        if direction is None:
            logger.warning("SCOUT: 无效方向 %s", direction_str)
            return True

        game_map = game_state.get_map()
        rq = game_state.get_range_query()

        # 侦察时视野临时 +2
        scout_vision = unit.vision_range + _SCOUT_VISION_BONUS

        dx, dy = direction.value
        steps = unit.speed

        for _ in range(steps):
            next_coord = Coordinate(unit.position.x + dx, unit.position.y + dy)
            if not game_map.is_within_bounds(next_coord) or not game_map.is_passable(next_coord):
                break

            if not game_map.move_unit(unit, unit.position, next_coord):
                break
            self._set_unit_position(unit, next_coord)

            # 侦察检测：用增强视野发现敌人
            if rq is not None:
                enemies = rq.get_units_in_range(
                    center=unit.position,
                    radius=scout_vision,
                    faction=Faction.ENEMY if unit.faction == Faction.FRIENDLY else Faction.FRIENDLY,
                    exclude_ids={unit.unit_id},
                )
                for enemy in enemies:
                    event_bus.emit(
                        GameEventType.ENEMY_SPOTTED,
                        EnemySpottedPayload(
                            turn=game_state.get_current_turn(),
                            reporter_id=unit.unit_id,
                            reporter_name=unit.name,
                            enemy_type=enemy.unit_type.value,
                            enemy_count=1,
                            location=enemy.position.to_tuple(),
                        ),
                    )
                    logger.info(
                        "SCOUT: %s 发现敌军 %s 在 (%d,%d)",
                        unit.name,
                        enemy.name,
                        enemy.position.x,
                        enemy.position.y,
                    )

        return True  # 完成本次 SCOUT

    # ── 指令执行：RETREAT ──────────────────────────────────────────────

    def _execute_retreat(
        self, cmd: Command, unit: IUnit, game_state: IGameState
    ) -> bool:
        """RETREAT — 向指定方向快速撤退 speed+2 格，不反击。"""
        direction_str = cmd.params.get("direction", "N")
        direction = self._parse_direction(direction_str)
        if direction is None:
            return True

        game_map = game_state.get_map()
        start_pos = unit.position
        dx, dy = direction.value
        steps = unit.speed + _RETREAT_SPEED_BONUS

        # 记录旧位置并移除占用（后续直接设坐标，不经过 move_unit）
        game_map.remove_unit(unit)

        for _ in range(steps):
            next_coord = Coordinate(unit.position.x + dx, unit.position.y + dy)
            if not game_map.is_within_bounds(next_coord):
                break
            # 撤退忽略敌方单位占格，但尊重不可通行地形
            if not game_map.is_passable(next_coord):
                break

            self._set_unit_position(unit, next_coord)

        # 在最终位置重新放置单位
        game_map.place_unit(unit, unit.position)

        return True

    # ── 指令执行：CAPTURE ──────────────────────────────────────────────

    def _execute_capture(
        self, cmd: Command, unit: IUnit, game_state: IGameState
    ) -> bool:
        """CAPTURE — 移动到敌方指挥所并占领。

        占领需连续停留 CAPTURE_REQUIRED_TURNS 回合。
        被打断时若 CAPTURE_INTERRUPTIBLE=True 则重置计数。
        """
        tx = cmd.params.get("x", -1)
        ty = cmd.params.get("y", -1)
        target = Coordinate(tx, ty)

        game_map = game_state.get_map()
        current_turn = game_state.get_current_turn()

        # 阶段 1：移动到目标
        if unit.position != target:
            path = game_map.find_path(unit.position, target, unit.speed)
            if not path:
                return True  # 不可达，放弃

            for i, next_coord in enumerate(path):
                if i == 0:
                    continue
                if not game_map.move_unit(unit, unit.position, next_coord):
                    break
                self._set_unit_position(unit, next_coord)
                if unit.position == target:
                    break

            if unit.position != target:
                return False  # 还没到，下回合继续
            # 到达目标格，进入占领阶段

        # 阶段 2：验证是否为敌方 HQ 格
        terrain = game_map.get_terrain(target)
        if terrain != TerrainType.HQ_CELL:
            logger.info("CAPTURE: 目标 (%d,%d) 不是指挥所", tx, ty)
            return True  # 不是 HQ，放弃

        # 查找该格上的敌方 HQ 单位
        units_at_target = game_map.get_units_at(target)
        enemy_hq = None
        for u in units_at_target:
            if u.is_hq and u.faction != unit.faction:
                enemy_hq = u
                break

        if enemy_hq is None:
            logger.info("CAPTURE: 目标格无敌方 HQ")
            return True

        # 阶段 3：仅步兵可触发占领（其他兵种可到达 HQ 格但无法占领）
        if unit.unit_type != UnitType.INFANTRY:
            logger.info(
                "CAPTURE: %s 不是步兵，无法占领指挥所（当前兵种: %s）",
                unit.name,
                unit.unit_type.value,
            )
            return True  # 指令完成，但未占领

        # 阶段 4：占领倒计时
        # 检测是否被打断（位置改变或受到攻击导致 HP 下降）
        prev_pos = self._last_positions.get(unit.unit_id)
        prev_hp = self._last_hp.get(unit.unit_id)
        position_changed = (
            prev_pos is not None
            and prev_pos != unit.position
        )
        hp_decreased = (
            prev_hp is not None
            and unit.current_hp < prev_hp
        )
        interrupted = CAPTURE_INTERRUPTIBLE and (position_changed or hp_decreased)

        if interrupted:
            self._capture_progress[unit.unit_id] = 0
            logger.info("CAPTURE: %s 占领被打断（位置变化=%s HP下降=%s），重置计数",
                        unit.name, position_changed, hp_decreased)

        # 累计回合
        progress = self._capture_progress.get(unit.unit_id, 0) + 1
        self._capture_progress[unit.unit_id] = progress

        logger.info(
            "CAPTURE: %s 占领进度 %d/%d",
            unit.name,
            progress,
            CAPTURE_REQUIRED_TURNS,
        )

        if progress >= CAPTURE_REQUIRED_TURNS:
            # 占领成功！
            self._unit_manager.kill_unit(enemy_hq, unit, current_turn)
            event_bus.emit(
                GameEventType.HQ_CAPTURED,
                HqCapturedPayload(
                    turn=current_turn,
                    capturer_id=unit.unit_id,
                    capturer_name=unit.name,
                    capturer_faction=unit.faction.value,
                    hq_location=target.to_tuple(),
                ),
            )
            self._capture_progress.pop(unit.unit_id, None)
            logger.info("CAPTURE: %s 成功占领敌方指挥所！", unit.name)
            return True

        return False  # 继续占领

    # ── 指令执行：PATROL ───────────────────────────────────────────────

    def _execute_patrol(
        self, cmd: Command, unit: IUnit, game_state: IGameState
    ) -> bool:
        """PATROL — 沿路径列表往复巡逻，途中遇敌自动攻击。持续指令。"""
        path_raw = cmd.params.get("path", [])
        if len(path_raw) < 2:
            logger.warning("PATROL: 路径至少需要 2 个点")
            return True

        # 初始化巡逻状态
        uid = unit.unit_id
        if uid not in self._patrol_state:
            self._patrol_state[uid] = {
                "path": [Coordinate(p[0], p[1]) for p in path_raw],
                "index": 0,
                "forward": True,
            }

        state = self._patrol_state[uid]
        waypoints = state["path"]
        idx = state["index"]
        forward = state["forward"]

        game_map = game_state.get_map()
        rq = game_state.get_range_query()

        # 检查当前是否在攻击范围内有敌人
        if rq is not None and rq.has_enemy_in_range(unit, unit.attack_range):
            self._engage_nearest_enemy(unit, game_state)

        # 确定下一个目标
        if forward:
            target_idx = idx + 1
            if target_idx >= len(waypoints):
                forward = False
                target_idx = idx - 1
        else:
            target_idx = idx - 1
            if target_idx < 0:
                forward = True
                target_idx = idx + 1

        target = waypoints[target_idx]

        # 移动一步
        path = game_map.find_path(unit.position, target, unit.speed)
        if path and len(path) >= 2:
            next_coord = path[1]
            if game_map.move_unit(unit, unit.position, next_coord):
                self._set_unit_position(unit, next_coord)

        # 到达当前目标点 → 更新索引
        if unit.position == target:
            state["index"] = target_idx
            state["forward"] = forward

        return False  # 持续指令

    # ── 内部：辅助方法 ─────────────────────────────────────────────────

    def _engage_nearest_enemy(self, unit: IUnit, game_state: IGameState) -> bool:
        """攻击最近的敌人。

        Args:
            unit: 攻击方
            game_state: 游戏状态

        Returns:
            True 如果发生了战斗
        """
        if self._combat_resolver is None:
            return False

        rq = game_state.get_range_query()
        if rq is None:
            return False

        enemy = rq.find_nearest_enemy(unit)
        if enemy is None:
            return False

        self._combat_resolver(unit, enemy, game_state.get_current_turn())
        return True

    def _on_unit_killed(self, payload: Any) -> None:
        """UNIT_KILLED 事件回调：清除阵亡单位的所有待执行指令。"""
        if payload is None:
            return
        unit_id = getattr(payload, "unit_id", None)
        if unit_id is None:
            return
        self.cancel_all_commands(unit_id)

    @staticmethod
    def _parse_direction(direction_str: str) -> Direction | None:
        """解析方向字符串为 Direction 枚举。

        Args:
            direction_str: "N"/"NE"/"E"/"SE"/"S"/"SW"/"W"/"NW"

        Returns:
            Direction 枚举值，无效时返回 None
        """
        direction_map: dict[str, Direction] = {
            "N": Direction.N, "NE": Direction.NE,
            "E": Direction.E, "SE": Direction.SE,
            "S": Direction.S, "SW": Direction.SW,
            "W": Direction.W, "NW": Direction.NW,
        }
        return direction_map.get(direction_str.upper())

    @staticmethod
    def _set_unit_position(unit: IUnit, coord: Coordinate) -> None:
        """更新单位坐标（绕过 move_to 的路径验证）。

        通过 UnitBase.set_position 直接设坐标（Commander 已自行处理
        game_map.move_unit 的地图占用更新，只需同步单位内部坐标）。
        """
        if hasattr(unit, 'set_position'):
            unit.set_position(coord)
        else:
            # 回退：旧版 Unit 类的 move_to 是简易 teleport
            unit.move_to(coord)


# ============================================================================
# _SimpleGameState — IGameState 的轻量实现
# ============================================================================


class _SimpleGameState(IGameState):
    """IGameState 的简易实现，供 Commander 内部使用。

    包装 game_map + unit_manager + range_query + current_turn，提供只读查询。
    不持有 GameLoop 引用，避免循环依赖。
    """

    def __init__(
        self,
        game_map: IMap,
        unit_manager: UnitManager,
        range_query: IRangeQuery | None,
        current_turn: int,
    ) -> None:
        self._map = game_map
        self._unit_manager = unit_manager
        self._range_query = range_query
        self._current_turn = current_turn

    def get_unit_by_id(self, unit_id: str) -> IUnit | None:
        return self._unit_manager.get_unit_by_id(unit_id)

    def get_map(self) -> IMap:
        return self._map

    def get_range_query(self) -> IRangeQuery | None:
        return self._range_query

    def get_current_turn(self) -> int:
        return self._current_turn

    def get_fog(self) -> "IFogOfWar | None":  # type: ignore[name-defined]
        """_SimpleGameState 不持有 FogOfWar 实例，返回 None。"""
        return None
