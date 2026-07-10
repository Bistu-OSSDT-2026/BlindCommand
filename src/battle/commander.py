"""
RTT 指令解析与执行 — ICommander 实现
=====================================
仅支持 MOVE + RETREAT。延迟从回合改为秒。
params 格式: {"direction": "NE", "distance": 5} 或 {"direction": "W"}

版本: v2.0 — RTT
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

from src.core.constants import (
    COMMAND_DELAY_MAX,
    COMMAND_DELAY_MIN,
    CommandArrivedPayload,
    CommandSentPayload,
    CommandType,
    Coordinate,
    Direction,
    GameEventType,
)
from src.core.event_bus import event_bus
from src.core.interfaces import ICommand, ICommander, IGameState, IMap, IUnit

logger = logging.getLogger(__name__)

_DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# ── 指令机制内部常量 ──────────────────────────────────────────────────

_HOLD_DEFENSE_BONUS: int = 1        # HOLD 驻守时临时防御加成
_SCOUT_VISION_BONUS: int = 2        # SCOUT 侦察时视野临时扩大的格数
_RETREAT_SPEED_BONUS: int = 2       # RETREAT 撤退时额外移动格数


def _adjacent_directions(d: str) -> list[str]:
    """返回主方向的两侧邻向（45°偏）。"""
    if d not in _DIRS:
        return []
    i = _DIRS.index(d)
    return [_DIRS[(i - 1) % 8], _DIRS[(i + 1) % 8]]

_DIR_MAP: dict[str, Direction] = {
    "N": Direction.N, "NE": Direction.NE, "E": Direction.E, "SE": Direction.SE,
    "S": Direction.S, "SW": Direction.SW, "W": Direction.W, "NW": Direction.NW,
}

# ── Direction → (dx, dy) ──────────────────────────────────────────────

_DIR_DELTA: dict[str, tuple[int, int]] = {
    d.name: d.value for d in Direction
}


@dataclass
class Command:  # 不继承 ICommand，避免 dataclass-ABC 冲突
    """单条 RTT 指令。"""

    command_type: CommandType
    target_unit_id: str
    params: dict = field(default_factory=dict)
    issued_time: float = 0.0
    arrival_time: float = 0.0

    def execute(self, unit: IUnit, game_state: IGameState) -> bool:
        return True  # 由 Commander._execute 处理

    def get_human_description(self) -> str:
        if self.command_type == CommandType.MOVE:
            d = self.params.get("direction", "?")
            dist = self.params.get("distance", "?")
            return f"MOVE 方向{d} {dist}格"
        return f"RETREAT 方向{self.params.get('direction', '?')}"


class Commander(ICommander):
    """RTT 指令系统。"""

    def __init__(
        self,
        game_map: IMap,
        seed: int | None = None,
    ) -> None:
        self._map = game_map
        self._rng = random.Random(seed)
        self._queue: list[Command] = []
        self._pending: dict[str, list[Command]] = {}  # unit_id → 待执行队列

    # ── ICommander ────────────────────────────────────────────────────

    def issue_command(
        self,
        unit_id: str,
        command_type: CommandType,
        params: dict | None = None,
        current_time: float = 0,
    ) -> bool:
        params = params or {}
        cmd = Command(
            command_type=command_type,
            target_unit_id=unit_id,
            params=params,
            issued_time=current_time,
            arrival_time=current_time + self._rng.uniform(
                COMMAND_DELAY_MIN, COMMAND_DELAY_MAX
            ),
        )
        self._queue.append(cmd)

        event_bus.emit(GameEventType.COMMAND_SENT, CommandSentPayload(
            turn=0,
            target_unit_id=unit_id,
            target_unit_name=unit_id,
            command_type=command_type.value,
            params=cmd.get_human_description(),
            estimated_arrival_turn=int(cmd.arrival_time),
        ))
        return True

    def process_command_queue(self, current_time: float) -> list[ICommand]:
        """处理到期指令。"""
        due = [c for c in self._queue if c.arrival_time <= current_time]
        self._queue = [c for c in self._queue if c.arrival_time > current_time]

        for cmd in due:
            if cmd.target_unit_id not in self._pending:
                self._pending[cmd.target_unit_id] = []
            self._pending[cmd.target_unit_id].append(cmd)
            event_bus.emit(GameEventType.COMMAND_ARRIVED, CommandArrivedPayload(
                turn=0,
                target_unit_id=cmd.target_unit_id,
                target_unit_name=cmd.target_unit_id,
                command_type=cmd.command_type.value,
            ))

        return due

    def get_pending_commands(self, unit_id: str) -> list[ICommand]:
        return list(self._pending.get(unit_id, []))

    def cancel_all_commands(self, unit_id: str) -> None:
        self._queue = [c for c in self._queue if c.target_unit_id != unit_id]
        self._pending.pop(unit_id, None)

    # ── 执行 ──────────────────────────────────────────────────────────

    def execute_pending(self, unit: IUnit, game_state: IGameState) -> str | None:
        """取出一条待执行指令并执行。返回战报文本。"""
        pending = self._pending.get(unit.unit_id, [])
        if not pending:
            return None

        cmd = pending.pop(0)
        if not pending:
            del self._pending[unit.unit_id]

        return self._dispatch(cmd, unit, game_state)

    def _dispatch(self, cmd: Command, unit: IUnit, gs: IGameState) -> str | None:
        if cmd.command_type == CommandType.MOVE:
            return self._execute_move(cmd, unit, gs)
        elif cmd.command_type == CommandType.RETREAT:
            return self._execute_retreat(cmd, unit, gs)
        return None

    def _execute_move(self, cmd: Command, unit: IUnit, gs: IGameState) -> str:
        direction = cmd.params.get("direction", "N")
        distance = int(cmd.params.get("distance", 1))
        logger.info(f"MOVE: {unit.name} → {direction}{distance}格 from {unit.position}")
        delta = _DIR_DELTA.get(direction, (0, -1))

        tx = unit.position.x + delta[0] * distance
        ty = unit.position.y + delta[1] * distance
        # 钳制 + 寻找最近可通行格
        tx = max(0, min(self._map.width - 1, tx))
        ty = max(0, min(self._map.height - 1, ty))
        target = Coordinate(tx, ty)

        # 如果目标不可通行，沿方向回退找最近可通行格
        if not self._map.is_passable(target):
            for d in range(distance, 0, -1):
                nx = unit.position.x + delta[0] * d
                ny = unit.position.y + delta[1] * d
                nx = max(0, min(self._map.width - 1, nx))
                ny = max(0, min(self._map.height - 1, ny))
                alt = Coordinate(nx, ny)
                if self._map.is_passable(alt):
                    target = alt
                    break
            else:
                return f"{unit.name} 无法向{direction}方向移动——前方有障碍"

        if hasattr(unit, 'set_destination'):
            if unit.set_destination(target):
                return f"{unit.name} 已收到移动指令，向{direction}方向推进"
            # 被阻挡：尝试走尽可能远
            for d in range(distance - 1, 0, -1):
                nx = unit.position.x + delta[0] * d
                ny = unit.position.y + delta[1] * d
                nx = max(0, min(self._map.width - 1, nx))
                ny = max(0, min(self._map.height - 1, ny))
                alt = Coordinate(nx, ny)
                if self._map.is_passable(alt) and unit.set_destination(alt):
                    return f"{unit.name} 向{direction}方向推进{d}格（被阻挡）"
            # 邻向绕路
            for offset_dir in _adjacent_directions(direction):
                od = _DIR_DELTA.get(offset_dir, (0, 0))
                for d in range(distance, 0, -1):
                    nx = unit.position.x + od[0] * d
                    ny = unit.position.y + od[1] * d
                    nx = max(0, min(self._map.width - 1, nx))
                    ny = max(0, min(self._map.height - 1, ny))
                    alt = Coordinate(nx, ny)
                    if self._map.is_passable(alt) and unit.set_destination(alt):
                        return f"{unit.name} 向{offset_dir}方向绕行{d}格"
            return f"{unit.name} 无法移动——{direction}方向被阻挡"
        return f"{unit.name} 无法移动到目标"

    def _execute_retreat(self, cmd: Command, unit: IUnit, gs: IGameState) -> str:
        direction = cmd.params.get("direction", "N")
        delta = _DIR_DELTA.get(direction, (0, -1))
        for dist in range(unit.speed + 2, 0, -1):
            tx = unit.position.x + delta[0] * dist
            ty = unit.position.y + delta[1] * dist
            tx = max(0, min(self._map.width - 1, tx))
            ty = max(0, min(self._map.height - 1, ty))
            target = Coordinate(tx, ty)
            if self._map.is_passable(target) and hasattr(unit, 'set_destination'):
                if unit.set_destination(target):
                    return f"{unit.name} 向{direction}方向撤退！"
        return f"{unit.name} 无法撤退"
