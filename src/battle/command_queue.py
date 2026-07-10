"""
通信延迟队列 — 指令的传达延迟管理
===================================
本模块实现 `CommandQueue` 类：管理指令从"下达"到"到达单位"之间的
通信延迟（1~3 回合随机），提供入队/出队/取消/查询等操作。

延迟分布（COMMAND_DELAY_WEIGHTS）：
    - 1 回合：30%
    - 2 回合：50%
    - 3 回合：20%

依赖：
    src/core/constants.py — COMMAND_DELAY_* 常量

版本: v0.1.0
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from src.core.constants import COMMAND_DELAY_MAX, COMMAND_DELAY_MIN, COMMAND_DELAY_WEIGHTS

if TYPE_CHECKING:
    from src.battle.commander import Command


class CommandQueue:
    """通信延迟队列。

    管理指令从"下达"到"到达单位"之间的延迟。
    所有指令（玩家 + AI）经过同一个队列，公平对待。
    """

    # ── __init__ ───────────────────────────────────────────────────────

    def __init__(self, seed: int | None = None) -> None:
        """初始化延迟队列。

        Args:
            seed: 随机种子（测试用例用于可复现）
        """
        self._queue: list[Command] = []
        self._rng = random.Random(seed)

    # ── 入队 ──────────────────────────────────────────────────────────

    def enqueue(self, command: Command, current_turn: int) -> int:
        """指令入队，随机分配通信延迟。

        延迟概率分布（COMMAND_DELAY_WEIGHTS）：
            - 30%：1 回合
            - 50%：2 回合
            - 20%：3 回合

        Args:
            command: 待传达的指令
            current_turn: 当前回合数

        Returns:
            指令预计到达回合数（= current_turn + delay）
        """
        delay = self._roll_delay()
        command.arrival_turn = current_turn + delay
        self._queue.append(command)
        return command.arrival_turn

    # ── 出队 ──────────────────────────────────────────────────────────

    def pop_due_commands(self, current_turn: int) -> list[Command]:
        """返回并移除所有本回合到期的指令。

        Args:
            current_turn: 当前回合数

        Returns:
            到期的指令列表（按入队顺序）
        """
        due: list[Command] = []
        remaining: list[Command] = []

        for cmd in self._queue:
            if cmd.arrival_turn <= current_turn:
                due.append(cmd)
            else:
                remaining.append(cmd)

        self._queue = remaining
        return due

    # ── 查询 ──────────────────────────────────────────────────────────

    def get_pending_for_unit(self, unit_id: str) -> list[Command]:
        """获取某单位的所有待执行指令（不修改队列）。

        Args:
            unit_id: 单位唯一标识

        Returns:
            该单位的待执行指令列表
        """
        return [cmd for cmd in self._queue if cmd.target_unit_id == unit_id]

    def cancel_for_unit(self, unit_id: str) -> None:
        """移除某单位的所有待执行指令。

        Args:
            unit_id: 单位唯一标识
        """
        self._queue = [
            cmd for cmd in self._queue if cmd.target_unit_id != unit_id
        ]

    def peek_all(self) -> list[Command]:
        """查看队列中所有指令（不修改队列，调试用）。

        Returns:
            全部待执行指令列表
        """
        return list(self._queue)

    # ── 属性 ──────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        """队列中待处理指令总数。"""
        return len(self._queue)

    # ── 内部辅助 ──────────────────────────────────────────────────────

    def _roll_delay(self) -> int:
        """根据权重分布随机延迟回合数。

        Returns:
            延迟回合数，范围 [COMMAND_DELAY_MIN, COMMAND_DELAY_MAX]

        Raises:
            ValueError: 若 COMMAND_DELAY_WEIGHTS 长度与延迟值数量不匹配
        """
        values = list(range(COMMAND_DELAY_MIN, COMMAND_DELAY_MAX + 1))
        if len(values) != len(COMMAND_DELAY_WEIGHTS):
            raise ValueError(
                f"COMMAND_DELAY_WEIGHTS 长度 ({len(COMMAND_DELAY_WEIGHTS)}) "
                f"与延迟范围 [{COMMAND_DELAY_MIN}, {COMMAND_DELAY_MAX}] "
                f"({len(values)} 个值) 不匹配"
            )
        return self._rng.choices(values, weights=COMMAND_DELAY_WEIGHTS, k=1)[0]
