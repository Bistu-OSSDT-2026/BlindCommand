"""
BlindCommand 全局事件总线
=========================
实现发布/订阅模式，是业务层（#3）和 UI 层（#4）之间的唯一通信渠道。

设计原则：
- 同步执行：emit() 会立即调用所有订阅者的回调，保证事件有序。
- 类型安全：emit() 接受 GameEventType 枚举，拒绝无效事件类型。
- 防崩溃：单个回调抛出异常不会影响其他回调。
- 单例模式（模块级实例）：全局唯一，各模块 import 同一个实例。

使用示例：
    from src.core.event_bus import event_bus

    # 订阅
    def on_battle(payload: BattleResultPayload):
        print(f"战斗: {payload.attacker_name} vs {payload.defender_name}")

    event_bus.subscribe(GameEventType.BATTLE_RESULT, on_battle)

    # 广播
    event_bus.emit(GameEventType.BATTLE_RESULT, BattleResultPayload(...))

    # 取消订阅
    event_bus.unsubscribe(GameEventType.BATTLE_RESULT, on_battle)

版本：v1.0
"""

import logging
from collections import defaultdict
from contextlib import suppress
from typing import Any, Callable

from src.core.constants import GameEventType

logger = logging.getLogger(__name__)

# 回调类型：接收一个任意 payload（由事件类型决定具体类型）
EventHandler = Callable[[Any], None]


class EventBus:
    """全局事件总线。

    线程安全：否（游戏主循环单线程，不需要锁）。
    异常处理：单个回调异常被捕获并日志记录，不影响其他回调。
    """

    def __init__(self) -> None:
        # 事件类型 → 回调列表
        self._handlers: dict[GameEventType, list[EventHandler]] = defaultdict(list)
        self._emitting_depth: int = 0  # 嵌套 emit 深度计数（替代 bool 防止嵌套时提前处理 pending）
        self._pending_operations: list[tuple[str, GameEventType, EventHandler]] = []
        # 统计（调试用）
        self._emit_counts: dict[GameEventType, int] = defaultdict(int)

    # ── 公开 API ──────────────────────────────────────────────────────

    def subscribe(self, event_type: GameEventType, handler: EventHandler) -> None:
        """订阅事件。

        Args:
            event_type: 事件类型
            handler: 回调函数，接收对应的 payload dataclass 作为参数

        Raises:
            TypeError: event_type 不是 GameEventType 枚举值
        """
        if not isinstance(event_type, GameEventType):
            raise TypeError(f"event_type 必须是 GameEventType 枚举值，收到 {type(event_type)}")

        if self._emitting_depth > 0:
            # emit 过程中不允许修改订阅列表，延后处理
            self._pending_operations.append(("subscribe", event_type, handler))
            return

        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: GameEventType, handler: EventHandler) -> None:
        """取消订阅。

        如果 handler 未订阅过该事件，静默忽略。
        """
        if self._emitting_depth > 0:
            self._pending_operations.append(("unsubscribe", event_type, handler))
            return

        with suppress(ValueError):
            self._handlers[event_type].remove(handler)

    def emit(self, event_type: GameEventType, payload: Any = None) -> None:
        """广播事件。

        所有订阅了该事件类型的回调会被同步调用。
        回调顺序：按订阅顺序。

        Args:
            event_type: 事件类型
            payload: 事件载荷（对应 EVENT_PAYLOAD_MAP 中定义的数据类实例）。
                     若该事件类型无载荷要求（如 TURN_START），传 None。

        Raises:
            TypeError: event_type 不是 GameEventType 枚举值
        """
        if not isinstance(event_type, GameEventType):
            raise TypeError(f"event_type 必须是 GameEventType 枚举值，收到 {type(event_type)}")

        # 调试日志（生产环境可关闭）
        logger.debug("EventBus emit: %s (handlers: %d)", event_type.name,
                      len(self._handlers[event_type]))

        self._emit_counts[event_type] += 1

        handlers = self._handlers[event_type].copy()
        self._emitting_depth += 1

        for handler in handlers:
            try:
                handler(payload)
            except Exception:
                logger.exception(
                    "EventBus: 回调 %s 在处理事件 %s 时抛出异常",
                    getattr(handler, "__name__", str(handler)),
                    event_type.name,
                )

        self._emitting_depth -= 1

        # 仅在最外层 emit 完成时处理积攒的订阅/取消操作
        if self._emitting_depth == 0:
            while self._pending_operations:
                op, et, h = self._pending_operations.pop(0)
                if op == "subscribe":
                    if h not in self._handlers[et]:
                        self._handlers[et].append(h)
                elif op == "unsubscribe":
                    with suppress(ValueError):
                        self._handlers[et].remove(h)

    def clear_all(self) -> None:
        """清空所有订阅（仅用于测试重置）。"""
        self._handlers.clear()
        self._emit_counts.clear()
        self._pending_operations.clear()

    # ── 调试 API ──────────────────────────────────────────────────────

    def get_subscriber_count(self, event_type: GameEventType | None = None) -> int:
        """获取订阅者数量。

        Args:
            event_type: 若指定，返回该事件类型的订阅者数；若 None，返回总数
        """
        if event_type is not None:
            return len(self._handlers.get(event_type, []))
        return sum(len(v) for v in self._handlers.values())

    def get_emit_count(self, event_type: GameEventType) -> int:
        """获取某事件类型已被广播的次数（调试/统计用）。"""
        return self._emit_counts.get(event_type, 0)

    def has_subscribers(self, event_type: GameEventType) -> bool:
        """是否有订阅者监听该事件。"""
        return len(self._handlers.get(event_type, [])) > 0


# ============================================================================
# 全局单例
# ============================================================================

# 各模块直接 import 此实例：
#   from src.core.event_bus import event_bus
event_bus = EventBus()
