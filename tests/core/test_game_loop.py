"""
GameLoop 单元测试 — 对齐 CORE_SPEC.md §9.5
=============================================
覆盖：回合推进、胜负判定（全歼/回合上限/HQ 占领）、位置汇报。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.core.constants import (
    MAX_TURNS,
    UNIT_STATS,
    Coordinate,
    Faction,
    GameEventType,
    GameResult,
    HqCapturedPayload,
    UnitType,
)
from src.core.event_bus import EventBus, event_bus
from src.core.fog_of_war import FogOfWar
from src.core.game_loop import GameLoop
from src.core.map import GameMap
from src.core.unit_base import UnitBase


# ── 辅助 ──────────────────────────────────────────────────────────────

PLAIN_10X10 = [[0] * 10 for _ in range(10)]


def _make_friendly(uid: str, x: int, y: int, utype: UnitType = UnitType.INFANTRY) -> UnitBase:
    return UnitBase(uid, uid, Faction.FRIENDLY, utype, Coordinate(x, y), UNIT_STATS[utype])


def _make_enemy(uid: str, x: int, y: int, utype: UnitType = UnitType.INFANTRY) -> UnitBase:
    return UnitBase(uid, uid, Faction.ENEMY, utype, Coordinate(x, y), UNIT_STATS[utype])


@pytest.fixture(autouse=True)
def reset_event_bus():
    """每个测试前后清空 EventBus 订阅。"""
    event_bus.clear_all()
    yield
    event_bus.clear_all()


@pytest.fixture
def plain_map() -> GameMap:
    return GameMap(PLAIN_10X10, Coordinate(0, 0), Coordinate(9, 9))


# ============================================================================
# 回合推进与事件
# ============================================================================

class TestTurnProgression:

    def test_turn_counter_increments(self, plain_map):
        u_f = _make_friendly("u1", 5, 5)
        u_e = _make_enemy("e1", 8, 8)
        gl = GameLoop(plain_map, [u_f, u_e])
        assert gl.get_current_turn() == 0
        gl.run_turn()
        assert gl.get_current_turn() == 1
        gl.run_turn()
        assert gl.get_current_turn() == 2

    def test_turn_start_and_end_events(self, plain_map):
        """每回合 emit TURN_START 和 TURN_END 各一次。"""
        u = _make_enemy("e1", 8, 8)
        gl = GameLoop(plain_map, [u])

        calls = []

        def on_start(*_):
            calls.append("START")
        def on_end(*_):
            calls.append("END")

        event_bus.subscribe(GameEventType.TURN_START, on_start)
        event_bus.subscribe(GameEventType.TURN_END, on_end)

        gl.run_turn()
        assert calls == ["START", "END"]


# ============================================================================
# 胜负判定：全歼
# ============================================================================

class TestVictoryByAnnihilation:

    def test_victory_when_enemy_dead(self, plain_map):
        f = _make_friendly("f1", 5, 5)
        e = _make_enemy("e1", 8, 8)
        gl = GameLoop(plain_map, [f, e])

        # 手动击杀敌军
        e.take_damage(999, f)
        result = gl.run_turn()   # cleanup + victory check
        assert result == GameResult.VICTORY

    def test_defeat_when_friendly_dead(self, plain_map):
        f = _make_friendly("f1", 5, 5)
        e = _make_enemy("e1", 8, 8)
        gl = GameLoop(plain_map, [f, e])

        f.take_damage(999, e)
        result = gl.run_turn()
        assert result == GameResult.DEFEAT

    def test_game_over_event_emitted(self, plain_map):
        f = _make_friendly("f1", 5, 5)
        gl = GameLoop(plain_map, [f])
        f.take_damage(999, f)  # 自杀 → 全军覆没

        payload_captured = []

        def on_game_over(payload):
            payload_captured.append(payload)

        event_bus.subscribe(GameEventType.GAME_OVER, on_game_over)
        gl.run_turn()

        assert len(payload_captured) == 1
        assert payload_captured[0].result == GameResult.DEFEAT.value


# ============================================================================
# 胜负判定：回合上限
# ============================================================================

class TestDrawByTurnLimit:

    def test_draw_at_max_turns(self, plain_map):
        f = _make_friendly("f1", 5, 5)
        e = _make_enemy("e1", 8, 8)
        gl = GameLoop(plain_map, [f, e])

        # 快进到 MAX_TURNS-1
        for _ in range(MAX_TURNS - 1):
            assert gl.run_turn() is None

        assert gl.get_current_turn() == MAX_TURNS - 1
        result = gl.run_turn()  # 第 MAX_TURNS 回合
        assert result == GameResult.DRAW


# ============================================================================
# HQ 占领胜负
# ============================================================================

class TestHQCaptured:

    def test_hq_captured_event_sets_victory(self, plain_map):
        f = _make_friendly("f1", 5, 5)
        e = _make_enemy("e1", 8, 8)
        gl = GameLoop(plain_map, [f, e])

        # 模拟 #3 广播 HQ_CAPTURED
        event_bus.emit(GameEventType.HQ_CAPTURED, HqCapturedPayload(
            turn=1,
            capturer_id="f1",
            capturer_name="f1",
            capturer_faction=Faction.FRIENDLY.value,
            hq_location=(9, 9),
        ))
        # 下一回合应触发胜利
        result = gl.run_turn()
        assert result == GameResult.VICTORY

    def test_hq_captured_defeat(self, plain_map):
        f = _make_friendly("f1", 5, 5)
        gl = GameLoop(plain_map, [f])

        event_bus.emit(GameEventType.HQ_CAPTURED, HqCapturedPayload(
            turn=1,
            capturer_id="enemy",
            capturer_name="enemy",
            capturer_faction=Faction.ENEMY.value,
            hq_location=(0, 0),
        ))
        result = gl.run_turn()
        assert result == GameResult.DEFEAT


# ============================================================================
# 位置汇报
# ============================================================================

class TestPositionReport:

    def test_friendly_reports_position(self, plain_map):
        """友军单位应在回合中广播 POSITION_REPORT（需调度触发加上敌军存活避免提前胜利）。"""
        f = _make_friendly("f_scout", 5, 5, UnitType.SCOUT)
        e = _make_enemy("e1", 9, 9)
        gl = GameLoop(plain_map, [f, e])

        reports = []

        def capture(payload):
            reports.append(payload)

        event_bus.subscribe(GameEventType.POSITION_REPORT, capture)

        # 跑足够多回合确保至少一次汇报（FogOfWar 随机间隔 3~5 回合）
        for _ in range(20):
            gl.run_turn()
            if gl.get_game_result() is not None:
                break

        assert len(reports) >= 1, f"在 20 回合内应有至少 1 次汇报，实际 {len(reports)}"
        r = reports[0]
        assert r.unit_id == "f_scout"
        assert 0 <= r.reported_x < plain_map.width
        assert 0 <= r.reported_y < plain_map.height


# ============================================================================
# IGameState 查询
# ============================================================================

class TestGameState:

    def test_get_unit_by_id(self, plain_map):
        f = _make_friendly("f1", 5, 5)
        gl = GameLoop(plain_map, [f])
        assert gl.get_unit_by_id("f1") is f
        assert gl.get_unit_by_id("nonexistent") is None

    def test_get_all_units_faction_filter(self, plain_map):
        f1 = _make_friendly("f1", 1, 1)
        f2 = _make_friendly("f2", 2, 2)
        e1 = _make_enemy("e1", 8, 8)
        gl = GameLoop(plain_map, [f1, f2, e1])

        assert len(gl.get_all_units()) == 3
        assert len(gl.get_all_units(Faction.FRIENDLY)) == 2
        assert len(gl.get_all_units(Faction.ENEMY)) == 1

    def test_get_map_and_range_query(self, plain_map):
        gl = GameLoop(plain_map, [_make_friendly("f1", 5, 5)])
        assert gl.get_map() is plain_map
        assert gl.get_range_query() is not None

    def test_duplicate_unit_id_raises(self, plain_map):
        u1 = _make_friendly("dup", 1, 1)
        u2 = _make_enemy("dup", 8, 8)
        with pytest.raises(ValueError, match="重复"):
            GameLoop(plain_map, [u1, u2])
