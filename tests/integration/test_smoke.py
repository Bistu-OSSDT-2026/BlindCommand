"""
集成冒烟测试 — Checkpoint 1 验收标准
=====================================
验证各层组装后可以跑通：地图→单位→战斗→事件广播。

三个测试分别覆盖：
    S1 — 全组件初始化：加载地形 + 创建双方单位 + 组装 GameLoop + BattleSystem
    S2 — 回合推进：运行 1 回合 → TURN_START / TURN_END / POSITION_REPORT 事件触发
    S3 — 战斗结算：相邻敌对单位 → 自动战斗 → BATTLE_RESULT / UNIT_KILLED 事件触发

约束：测试中同时 import src.core 和 src.battle（集成测试允许跨层），
      但被测模块本身仍遵守三层隔离规则。
"""

from __future__ import annotations

import pytest

from src.battle.battle_system import BattleSystem
from src.battle.unit_manager import UnitManager
from src.battle.units import Infantry
from src.core.constants import CommandType, Coordinate, Faction, GameEventType, GameResult, UnitType
from src.core.event_bus import event_bus
from src.core.game_loop import GameLoop
from src.core.map import GameMap

# ============================================================================
# 地形
# ============================================================================

# 5×5 全平原（满足 MAP_MIN_SIZE=10？不满足！改用 10×10）
PLAIN_10X10 = [[0] * 10 for _ in range(10)]


# ============================================================================
# 夹具
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_event_bus():
    """每个测试前后清空全局 EventBus，避免测试间污染。"""
    event_bus.clear_all()
    yield
    event_bus.clear_all()


@pytest.fixture
def game_map() -> GameMap:
    """10×10 全平原地图。"""
    return GameMap(
        terrain=PLAIN_10X10,
        friendly_hq=Coordinate(0, 0),
        enemy_hq=Coordinate(9, 9),
    )


@pytest.fixture
def friendly_infantry() -> Infantry:
    """友军步兵 (5,5)。"""
    return Infantry("f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5))


@pytest.fixture
def enemy_infantry() -> Infantry:
    """敌军步兵 (5,6)——与友军相邻。"""
    return Infantry("e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(5, 6))


# ============================================================================
# S1 — 全组件初始化
# ============================================================================


class TestInitialization:
    """S1: 创建地图 → 创建双方单位 → 组装 GameLoop + BattleSystem → 不报错。"""

    def test_create_map_and_units(self, game_map):
        """加载地形并放置单位后，地图正确反映占用状态。"""
        um = UnitManager(game_map)
        f = um.create_unit(
            UnitType.INFANTRY, "f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5)
        )
        e = um.create_unit(
            UnitType.INFANTRY, "e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(8, 8)
        )

        assert f.is_alive
        assert e.is_alive
        assert f in game_map.get_units_at(Coordinate(5, 5))
        assert e in game_map.get_units_at(Coordinate(8, 8))

    def test_assemble_game_loop_with_battle_system(self, game_map):
        """组装 GameLoop + BattleSystem，验证无异常。"""
        um = UnitManager(game_map)
        f = um.create_unit(
            UnitType.INFANTRY, "f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5)
        )
        e = um.create_unit(
            UnitType.INFANTRY, "e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(8, 8)
        )

        units = um.get_all_units()
        gl = GameLoop(game_map, units)
        rq = gl.get_range_query()
        bs = BattleSystem(unit_manager=um, range_query=rq, game_map=game_map, seed=42)

        assert gl.get_current_turn() == 0
        assert gl.get_game_result() is None
        assert len(gl.get_all_units()) == 2
        assert bs is not None

    def test_combat_resolver_hook_wiring(self, game_map):
        """combat_resolver 钩子被 GameLoop 正确调用（阶段 5）。"""
        um = UnitManager(game_map)
        f = um.create_unit(
            UnitType.INFANTRY, "f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5)
        )
        e = um.create_unit(
            UnitType.INFANTRY, "e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(8, 8)
        )
        units = um.get_all_units()
        gl = GameLoop(game_map, units)
        rq = gl.get_range_query()
        bs = BattleSystem(unit_manager=um, range_query=rq, game_map=game_map, seed=42)

        resolver_calls = []

        def combat_resolver(state):
            resolver_calls.append(1)
            bs.process_all_battles(state.get_current_turn())

        # 重新构造 GameLoop 以注入钩子（或手动调用 run_turn 前替换）
        gl2 = GameLoop(
            game_map, units,
            combat_resolver=combat_resolver,
        )
        gl2.run_turn()
        # combat_resolver 钩子在阶段 5 被调用
        assert len(resolver_calls) == 1


# ============================================================================
# S2 — 回合推进与事件广播
# ============================================================================


class TestTurnEvents:
    """S2: 运行 1 回合，TURN_START / TURN_END / POSITION_REPORT 至少各触发一次。"""

    def test_turn_start_and_end_emitted(self, game_map):
        """运行 1 回合后 TURN_START 和 TURN_END 各被 emit 一次。"""
        f = Infantry("f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5))
        e = Infantry("e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(8, 8))
        game_map.place_unit(f, Coordinate(5, 5))
        game_map.place_unit(e, Coordinate(8, 8))

        gl = GameLoop(game_map, [f, e])

        start_count = [0]
        end_count = [0]

        def on_start(_):
            start_count[0] += 1

        def on_end(_):
            end_count[0] += 1

        event_bus.subscribe(GameEventType.TURN_START, on_start)
        event_bus.subscribe(GameEventType.TURN_END, on_end)

        gl.run_turn()

        assert start_count[0] == 1
        assert end_count[0] == 1

    def test_position_report_emitted(self, game_map):
        """友军单位在足够多回合后触发 POSITION_REPORT 事件。"""
        f = Infantry("f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5))
        # 需要一个敌军存活以避免提前胜利
        e = Infantry("e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(9, 9))
        game_map.place_unit(f, Coordinate(5, 5))
        game_map.place_unit(e, Coordinate(9, 9))

        gl = GameLoop(game_map, [f, e])

        reports = []

        def on_report(payload):
            reports.append(payload)

        event_bus.subscribe(GameEventType.POSITION_REPORT, on_report)

        # 友军汇报间隔 3~5 回合，跑 20 回合确保至少触发一次
        for _ in range(20):
            gl.run_turn()
            if gl.get_game_result() is not None:
                break

        assert len(reports) >= 1, (
            f"20 回合内应至少有 1 次位置汇报，实际 {len(reports)}"
        )

    def test_no_game_over_with_both_factions_alive(self, game_map):
        """双方都有存活单位时，run_turn 返回 None（游戏继续）。"""
        f = Infantry("f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5))
        e = Infantry("e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(8, 8))
        game_map.place_unit(f, Coordinate(5, 5))
        game_map.place_unit(e, Coordinate(8, 8))

        gl = GameLoop(game_map, [f, e])
        result = gl.run_turn()
        assert result is None


# ============================================================================
# S3 — 战斗结算
# ============================================================================


class TestBattleResolution:
    """S3: 相邻敌对单位 → 自动战斗 → BATTLE_RESULT / UNIT_KILLED 事件触发。"""

    @staticmethod
    def _make_combat_resolver(bs: BattleSystem):
        """创建 adapter：BattleSystem.process_all_battles → IGameState hook。"""
        def resolver(state):
            bs.process_all_battles(state.get_current_turn())
        return resolver

    def test_battle_result_event_emitted(self, game_map):
        """相邻单位触发战斗，BATTLE_RESULT 事件被广播。"""
        um = UnitManager(game_map)
        f = um.create_unit(
            UnitType.INFANTRY, "f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5)
        )
        e = um.create_unit(
            UnitType.INFANTRY, "e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(5, 6)
        )

        units = um.get_all_units()
        gl = GameLoop(game_map, units)
        rq = gl.get_range_query()
        bs = BattleSystem(unit_manager=um, range_query=rq, game_map=game_map, seed=42)

        battle_results = []

        def on_battle(payload):
            battle_results.append(payload)

        event_bus.subscribe(GameEventType.BATTLE_RESULT, on_battle)

        # 重新构造 GameLoop 以注入 combat_resolver
        gl2 = GameLoop(
            game_map, units,
            combat_resolver=self._make_combat_resolver(bs),
        )
        gl2.run_turn()

        assert len(battle_results) >= 1, (
            f"相邻敌对单位应触发至少 1 次战斗，实际 {len(battle_results)}"
        )
        br = battle_results[0]
        assert br.damage_to_defender > 0

    def test_unit_killed_event_on_death(self, game_map):
        """单位被击杀时 UNIT_KILLED 事件被广播。"""
        um = UnitManager(game_map)
        # 骑兵攻击高，容易击杀
        f = um.create_unit(
            UnitType.CAVALRY, "f_cav", "第一骑兵连", Faction.FRIENDLY, Coordinate(5, 5)
        )
        e = um.create_unit(
            UnitType.SCOUT, "e_sct", "敌军侦察兵", Faction.ENEMY, Coordinate(5, 6)
        )
        # Scout: HP=5, Def=1; Cavalry: Atk=4 → raw=3, 两击可杀

        units = um.get_all_units()
        gl = GameLoop(game_map, units)
        rq = gl.get_range_query()
        bs = BattleSystem(unit_manager=um, range_query=rq, game_map=game_map, seed=42)

        killed_units = []

        def on_killed(payload):
            killed_units.append(payload)

        event_bus.subscribe(GameEventType.UNIT_KILLED, on_killed)

        gl2 = GameLoop(
            game_map, units,
            combat_resolver=self._make_combat_resolver(bs),
        )

        # 跑多回合直到击杀发生（骑兵攻4 vs 侦察兵防1 HP5 → raw=3，需2击）
        for _ in range(10):
            result = gl2.run_turn()
            if result is not None:
                break

        assert len(killed_units) >= 1, (
            f"应在 10 回合内至少击杀 1 个单位，实际击杀 {len(killed_units)}"
        )

    def test_game_over_on_total_annihilation(self, game_map):
        """一方全军覆没时触发 GAME_OVER 事件。"""
        um = UnitManager(game_map)
        f = um.create_unit(
            UnitType.CAVALRY, "f_cav", "第一骑兵连", Faction.FRIENDLY, Coordinate(5, 5)
        )
        e = um.create_unit(
            UnitType.SCOUT, "e_sct", "敌军侦察兵", Faction.ENEMY, Coordinate(5, 6)
        )

        units = um.get_all_units()
        gl = GameLoop(game_map, units)
        rq = gl.get_range_query()
        bs = BattleSystem(unit_manager=um, range_query=rq, game_map=game_map, seed=42)

        game_over_payloads = []

        def on_game_over(payload):
            game_over_payloads.append(payload)

        event_bus.subscribe(GameEventType.GAME_OVER, on_game_over)

        gl2 = GameLoop(
            game_map, units,
            combat_resolver=self._make_combat_resolver(bs),
        )

        result = None
        for _ in range(10):
            result = gl2.run_turn()
            if result is not None:
                break

        assert result is not None, "10 回合内游戏应当结束"
        assert len(game_over_payloads) >= 1
        # 骑兵克侦察兵，大概率胜利
        assert game_over_payloads[0].result in (
            GameResult.VICTORY.value,
            GameResult.DEFEAT.value,
        )


# ============================================================================
# CP-2 新增：from_map_file 工厂 + get_fog + 标准集成模板
# ============================================================================


class TestFromMapFileFactory:
    """CP-2: GameLoop.from_map_file() 一键组装 + #5 集成参考。"""

    def test_from_map_file_creates_game_loop(self):
        """从 map_01.json 一键创建 GameLoop，验证单位正确加载。"""
        from pathlib import Path

        from src.core.constants import DEFAULT_MAP_FILE, Faction

        # 使用项目自带的地图文件
        map_path = Path(DEFAULT_MAP_FILE)
        if not map_path.exists():
            pytest.skip(f"地图文件不存在: {map_path}")

        gl = GameLoop.from_map_file(map_path)

        # 验证基本状态
        assert gl.get_current_turn() == 0
        assert gl.get_game_result() is None
        assert gl.get_map() is not None

        # 验证双方单位已加载（map_01.json：5 友军 + 5 敌军）
        all_units = gl.get_all_units()
        friendly = gl.get_all_units(Faction.FRIENDLY)
        enemy = gl.get_all_units(Faction.ENEMY)
        assert len(friendly) == 5, f"友军应为 5，实际 {len(friendly)}"
        assert len(enemy) == 5, f"敌军应为 5，实际 {len(enemy)}"
        assert len(all_units) == 10

        # 验证单位已放置到地图
        for u in friendly:
            assert u in gl.get_map().get_units_at(u.position)

    def test_from_map_file_runs_one_turn(self):
        """CP-2 标准集成模板：加载 → 组装 BattleSystem → 跑 1 回合。"""
        from pathlib import Path

        from src.battle.battle_system import BattleSystem
        from src.battle.unit_manager import UnitManager
        from src.core.constants import DEFAULT_MAP_FILE

        map_path = Path(DEFAULT_MAP_FILE)
        if not map_path.exists():
            pytest.skip(f"地图文件不存在: {map_path}")

        # ── 步骤 1：一键创建 GameLoop ──────────────────────────
        gl = GameLoop.from_map_file(map_path)

        # ── 步骤 2：#3 创建 BattleSystem（需要 UnitManager + 地图） ──
        um = UnitManager(gl.get_map())
        # 注：CP-2 集成时 UnitManager 通过 create_unit() 创建单位，
        # 此处 gl.get_all_units() 返回的是 GameLoop.from_map_file() 预创建的单位，
        # UnitManager 直接接收 BattleSystem 使用其 get_alive_units() 即可
        bs = BattleSystem(
            unit_manager=um,
            range_query=gl.get_range_query(),
            game_map=gl.get_map(),
            seed=42,
        )

        # ── 步骤 3：注入战斗钩子，运行 1 回合 ──────────────────
        events_received = []

        def on_battle(payload):
            events_received.append(("BATTLE", payload))

        def on_turn_start(_):
            events_received.append(("TURN_START", None))

        event_bus.subscribe(GameEventType.BATTLE_RESULT, on_battle)
        event_bus.subscribe(GameEventType.TURN_START, on_turn_start)

        # 重新构造以注入钩子（CP-2 标准模式）
        gl2 = GameLoop(
            game_map=gl.get_map(),
            units=gl.get_all_units(),
            combat_resolver=lambda state: bs.process_all_battles(state.get_current_turn()),
        )
        gl2.run_turn()

        # ── 验证 ───────────────────────────────────────────────
        assert gl2.get_current_turn() == 1
        # TURN_START 必定触发
        assert any(e[0] == "TURN_START" for e in events_received)

    def test_get_fog_available(self):
        """CP-2: get_fog() 返回迷雾管理器供 #4 UI 查询。"""
        from pathlib import Path

        from src.core.constants import DEFAULT_MAP_FILE

        map_path = Path(DEFAULT_MAP_FILE)
        if not map_path.exists():
            pytest.skip(f"地图文件不存在: {map_path}")

        gl = GameLoop.from_map_file(map_path)
        fog = gl.get_fog()

        assert fog is not None

        # #4 UI 的标准查询模式
        friendly_area = fog.get_visible_area(Faction.FRIENDLY)
        assert len(friendly_area) > 0, "友军应有可见区域"

        # 验证友军单位对己方可见
        for u in gl.get_all_units(Faction.FRIENDLY):
            assert fog.is_unit_visible(u, Faction.FRIENDLY) is True


# ============================================================================
# S4 — Sprint 2: Commander + AI 集成
# ============================================================================


class TestCommanderIntegration:
    """S4: 指令系统 + AI 集成冒烟测试。"""

    @staticmethod
    def _make_combat_resolver(bs: BattleSystem):
        """创建 adapter：BattleSystem.process_all_battles → IGameState hook。"""
        def resolver(state):
            bs.process_all_battles(state.get_current_turn())
        return resolver

    def test_commander_move_and_event(self, game_map):
        """通过 Commander 下达 MOVE 指令 → 验证 COMMAND_SENT 事件广播。"""
        from src.battle.commander import Commander

        um = UnitManager(game_map)
        f = um.create_unit(
            UnitType.INFANTRY, "f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5)
        )
        e = um.create_unit(
            UnitType.INFANTRY, "e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(8, 8)
        )

        cmdr = Commander(unit_manager=um, game_map=game_map, seed=42)

        sent_events = []

        def on_command_sent(payload):
            sent_events.append(payload)

        event_bus.subscribe(GameEventType.COMMAND_SENT, on_command_sent)

        result = cmdr.issue_command("f_inf", CommandType.MOVE, {"x": 7, "y": 5})
        assert result is True
        assert len(sent_events) == 1
        assert sent_events[0].target_unit_id == "f_inf"
        assert sent_events[0].command_type == "MOVE"

    def test_commander_with_game_loop_hook(self, game_map):
        """GameLoop 注入 Commander → 回合推进 → COMMAND_ARRIVED 事件触发。"""
        from src.battle.commander import Commander

        um = UnitManager(game_map)
        f = um.create_unit(
            UnitType.INFANTRY, "f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5)
        )
        e = um.create_unit(
            UnitType.INFANTRY, "e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(8, 8)
        )

        cmdr = Commander(unit_manager=um, game_map=game_map, seed=42)
        units = um.get_all_units()

        arrived_events = []

        def on_arrived(payload):
            arrived_events.append(payload)

        event_bus.subscribe(GameEventType.COMMAND_ARRIVED, on_arrived)

        # 下达 MOVE 指令
        cmdr.issue_command("f_inf", CommandType.MOVE, {"x": 6, "y": 5})

        gl = GameLoop(game_map, units, commander=cmdr)
        # 跑足够多回合确保指令到达（延迟 1~3 回合）
        for _ in range(10):
            result = gl.run_turn()
            if result is not None:
                break

        assert len(arrived_events) >= 1, (
            f"10 回合内应有至少 1 条 COMMAND_ARRIVED，实际 {len(arrived_events)}"
        )

    def test_ai_integration_with_game_loop(self, game_map):
        """GameLoop 注入 EnemyAI → AI 自动为敌军下达指令。"""
        from src.battle.ai import EnemyAI
        from src.battle.commander import Commander

        um = UnitManager(game_map)
        f = um.create_unit(
            UnitType.INFANTRY, "f_inf", "第一步兵连", Faction.FRIENDLY, Coordinate(5, 5)
        )
        e = um.create_unit(
            UnitType.INFANTRY, "e_inf", "敌军步兵A", Faction.ENEMY, Coordinate(8, 8)
        )

        cmdr = Commander(unit_manager=um, game_map=game_map, seed=42)
        units = um.get_all_units()
        gl = GameLoop(game_map, units, commander=cmdr)
        rq = gl.get_range_query()

        ai = EnemyAI(
            unit_manager=um,
            range_query=rq,
            game_map=game_map,
            commander=cmdr,
            seed=42,
        )

        sent_events = []

        def on_sent(payload):
            sent_events.append(payload)

        event_bus.subscribe(GameEventType.COMMAND_SENT, on_sent)

        # 重新构造 GameLoop，注入 ai_decider
        gl2 = GameLoop(game_map, units, commander=cmdr, ai_decider=ai.decide_all)

        for _ in range(5):
            result = gl2.run_turn()
            if result is not None:
                break

        # AI 应为敌军单位下达了指令
        ai_commands = [e for e in sent_events if e.target_unit_id == "e_inf"]
        assert len(ai_commands) >= 1, (
            f"5 回合内 AI 应为敌军下达至少 1 条指令，实际 {len(ai_commands)}"
        )
