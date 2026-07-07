"""
EventBus 单元测试 — 对齐 CORE_SPEC.md §9.5 & WORKFLOW.md §7.2
================================================================
覆盖：订阅/广播、异常隔离、取消订阅、emit 期间修改订阅。
"""

from __future__ import annotations

import pytest

from src.core.constants import GameEventType
from src.core.event_bus import EventBus, event_bus


# ── 每个测试前后重置全局 event_bus ───────────────────────────────────

@pytest.fixture(autouse=True)
def reset_bus():
    event_bus.clear_all()
    yield
    event_bus.clear_all()


# ============================================================================
# E1 — subscribe → emit → 回调被调用
# ============================================================================

class TestSubscribeAndEmit:

    def test_handler_called_on_emit(self):
        """E1: 订阅后 emit，回调被正确调用并收到 payload。"""
        received = []

        def handler(payload):
            received.append(payload)

        event_bus.subscribe(GameEventType.TURN_START, handler)
        event_bus.emit(GameEventType.TURN_START, {"turn": 1})

        assert len(received) == 1
        assert received[0] == {"turn": 1}

    def test_multiple_handlers_receive_same_event(self):
        """同一事件多个订阅者都收到。"""
        calls = set()

        def h1(_):
            calls.add("h1")

        def h2(_):
            calls.add("h2")

        event_bus.subscribe(GameEventType.TURN_END, h1)
        event_bus.subscribe(GameEventType.TURN_END, h2)
        event_bus.emit(GameEventType.TURN_END, None)

        assert calls == {"h1", "h2"}

    def test_unrelated_event_does_not_fire(self):
        """不相关的事件不会触发回调。"""
        received = []

        def handler(_):
            received.append(1)

        event_bus.subscribe(GameEventType.TURN_START, handler)
        event_bus.emit(GameEventType.TURN_END, None)

        assert len(received) == 0

    def test_no_payload_handler(self):
        """payload=None 事件正常调用 handler（统一传 None）。"""
        received = []

        def handler(payload):
            received.append(payload)

        event_bus.subscribe(GameEventType.TURN_START, handler)
        event_bus.emit(GameEventType.TURN_START, None)

        assert len(received) == 1
        assert received[0] is None


# ============================================================================
# E2 — 回调抛异常不影响其他回调
# ============================================================================

class TestErrorIsolation:

    def test_one_handler_crash_does_not_block_others(self):
        """E2: 一个回调抛异常，其他回调仍被调用。"""
        calls = []

        def crashing(_):
            raise RuntimeError("模拟崩溃")

        def normal(_):
            calls.append("normal")

        event_bus.subscribe(GameEventType.TURN_START, crashing)
        event_bus.subscribe(GameEventType.TURN_START, normal)
        # 不应抛出异常
        event_bus.emit(GameEventType.TURN_START, None)

        assert calls == ["normal"]


# ============================================================================
# unsubscribe
# ============================================================================

class TestUnsubscribe:

    def test_unsubscribed_handler_not_called(self):
        """取消订阅后回调不再被触发。"""
        calls = []

        def handler(_):
            calls.append(1)

        event_bus.subscribe(GameEventType.TURN_START, handler)
        event_bus.unsubscribe(GameEventType.TURN_START, handler)
        event_bus.emit(GameEventType.TURN_START, None)

        assert len(calls) == 0

    def test_unsubscribe_nonexistent_noop(self):
        """取消未订阅的 handler 不抛异常。"""
        def dummy(_):
            pass

        event_bus.unsubscribe(GameEventType.TURN_START, dummy)  # no error


# ============================================================================
# emit 期间修改订阅（延后处理）
# ============================================================================

class TestPendingOperations:

    def test_subscribe_during_emit(self):
        """emit 期间订阅新 handler 会被延后处理（本次不触发）。"""
        calls = []

        def h1(_):
            calls.append("h1")
            # 在 h1 中订阅 h2
            event_bus.subscribe(GameEventType.TURN_START, h2)

        def h2(_):
            calls.append("h2")

        event_bus.subscribe(GameEventType.TURN_START, h1)
        event_bus.emit(GameEventType.TURN_START, None)

        # h1 被调用，emit 期间新订阅的 h2 不会在本次 emit 中被调用
        assert calls == ["h1"], f"h2 不应在本次 emit 中被调用，实际: {calls}"

    def test_unsubscribe_during_emit(self):
        """emit 期间取消订阅会在当前 emit 完成后生效。"""
        calls = []

        def h1(_):
            calls.append("h1")
            event_bus.unsubscribe(GameEventType.TURN_START, h2)

        def h2(_):
            calls.append("h2")

        event_bus.subscribe(GameEventType.TURN_START, h1)
        event_bus.subscribe(GameEventType.TURN_START, h2)
        event_bus.emit(GameEventType.TURN_START, None)

        # h2 在 h1 被调用时仍在 handlers 快照中，仍会被调用
        assert "h1" in calls
        # 取决于 h1 和 h2 的订阅顺序：h1 先注册所以先调用
        # h1 中取消 h2，但 emit 复制了快照，h2 仍在快照中 → h2 仍被调用
        assert "h2" in calls


# ============================================================================
# 类型检查
# ============================================================================

class TestTypeChecking:

    def test_invalid_event_type_raises(self):
        """非 GameEventType 枚举值的 subscribe/emit 抛 TypeError。"""
        with pytest.raises(TypeError, match="GameEventType"):
            event_bus.subscribe("NOT_AN_EVENT", lambda x: x)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="GameEventType"):
            event_bus.emit("NOT_AN_EVENT", None)  # type: ignore[arg-type]


# ============================================================================
# 统计
# ============================================================================

class TestStats:

    def test_subscriber_count(self):
        def h(_):
            pass

        assert event_bus.get_subscriber_count() == 0
        event_bus.subscribe(GameEventType.TURN_START, h)
        assert event_bus.get_subscriber_count() == 1
        assert event_bus.get_subscriber_count(GameEventType.TURN_START) == 1
        assert event_bus.get_subscriber_count(GameEventType.TURN_END) == 0

    def test_emit_count(self):
        def h(_):
            pass

        event_bus.subscribe(GameEventType.TURN_START, h)
        assert event_bus.get_emit_count(GameEventType.TURN_START) == 0
        event_bus.emit(GameEventType.TURN_START, None)
        assert event_bus.get_emit_count(GameEventType.TURN_START) == 1
        event_bus.emit(GameEventType.TURN_START, None)
        assert event_bus.get_emit_count(GameEventType.TURN_START) == 2

    def test_has_subscribers(self):
        def h(_):
            pass

        assert event_bus.has_subscribers(GameEventType.TURN_START) is False
        event_bus.subscribe(GameEventType.TURN_START, h)
        assert event_bus.has_subscribers(GameEventType.TURN_START) is True


# ============================================================================
# clear_all
# ============================================================================

class TestClearAll:

    def test_clear_all_removes_all_handlers(self):
        def h(_):
            pass

        event_bus.subscribe(GameEventType.TURN_START, h)
        event_bus.subscribe(GameEventType.TURN_END, h)
        assert event_bus.get_subscriber_count() == 2

        event_bus.clear_all()
        assert event_bus.get_subscriber_count() == 0
