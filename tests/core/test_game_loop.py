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


# ============================================================================
# CP-2 新增：敌情首次发现追踪
# ============================================================================


class TestEnemySpottedFirstDiscovery:
    """CP-2: _detect_enemy_spotted 仅对首次发现的敌军广播 ENEMY_SPOTTED。"""

    def test_enemy_spotted_only_once_per_enemy(self, plain_map):
        """同一敌军在多回合中只触发一次 ENEMY_SPOTTED。"""
        f = _make_friendly("f_scout", 5, 5, UnitType.SCOUT)
        e = _make_enemy("e1", 6, 5)  # 相邻，在视野内
        gl = GameLoop(plain_map, [f, e])

        spotted_events = []

        def on_spotted(payload):
            spotted_events.append(payload)

        event_bus.subscribe(GameEventType.ENEMY_SPOTTED, on_spotted)

        # 第一回合：应触发首次发现
        gl.run_turn()
        assert len(spotted_events) == 1, f"首次应广播 ENEMY_SPOTTED，实际 {len(spotted_events)}"
        assert spotted_events[0].enemy_type == e.unit_type.value

        # 第二回合：同一敌军不应再次触发
        gl.run_turn()
        assert len(spotted_events) == 1, (
            f"第二回合不应重复广播同一敌军，实际新增 {len(spotted_events) - 1} 条"
        )

    def test_multiple_enemies_spotted_independently(self, plain_map):
        """多个不同敌军各自触发一次首次发现事件。"""
        f = _make_friendly("f_scout", 5, 5, UnitType.SCOUT)
        e1 = _make_enemy("e1", 6, 5)
        e2 = _make_enemy("e2", 5, 6)
        gl = GameLoop(plain_map, [f, e1, e2])

        spotted_ids = []

        def on_spotted(payload):
            spotted_ids.append(payload.reporter_id)  # 用 reporter 追踪

        event_bus.subscribe(GameEventType.ENEMY_SPOTTED, on_spotted)

        gl.run_turn()
        # 两个敌军都在视野内，应各触发一次
        assert len(spotted_ids) == 2, f"两个新敌军应各触发一次，实际 {len(spotted_ids)}"

    def test_new_enemy_spotted_after_previous_discoveries(self, plain_map):
        """已发现敌军不再触发，但新进入视野的敌军仍触发。"""
        f = _make_friendly("f_scout", 5, 5, UnitType.SCOUT)
        e_known = _make_enemy("e_known", 6, 5)

        gl = GameLoop(plain_map, [f, e_known])

        spotted_events = []

        def on_spotted(payload):
            spotted_events.append(payload)

        event_bus.subscribe(GameEventType.ENEMY_SPOTTED, on_spotted)

        # 第一回合：发现 e_known
        gl.run_turn()
        assert len(spotted_events) == 1

        # 第二回合：添加新敌军 e_new，仍在视野内
        e_new = _make_enemy("e_new", 5, 6)
        gl.register_unit(e_new)
        gl.run_turn()
        # 应只触发新敌军的发现
        assert len(spotted_events) == 2, f"新敌军应触发事件，实际新增 {len(spotted_events) - 1}"
        assert spotted_events[-1].enemy_type == e_new.unit_type.value


# ============================================================================
# CP-2 新增：动态单位注册
# ============================================================================


class TestRegisterUnit:
    """CP-2: GameLoop.register_unit / unregister_unit。"""

    def test_register_unit_adds_to_game_loop(self, plain_map):
        """注册后单位出现在 get_all_units 中且放置到地图。"""
        f = _make_friendly("f1", 5, 5)
        gl = GameLoop(plain_map, [f])

        new_unit = _make_friendly("f2", 7, 7)
        result = gl.register_unit(new_unit)

        assert result is True
        assert gl.get_unit_by_id("f2") is new_unit
        assert new_unit in gl.get_all_units()
        assert new_unit in plain_map.get_units_at(new_unit.position)

    def test_register_unit_duplicate_id_raises(self, plain_map):
        """重复 unit_id 注册应抛 ValueError。"""
        f = _make_friendly("f1", 5, 5)
        gl = GameLoop(plain_map, [f])

        dup = _make_enemy("f1", 8, 8)
        with pytest.raises(ValueError, match="重复"):
            gl.register_unit(dup)

    def test_register_unit_init_fog_schedule(self, plain_map):
        """注册友军单位时自动初始化汇报调度。"""
        e = _make_enemy("e1", 8, 8)  # 需要敌军存活避免提前胜利
        gl = GameLoop(plain_map, [e])

        f_new = _make_friendly("f_new", 5, 5, UnitType.SCOUT)
        gl.register_unit(f_new)

        # 跑足够多回合，验证新单位会汇报位置
        reports = []

        def on_report(payload):
            if payload.unit_id == "f_new":
                reports.append(payload)

        event_bus.subscribe(GameEventType.POSITION_REPORT, on_report)

        for _ in range(20):
            gl.run_turn()
            if gl.get_game_result() is not None:
                break
            if reports:
                break

        assert len(reports) >= 1, f"新注册的友军应在 20 回合内至少汇报一次，实际 {len(reports)}"

    def test_unregister_unit_removes_from_game_loop(self, plain_map):
        """注销后单位从注册表和地图中移除。"""
        f1 = _make_friendly("f1", 5, 5)
        f2 = _make_friendly("f2", 7, 7)
        e = _make_enemy("e1", 8, 8)
        gl = GameLoop(plain_map, [f1, f2, e])

        removed = gl.unregister_unit("f2")
        assert removed is not None
        assert removed.unit_id == "f2"
        assert gl.get_unit_by_id("f2") is None
        assert f2 not in gl.get_all_units()
        assert plain_map.get_units_at(Coordinate(7, 7)) == []

    def test_unregister_nonexistent_returns_none(self, plain_map):
        """注销不存在的单位返回 None。"""
        gl = GameLoop(plain_map, [_make_friendly("f1", 5, 5)])
        assert gl.unregister_unit("no_such_unit") is None
