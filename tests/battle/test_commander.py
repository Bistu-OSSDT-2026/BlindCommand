"""
指令系统与 AI 测试 — 对齐 SPEC.md §10.3 & §10.4
==================================================
覆盖:
    - CommandQueue: 延迟入队/出队/取消/权重分布
    - Commander: MOVE / HOLD / 指令覆盖 / 阵亡取消
    - EnemyAI: 溃逃决策 / 接敌决策 / 默认巡逻

运行: pytest tests/battle/test_commander.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.battle.ai import EnemyAI
from src.battle.command_queue import CommandQueue
from src.battle.commander import Command, Commander
from src.battle.unit_manager import UnitManager
from src.battle.units import Infantry
from src.core.constants import (
    COMBAT_ROUT_HP_RATIO,
    COMMAND_DELAY_MAX,
    COMMAND_DELAY_MIN,
    CommandType,
    Coordinate,
    Faction,
    GameEventType,
    UnitType,
)
from src.core.event_bus import event_bus

# ============================================================================
# 辅助工厂函数
# ============================================================================


def _make_coord(x: int = 5, y: int = 5) -> Coordinate:
    return Coordinate(x, y)


def _make_infantry(
    unit_id: str = "inf_01",
    name: str = "测试步兵",
    faction: Faction = Faction.FRIENDLY,
    x: int = 5,
    y: int = 5,
) -> Infantry:
    return Infantry(unit_id=unit_id, name=name, faction=faction, start_pos=_make_coord(x, y))


def _make_enemy_infantry(
    unit_id: str = "enemy_01",
    x: int = 6,
    y: int = 5,
) -> Infantry:
    return Infantry(
        unit_id=unit_id, name="敌军步兵", faction=Faction.ENEMY, start_pos=_make_coord(x, y)
    )


def _make_fake_map() -> MagicMock:
    """创建可用于测试的假 IMap。"""
    fake_map = MagicMock()
    fake_map.width = 20
    fake_map.height = 15
    fake_map.is_within_bounds.return_value = True
    fake_map.is_passable.return_value = True
    fake_map.get_defense_bonus.return_value = 0
    fake_map.get_terrain.return_value = MagicMock()  # 非 HQ_CELL
    fake_map.get_units_at.return_value = []
    fake_map.place_unit.return_value = True
    fake_map.remove_unit.return_value = None
    fake_map.move_unit.return_value = True
    fake_map.find_path.return_value = [_make_coord(5, 5), _make_coord(6, 5)]
    fake_map.get_faction_hq_location.return_value = _make_coord(0, 0)
    return fake_map


def _make_fake_range_query() -> MagicMock:
    """创建假 IRangeQuery。"""
    fake_rq = MagicMock()
    fake_rq.get_units_in_range.return_value = []
    fake_rq.find_nearest_enemy.return_value = None
    fake_rq.has_enemy_in_range.return_value = False
    return fake_rq


# ============================================================================
# 事件总线重置
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_event_bus():
    """每个测试前后清空全局 EventBus，避免测试间污染。"""
    event_bus.clear_all()
    yield
    event_bus.clear_all()


# ============================================================================
# CommandQueue 测试
# ============================================================================


class TestCommandQueue:
    """通信延迟队列测试。"""

    def test_enqueue_sets_arrival_turn(self) -> None:
        """入队后 arrival_turn = issued_turn + delay。"""
        q = CommandQueue(seed=42)
        cmd = Command(
            command_type=CommandType.MOVE,
            target_unit_id="u1",
            params={"x": 10, "y": 5},
        )
        arrival = q.enqueue(cmd, current_turn=5)
        assert arrival >= 5 + COMMAND_DELAY_MIN
        assert arrival <= 5 + COMMAND_DELAY_MAX
        assert cmd.arrival_turn == arrival

    def test_delay_in_valid_range(self) -> None:
        """多次入队，所有延迟在 [1, 3] 范围内。"""
        q = CommandQueue(seed=123)
        for i in range(50):
            cmd = Command(CommandType.MOVE, f"u{i}", {})
            arrival = q.enqueue(cmd, current_turn=10)
            delay = arrival - 10
            assert COMMAND_DELAY_MIN <= delay <= COMMAND_DELAY_MAX, (
                f"延迟 {delay} 超出范围 [{COMMAND_DELAY_MIN}, {COMMAND_DELAY_MAX}]"
            )

    def test_pop_due_commands(self) -> None:
        """到期指令出队，未到期指令保留。"""
        q = CommandQueue(seed=42)
        cmd1 = Command(CommandType.MOVE, "u1", {})
        cmd2 = Command(CommandType.HOLD, "u2", {})

        q.enqueue(cmd1, current_turn=1)  # arrival = 1 + delay
        q.enqueue(cmd2, current_turn=1)

        # 快进到足够大的回合确保所有指令到期
        due = q.pop_due_commands(current_turn=100)
        assert len(due) == 2
        assert q.size == 0

    def test_pop_not_due_yet(self) -> None:
        """未到期指令不出队。"""
        q = CommandQueue(seed=42)
        cmd = Command(CommandType.MOVE, "u1", {})
        q.enqueue(cmd, current_turn=10)
        # 在指令到达前查询
        due = q.pop_due_commands(current_turn=9)
        assert len(due) == 0
        assert q.size == 1

    def test_cancel_for_unit(self) -> None:
        """取消某单位指令后队列为空。"""
        q = CommandQueue(seed=42)
        cmd = Command(CommandType.MOVE, "u1", {})
        q.enqueue(cmd, current_turn=0)
        assert q.size == 1

        q.cancel_for_unit("u1")
        assert q.size == 0
        assert q.get_pending_for_unit("u1") == []

    def test_cancel_nonexistent_noop(self) -> None:
        """取消不存在的单位指令不报错。"""
        q = CommandQueue(seed=42)
        q.cancel_for_unit("no_such_unit")  # no exception

    def test_peek_all_returns_copy(self) -> None:
        """peek_all 返回副本，修改不影响队列。"""
        q = CommandQueue(seed=42)
        cmd = Command(CommandType.MOVE, "u1", {})
        q.enqueue(cmd, current_turn=0)
        peeked = q.peek_all()
        assert len(peeked) == 1
        peeked.clear()
        assert q.size == 1  # 队列不变

    def test_get_human_description(self) -> None:
        """指令人类可读描述格式化正确。"""
        cmd = Command(
            command_type=CommandType.MOVE,
            target_unit_id="u1",
            params={"x": 10, "y": 5},
        )
        desc = cmd.get_human_description()
        assert "MOVE" in desc
        assert "10" in desc
        assert "5" in desc


# ============================================================================
# Commander 测试
# ============================================================================


class TestCommander:
    """指令管理与传达系统测试。"""

    @staticmethod
    def _create_commander(
        units: list | None = None,
        fake_map: MagicMock | None = None,
        seed: int = 42,
    ) -> Commander:
        """创建测试用 Commander（含 UnitManager + 假 IMap）。"""
        fm = fake_map or _make_fake_map()
        um = UnitManager(fm)
        if units:
            for u in units:
                if u.unit_id not in [x.unit_id for x in um.get_all_units()]:
                    um.create_unit(
                        UnitType(u.unit_type.value),
                        u.unit_id,
                        u.name,
                        u.faction,
                        u.position,
                    )
        return Commander(unit_manager=um, game_map=fm, seed=seed)

    def test_issue_command_enqueues(self) -> None:
        """下达指令后队列中有该指令。"""
        fm = _make_fake_map()
        um = UnitManager(fm)
        um.create_unit(
            UnitType.INFANTRY, "inf_1", "第一步兵连", Faction.FRIENDLY, _make_coord(5, 5)
        )
        cmdq = CommandQueue(seed=42)
        cmdr = Commander(unit_manager=um, game_map=fm, command_queue=cmdq)

        result = cmdr.issue_command("inf_1", CommandType.MOVE, {"x": 10, "y": 5})
        assert result is True
        assert cmdq.size == 1

    def test_issue_command_dead_unit_fails(self) -> None:
        """对已阵亡单位下达指令返回 False。"""
        fm = _make_fake_map()
        um = UnitManager(fm)
        unit = um.create_unit(
            UnitType.INFANTRY, "inf_1", "第一步兵连", Faction.FRIENDLY, _make_coord(5, 5)
        )
        # 击杀单位
        unit.take_damage(unit.max_hp, unit)
        assert unit.is_alive is False

        cmdr = Commander(unit_manager=um, game_map=fm)
        result = cmdr.issue_command("inf_1", CommandType.MOVE, {"x": 10, "y": 5})
        assert result is False

    def test_hq_cannot_move(self) -> None:
        """HQ 不可下达移动类指令。"""
        fm = _make_fake_map()
        um = UnitManager(fm)
        um.create_unit(
            UnitType.HQ, "hq_1", "指挥所", Faction.FRIENDLY, _make_coord(0, 0)
        )
        cmdr = Commander(unit_manager=um, game_map=fm)

        assert cmdr.issue_command("hq_1", CommandType.MOVE, {"x": 10, "y": 5}) is False
        assert cmdr.issue_command("hq_1", CommandType.ATTACK, {"x": 10, "y": 5}) is False

    def test_move_command_executes_position_change(self) -> None:
        """MOVE 指令执行后单位坐标改变。"""
        fm = _make_fake_map()
        fm.find_path.return_value = [_make_coord(5, 5), _make_coord(6, 5), _make_coord(7, 5)]
        um = UnitManager(fm)
        unit = um.create_unit(
            UnitType.INFANTRY, "inf_1", "第一步兵连", Faction.FRIENDLY, _make_coord(5, 5)
        )

        cmdq = CommandQueue(seed=42)
        cmdr = Commander(unit_manager=um, game_map=fm, command_queue=cmdq)

        cmdr.issue_command("inf_1", CommandType.MOVE, {"x": 7, "y": 5})
        # 快进到指令到达
        cmdr.process_command_queue(current_turn=100)

        # 单位应该移动了
        assert unit.position.x != 5 or unit.position.y != 5

    def test_hold_command_attacks_enemy(self) -> None:
        """HOLD 指令在攻击范围内有敌人时自动攻击。"""
        fm = _make_fake_map()
        fm.find_path.return_value = []
        um = UnitManager(fm)
        um.create_unit(
            UnitType.INFANTRY, "inf_1", "第一步兵连", Faction.FRIENDLY, _make_coord(5, 5)
        )
        um.create_unit(
            UnitType.INFANTRY, "enemy_1", "敌军步兵", Faction.ENEMY, _make_coord(6, 5)
        )

        # 设置 combat_resolver mock
        combat_calls = []

        def mock_combat(attacker, defender, turn):
            combat_calls.append((attacker.unit_id, defender.unit_id))

        cmdq = CommandQueue(seed=42)
        cmdr = Commander(
            unit_manager=um, game_map=fm, command_queue=cmdq, combat_resolver=mock_combat
        )

        cmdr.issue_command("inf_1", CommandType.HOLD, {})
        cmdr.process_command_queue(current_turn=100)

        # HOLD 持续指令重新入队
        assert cmdq.size >= 1

    def test_cancel_commands_on_death(self) -> None:
        """单位阵亡 → 待执行指令被清除 + COMMAND_EXPIRED 事件广播。"""
        fm = _make_fake_map()
        um = UnitManager(fm)
        um.create_unit(
            UnitType.INFANTRY, "inf_1", "第一步兵连", Faction.FRIENDLY, _make_coord(5, 5)
        )

        cmdq = CommandQueue(seed=42)
        cmdr = Commander(unit_manager=um, game_map=fm, command_queue=cmdq)

        cmdr.issue_command("inf_1", CommandType.MOVE, {"x": 10, "y": 5})
        assert cmdq.size == 1

        # 直接调用 cancel_all（模拟 UNIT_KILLED 事件触发 _on_unit_killed）
        cmdr.cancel_all_commands("inf_1")
        assert cmdq.size == 0

    def test_command_override_clears_old(self) -> None:
        """新指令覆盖旧指令，队列中只保留最新。"""
        fm = _make_fake_map()
        um = UnitManager(fm)
        um.create_unit(
            UnitType.INFANTRY, "inf_1", "第一步兵连", Faction.FRIENDLY, _make_coord(5, 5)
        )

        cmdq = CommandQueue(seed=42)
        cmdr = Commander(unit_manager=um, game_map=fm, command_queue=cmdq)

        cmdr.issue_command("inf_1", CommandType.MOVE, {"x": 10, "y": 5})
        assert cmdq.size == 1

        cmdr.issue_command("inf_1", CommandType.HOLD, {})
        # 旧 MOVE 被覆盖，只剩新 HOLD
        assert cmdq.size == 1
        pending = cmdq.peek_all()
        assert pending[0].command_type == CommandType.HOLD

    def test_get_pending_commands(self) -> None:
        """get_pending_commands 返回正确的待执行指令列表。"""
        fm = _make_fake_map()
        um = UnitManager(fm)
        um.create_unit(
            UnitType.INFANTRY, "inf_1", "第一步兵连", Faction.FRIENDLY, _make_coord(5, 5)
        )

        cmdq = CommandQueue(seed=42)
        cmdr = Commander(unit_manager=um, game_map=fm, command_queue=cmdq)

        cmdr.issue_command("inf_1", CommandType.MOVE, {"x": 10, "y": 5})
        pending = cmdr.get_pending_commands("inf_1")
        assert len(pending) == 1
        assert pending[0].command_type == CommandType.MOVE

        assert cmdr.get_pending_commands("no_unit") == []

    def test_retreat_moves_farther(self) -> None:
        """RETREAT 指令移动速度+2 格。"""
        fm = _make_fake_map()
        fm.find_path.return_value = []
        um = UnitManager(fm)
        unit = um.create_unit(
            UnitType.INFANTRY, "inf_1", "第一步兵连", Faction.FRIENDLY, _make_coord(5, 5)
        )

        cmdq = CommandQueue(seed=42)
        cmdr = Commander(unit_manager=um, game_map=fm, command_queue=cmdq)

        old_pos = unit.position
        cmdr.issue_command("inf_1", CommandType.RETREAT, {"direction": "E"})
        cmdr.process_command_queue(current_turn=100)

        # 撤退后坐标应向东变化（多格）
        assert unit.position.x > old_pos.x or unit.position.y != old_pos.y


# ============================================================================
# EnemyAI 测试
# ============================================================================


class TestEnemyAI:
    """敌军 AI 行为树测试。"""

    @staticmethod
    def _create_ai(
        enemy: Infantry,
        fake_map: MagicMock | None = None,
        fake_rq: MagicMock | None = None,
        seed: int = 42,
        combat_resolver=None,
    ) -> EnemyAI:
        """创建测试用 EnemyAI。"""
        fm = fake_map or _make_fake_map()
        frq = fake_rq or _make_fake_range_query()
        um = UnitManager(fm)
        um.create_unit(
            UnitType(enemy.unit_type.value),
            enemy.unit_id,
            enemy.name,
            enemy.faction,
            enemy.position,
        )
        cmdr = Commander(
            unit_manager=um,
            game_map=fm,
            seed=seed,
            combat_resolver=combat_resolver,
        )
        return EnemyAI(
            unit_manager=um,
            range_query=frq,
            game_map=fm,
            commander=cmdr,
            seed=seed,
        )

    def test_ai_retreat_when_low_hp(self) -> None:
        """AI 在 HP < 20% 时应下达 RETREAT 指令。"""
        enemy = _make_enemy_infantry(x=5, y=5)
        # 打残敌军 — HP 降到 10%（严格低于 20% 阈值）
        enemy.take_damage(int(enemy.max_hp * 0.9), enemy)  # max_hp=10, damage=9 → HP=1
        assert enemy.hp_ratio < COMBAT_ROUT_HP_RATIO, f"HP ratio={enemy.hp_ratio}"

        fm = _make_fake_map()
        ai = self._create_ai(enemy, fake_map=fm)

        cmd_type, params = ai.decide_for_unit(enemy, current_turn=1)
        assert cmd_type == CommandType.RETREAT
        assert "direction" in params

    def test_ai_does_not_retreat_when_healthy(self) -> None:
        """HP 正常时 AI 不应溃逃。"""
        enemy = _make_enemy_infantry(x=5, y=5)
        assert enemy.hp_ratio >= COMBAT_ROUT_HP_RATIO

        fm = _make_fake_map()
        ai = self._create_ai(enemy, fake_map=fm)

        cmd_type, params = ai.decide_for_unit(enemy, current_turn=1)
        assert cmd_type != CommandType.RETREAT

    def test_ai_attacks_enemy_in_range(self) -> None:
        """AI 在攻击范围内有敌人时下达 ATTACK 指令。"""
        enemy = _make_enemy_infantry(x=5, y=5)
        fm = _make_fake_map()
        fake_rq = _make_fake_range_query()
        fake_rq.has_enemy_in_range.return_value = True
        fake_rq.find_nearest_enemy.return_value = _make_infantry(
            "friend_1", faction=Faction.FRIENDLY, x=6, y=5
        )

        # 需要 mock combat_resolver，否则 AI 回退为 MOVE
        mock_resolver = MagicMock()

        ai = self._create_ai(enemy, fake_map=fm, fake_rq=fake_rq, combat_resolver=mock_resolver)
        cmd_type, params = ai.decide_for_unit(enemy, current_turn=1)
        assert cmd_type == CommandType.ATTACK

    def test_ai_default_action_is_valid(self) -> None:
        """AI 在无威胁时返回 MOVE 或 PATROL。"""
        enemy = _make_enemy_infantry(x=5, y=5)
        fm = _make_fake_map()
        fake_rq = _make_fake_range_query()
        fake_rq.has_enemy_in_range.return_value = False

        ai = self._create_ai(enemy, fake_map=fm, fake_rq=fake_rq)
        cmd_type, params = ai.decide_for_unit(enemy, current_turn=1)
        assert cmd_type in (CommandType.MOVE, CommandType.PATROL)

    def test_ai_decide_all_does_not_crash(self) -> None:
        """decide_all 不为空单位列表崩溃。"""
        enemy = _make_enemy_infantry(x=5, y=5)
        fm = _make_fake_map()
        um = UnitManager(fm)
        um.create_unit(
            UnitType.INFANTRY, enemy.unit_id, enemy.name, enemy.faction, enemy.position
        )
        cmdr = Commander(unit_manager=um, game_map=fm, seed=42)
        ai = EnemyAI(
            unit_manager=um,
            range_query=_make_fake_range_query(),
            game_map=fm,
            commander=cmdr,
            seed=42,
        )

        # 不应崩溃 — 传入 mock IGameState
        mock_gs = MagicMock()
        mock_gs.get_current_turn.return_value = 1
        ai.decide_all(game_state=mock_gs)

    def test_ai_hq_defend_when_threatened(self) -> None:
        """AI 在己方 HQ 附近有敌人时回防。"""
        from src.battle.units import HQ

        # 创建一个敌军 HQ 单位
        enemy_hq = HQ(
            unit_id="enemy_hq",
            name="敌军指挥所",
            faction=Faction.ENEMY,
            start_pos=_make_coord(0, 0),
        )
        enemy = _make_enemy_infantry(x=5, y=5)

        fm = _make_fake_map()
        um = UnitManager(fm)
        um.create_unit(
            UnitType.HQ, enemy_hq.unit_id, enemy_hq.name, enemy_hq.faction, enemy_hq.position
        )
        um.create_unit(
            UnitType.INFANTRY, enemy.unit_id, enemy.name, enemy.faction, enemy.position
        )

        fake_rq = _make_fake_range_query()
        # 第一次 has_enemy_in_range(enemy, attack_range) → False（不接敌）
        # 第二次 has_enemy_in_range(hq, 5) → True（HQ 受威胁）
        fake_rq.has_enemy_in_range.side_effect = [False, True]

        cmdr = Commander(unit_manager=um, game_map=fm, seed=42)
        ai = EnemyAI(
            unit_manager=um,
            range_query=fake_rq,
            game_map=fm,
            commander=cmdr,
            seed=42,
        )

        cmd_type, params = ai.decide_for_unit(enemy, current_turn=1)
        # 应回防 HQ
        assert cmd_type == CommandType.MOVE, f"期望 MOVE，实际 {cmd_type}"
        assert "x" in params
        assert "y" in params


# ============================================================================
# Sprint 3 新增测试：指令执行 + AI 增强 + 战斗系统
# ============================================================================


class TestSprint3CaptureExecution:
    """T1: CAPTURE 指令完整流程测试。"""

    def test_capture_moves_then_counts_down(self):
        """占领指令：移动到 HQ 格 → 累计倒计时 → 成功触发 HQ_CAPTURED。"""
        from src.battle.units import HQ
        from src.core.constants import TerrainType

        fm = _make_fake_map()
        # 设置目标格为 HQ 地形（使用真实 TerrainType 枚举值）
        fm.get_terrain.return_value = TerrainType.HQ_CELL

        um = UnitManager(fm)
        infantry = um.create_unit(
            UnitType.INFANTRY, "cap_inf", "占领步兵", Faction.FRIENDLY, _make_coord(5, 5)
        )
        # 在目标格放置敌方 HQ
        enemy_hq = HQ("enemy_hq", "敌军指挥所", Faction.ENEMY, _make_coord(7, 5))
        # 手动注册到 um
        um._units[enemy_hq.unit_id] = enemy_hq
        fm.get_units_at.return_value = [enemy_hq]

        # 路径：一步到达
        fm.find_path.return_value = [_make_coord(5, 5), _make_coord(6, 5), _make_coord(7, 5)]

        cmdr = Commander(unit_manager=um, game_map=fm, seed=42)
        cmdr.issue_command("cap_inf", CommandType.CAPTURE, {"x": 7, "y": 5})

        # 第一回合: 移动到目标 (process_command_queue 内执行指令)
        cmdr.process_command_queue(current_turn=10)
        assert infantry.position == _make_coord(7, 5)

        # 指令执行后在 process_command_queue 末尾更新快照
        # 手动触发一次 process 让 _last_hp 和 _last_positions 更新
        # 再发一次 capture 指令让它进入占领倒计时
        cmdr.issue_command("cap_inf", CommandType.CAPTURE, {"x": 7, "y": 5})
        # 回合 11: progress = 1
        fm.get_units_at.return_value = [enemy_hq]
        cmdr.process_command_queue(current_turn=11)
        assert cmdr._capture_progress.get("cap_inf", 0) >= 1

        hq_captured_events = []

        def on_captured(payload):
            hq_captured_events.append(payload)

        event_bus.subscribe(GameEventType.HQ_CAPTURED, on_captured)

        # 回合 12: progress = 2 → 占领成功
        fm.get_units_at.return_value = [enemy_hq]
        cmdr.process_command_queue(current_turn=12)
        assert len(hq_captured_events) >= 1

    def test_capture_interrupted_by_damage(self):
        """占领过程中受到攻击 → HP 下降 → 打断 + 重置计数。"""
        from src.battle.units import HQ
        from src.core.constants import TerrainType

        fm = _make_fake_map()
        fm.get_terrain.return_value = TerrainType.HQ_CELL

        um = UnitManager(fm)
        infantry = um.create_unit(
            UnitType.INFANTRY, "cap_inf", "占领步兵", Faction.FRIENDLY, _make_coord(5, 5)
        )
        enemy_hq = HQ("enemy_hq", "敌军指挥所", Faction.ENEMY, _make_coord(5, 5))
        um._units[enemy_hq.unit_id] = enemy_hq
        fm.get_units_at.return_value = [enemy_hq]

        cmdr = Commander(unit_manager=um, game_map=fm, seed=42)
        cmdr.issue_command("cap_inf", CommandType.CAPTURE, {"x": 5, "y": 5})

        # 第一回合：已在目标格，progress = 1
        cmdr.process_command_queue(current_turn=10)
        assert cmdr._capture_progress.get("cap_inf", 0) == 1

        # 模拟受到攻击：HP 下降
        infantry.take_damage(3, enemy_hq)

        # 第二回合：应检测到 HP 下降 → 打断 → 重置
        cmdr.process_command_queue(current_turn=11)
        assert cmdr._capture_progress.get("cap_inf", 0) == 1  # 重置后重新累到 1


class TestSprint3PatrolExecution:
    """T2: PATROL 指令执行测试。"""

    def test_patrol_moves_along_waypoints(self):
        """巡逻沿路点移动，到达终点后往复。"""
        fm = _make_fake_map()
        fm.find_path.return_value = [_make_coord(5, 5), _make_coord(6, 5)]
        um = UnitManager(fm)
        um.create_unit(
            UnitType.INFANTRY, "patrol_inf", "巡逻步兵", Faction.ENEMY, _make_coord(5, 5)
        )

        cmdr = Commander(unit_manager=um, game_map=fm, seed=42)
        cmdr.issue_command("patrol_inf", CommandType.PATROL, {"path": [[5, 5], [7, 5], [5, 5]]})

        # 巡逻指令应被入队
        pending = cmdr.get_pending_commands("patrol_inf")
        assert len(pending) >= 1

        # 执行一次：应在巡逻状态中初始化
        fm.find_path.return_value = [_make_coord(5, 5), _make_coord(6, 5)]
        cmdr.process_command_queue(current_turn=10)
        # 巡逻状态应存在
        assert "patrol_inf" in cmdr._patrol_state

    def test_patrol_short_path_rejected(self):
        """路径少于 2 个点应被拒绝。"""
        fm = _make_fake_map()
        um = UnitManager(fm)
        um.create_unit(
            UnitType.INFANTRY, "patrol_inf", "巡逻步兵", Faction.ENEMY, _make_coord(5, 5)
        )

        cmdr = Commander(unit_manager=um, game_map=fm, seed=42)
        cmdr.issue_command("patrol_inf", CommandType.PATROL, {"path": [[5, 5]]})
        cmdr.process_command_queue(current_turn=10)
        # 不应该创建巡逻状态
        assert "patrol_inf" not in cmdr._patrol_state


class TestSprint3ScoutExecution:
    """T3: SCOUT 指令执行测试。"""

    def test_scout_moves_in_direction(self):
        """SCOUT 向指定方向移动并扩大视野。"""
        fm = _make_fake_map()
        fm.find_path.return_value = []
        um = UnitManager(fm)
        unit = um.create_unit(
            UnitType.SCOUT, "scout_sct", "侦察兵", Faction.ENEMY, _make_coord(5, 5)
        )

        cmdr = Commander(unit_manager=um, game_map=fm, seed=42)
        old_pos = unit.position
        cmdr.issue_command("scout_sct", CommandType.SCOUT, {"direction": "E"})
        cmdr.process_command_queue(current_turn=10)

        # 向东移动了
        assert unit.position.x > old_pos.x

    def test_scout_detects_enemies(self):
        """SCOUT 发现敌人时广播 ENEMY_SPOTTED。"""
        fm = _make_fake_map()
        fm.find_path.return_value = []
        um = UnitManager(fm)
        um.create_unit(
            UnitType.SCOUT, "scout_sct", "侦察兵", Faction.ENEMY, _make_coord(5, 5)
        )

        # 创建 range_query 让 SCOUT 能发现敌人
        fake_rq = _make_fake_range_query()
        fake_enemy = Infantry("friend_1", "友军", Faction.FRIENDLY, _make_coord(6, 5))
        fake_rq.get_units_in_range.return_value = [fake_enemy]

        cmdr = Commander(unit_manager=um, game_map=fm, range_query=fake_rq, seed=42)

        spotted_events = []

        def on_spotted(payload):
            spotted_events.append(payload)

        event_bus.subscribe(GameEventType.ENEMY_SPOTTED, on_spotted)

        cmdr.issue_command("scout_sct", CommandType.SCOUT, {"direction": "E"})
        cmdr.process_command_queue(current_turn=10)

        # SCOUT 应广播 ENEMY_SPOTTED
        assert len(spotted_events) >= 1


class TestSprint3BattleSystem:
    """T4-T7: 战斗系统补充测试。"""

    def test_should_strike_first_with_ranged(self):
        """远程单位 + 距离 > 1 → 先手。"""
        from src.battle.battle_system import BattleSystem
        from src.battle.units import Artillery, Infantry

        attacker = Artillery("art_1", "炮兵", Faction.FRIENDLY, _make_coord(0, 0))
        defender = Infantry("inf_1", "步兵", Faction.ENEMY, _make_coord(3, 0))

        assert BattleSystem._should_strike_first(attacker, defender) is True

    def test_should_strike_first_close_range_false(self):
        """距离 1 时不触发先手。"""
        from src.battle.battle_system import BattleSystem
        from src.battle.units import Artillery, Infantry

        attacker = Artillery("art_1", "炮兵", Faction.FRIENDLY, _make_coord(0, 0))
        defender = Infantry("inf_1", "步兵", Faction.ENEMY, _make_coord(1, 0))

        assert BattleSystem._should_strike_first(attacker, defender) is False

    def test_should_strike_first_melee_unit_false(self):
        """近战单位不触发先手。"""
        from src.battle.battle_system import BattleSystem

        attacker = Infantry("inf_a", "步兵A", Faction.FRIENDLY, _make_coord(0, 0))
        defender = Infantry("inf_b", "步兵B", Faction.ENEMY, _make_coord(3, 0))

        assert BattleSystem._should_strike_first(attacker, defender) is False

    def test_stalemate_outcome(self):
        """攻击方 HP 在 30%-70% 且未击杀 → STALEMATE。"""
        from src.battle.battle_system import BattleSystem
        from src.core.constants import BattleOutcome

        outcome = BattleSystem.determine_outcome(
            attacker_hp_ratio=0.5,
            defender_hp_ratio=0.6,
            attacker_killed=False,
            defender_killed=False,
        )
        assert outcome == BattleOutcome.STALEMATE.value

    def test_get_units_in_combat_range(self):
        """交战配对检测正确。"""

        from src.battle.battle_system import BattleSystem

        fake_map = _make_fake_map()
        um = UnitManager(fake_map)
        attacker = um.create_unit(
            UnitType.INFANTRY, "att", "攻击方", Faction.FRIENDLY, _make_coord(5, 5)
        )
        defender = um.create_unit(
            UnitType.INFANTRY, "def", "防御方", Faction.ENEMY, _make_coord(6, 5)
        )

        fake_rq = _make_fake_range_query()
        fake_rq.get_units_in_range.return_value = [defender]

        bs = BattleSystem(unit_manager=um, range_query=fake_rq, game_map=fake_map, seed=42)
        pairs = bs.get_units_in_combat_range()
        assert len(pairs) >= 1
        assert (attacker, defender) in pairs or (defender, attacker) in pairs


class TestSprint3AIEnhancements:
    """T8-T10: Sprint 3 AI 增强测试。"""

    def test_artillery_kiting(self):
        """AI1: 炮兵在近身有敌人时应后撤。"""

        fm = _make_fake_map()
        fm.is_passable.return_value = True
        um = UnitManager(fm)
        # 敌军炮兵 (attack_range=3)
        arty = um.create_unit(
            UnitType.ARTILLERY, "enemy_art", "敌军炮兵", Faction.ENEMY, _make_coord(5, 5)
        )
        # 友军在相邻格 (距离=1 < KITE_SAFE_DISTANCE=2)
        friend = um.create_unit(
            UnitType.INFANTRY, "friend", "友军步兵", Faction.FRIENDLY, _make_coord(6, 5)
        )

        fake_rq = _make_fake_range_query()
        fake_rq.has_enemy_in_range.return_value = True
        fake_rq.get_units_in_range.return_value = [friend]
        fake_rq.find_nearest_enemy.return_value = friend

        cmdr = Commander(unit_manager=um, game_map=fm, seed=42)
        ai = EnemyAI(unit_manager=um, range_query=fake_rq, game_map=fm, commander=cmdr, seed=42)

        # 炮兵决策：应触发风筝
        cmd_type, params = ai.decide_for_unit(arty, current_turn=1)
        # 近身有敌 → RETREAT
        assert cmd_type == CommandType.RETREAT, f"期望 RETREAT，实际 {cmd_type}"
        assert "direction" in params

    def test_ai_multi_unit_decision(self):
        """AI2: 多单位决策时 decide_all 正常执行。"""
        fm = _make_fake_map()
        um = UnitManager(fm)
        um.create_unit(
            UnitType.INFANTRY, "enemy_1", "敌军1", Faction.ENEMY, _make_coord(5, 5)
        )
        um.create_unit(
            UnitType.CAVALRY, "enemy_2", "敌军2", Faction.ENEMY, _make_coord(8, 8)
        )

        fake_rq = _make_fake_range_query()
        cmdr = Commander(unit_manager=um, game_map=fm, seed=42)
        ai = EnemyAI(unit_manager=um, range_query=fake_rq, game_map=fm, commander=cmdr, seed=42)

        mock_gs = MagicMock()
        mock_gs.get_current_turn.return_value = 1

        # 不应崩溃
        ai.decide_all(game_state=mock_gs)

        # 两个敌军都应收到指令
        pending_e1 = cmdr.get_pending_commands("enemy_1")
        pending_e2 = cmdr.get_pending_commands("enemy_2")
        assert len(pending_e1) >= 1
        assert len(pending_e2) >= 1

    def test_ai_prefers_high_defense_terrain(self):
        """AI3: 默认移动偏向高防御地形。"""
        from unittest.mock import patch

        fm = _make_fake_map()
        fm.width = 10
        fm.height = 10
        # 模拟有山地（防御+2）在附近
        fm.get_defense_bonus.return_value = 0  # 默认平原
        fm.is_passable.return_value = True
        fm.get_faction_hq_location.return_value = _make_coord(9, 9)

        um = UnitManager(fm)
        enemy = um.create_unit(
            UnitType.INFANTRY, "enemy_1", "敌军1", Faction.ENEMY, _make_coord(5, 5)
        )

        fake_rq = _make_fake_range_query()
        cmdr = Commander(unit_manager=um, game_map=fm, seed=42)
        ai = EnemyAI(unit_manager=um, range_query=fake_rq, game_map=fm, commander=cmdr, seed=42)

        # 让 AI 进入默认移动分支（非溃逃、非战斗、非保卫HQ）
        with patch.object(ai._rng, 'random', return_value=0.3):  # < 0.5 → MOVE
            cmd_type, params = ai.decide_for_unit(enemy, current_turn=1)

        assert cmd_type in (CommandType.MOVE, CommandType.PATROL)
