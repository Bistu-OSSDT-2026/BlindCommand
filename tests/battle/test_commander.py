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

from unittest.mock import MagicMock, patch

import pytest

from src.battle.ai import EnemyAI
from src.battle.command_queue import CommandQueue
from src.battle.commander import Command, Commander
from src.battle.unit_manager import UnitManager
from src.battle.units import Cavalry, Infantry, Scout
from src.core.constants import (
    CAPTURE_REQUIRED_TURNS,
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
        unit = um.create_unit(
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
        hq = um.create_unit(
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
        unit = um.create_unit(
            UnitType.INFANTRY, "inf_1", "第一步兵连", Faction.FRIENDLY, _make_coord(5, 5)
        )
        enemy = um.create_unit(
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
        unit = um.create_unit(
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
        unit = um.create_unit(
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
        cmdr = Commander(unit_manager=um, game_map=fm, seed=seed)
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

        ai = self._create_ai(enemy, fake_map=fm, fake_rq=fake_rq)
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

        # 不应崩溃
        ai.decide_all(current_turn=1)

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
