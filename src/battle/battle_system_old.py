"""
对战结算系统 — 伤害公式、单场战斗、全体战斗调度。

核心职责:
    - calculate_damage(): 纯函数，计算攻击方对防御方的实际伤害
    - BattleSystem: 管理每回合所有敌对单位战斗结算
    - 先手判定（炮兵远程）、反击、溃逃机制
    - 广播 BATTLE_RESULT / UNIT_DAMAGED / HQ_UNDER_ATTACK 事件

依赖:
    src/core/interfaces.py — IUnit, IMap, IRangeQuery
    src/core/constants.py  — 战斗规则常量
    src/core/event_bus.py  — 事件广播
    src/battle/units.py    — Unit 基类
    src/battle/unit_manager.py — UnitManager

版本: v0.1.0
"""

from __future__ import annotations

import random

from src.battle.unit_manager import UnitManager
from src.core.constants import (
    COMBAT_COUNTERATTACK_ENABLED,
    COMBAT_CRITICAL_HP_RATIO,
    COMBAT_HEALTHY_HP_RATIO,
    COMBAT_MIN_DAMAGE,
    COMBAT_RANGED_FIRST_STRIKE,
    COMBAT_ROUT_CHANCE,
    COMBAT_ROUT_HP_RATIO,
    BattleOutcome,
    BattleResultPayload,
    Faction,
    GameEventType,
    UnitDamagedPayload,
    get_advantage_multiplier,
)
from src.core.event_bus import event_bus
from src.core.interfaces import IMap, IRangeQuery, IUnit

# ============================================================================
# 纯函数: calculate_damage
# ============================================================================


def calculate_damage(
    attacker: IUnit,
    defender: IUnit,
) -> int:
    """计算攻击方对防御方造成的实际伤害。

    伤害公式:
        raw = attacker.attack - defender.defense
        raw = max(COMBAT_MIN_DAMAGE, raw)
        multiplier = get_advantage_multiplier(attacker.unit_type, defender.unit_type)
        damage = int(raw * multiplier)

    注意: defender.defense 已包含地形防御加成（per IUnit 接口契约）。
    调用方应在调用前通过 Unit.terrain_defense_bonus 确保防御力反映当前地形。

    Args:
        attacker: 攻击方单位
        defender: 防御方单位

    Returns:
        实际伤害值 (int, >= COMBAT_MIN_DAMAGE)

    Examples:
        >>> # 骑兵(攻4) vs 炮兵(防1) 在平原: raw=3, ×1.5克 → damage=4
        >>> # 侦察兵(攻1) vs 步兵(防2): raw=max(1,-1)=1, ×1.0 → damage=1
    """
    raw_damage = attacker.attack - defender.defense
    raw_damage = max(COMBAT_MIN_DAMAGE, raw_damage)

    multiplier = get_advantage_multiplier(attacker.unit_type, defender.unit_type)
    return int(raw_damage * multiplier)


# ============================================================================
# BattleSystem
# ============================================================================


class BattleSystem:
    """对战结算系统。

    由游戏主循环在"对战阶段"调用 process_all_battles()。
    处理所有敌对单位相遇的战斗结算，包括先手判定、反击、溃逃。
    """

    def __init__(
        self,
        unit_manager: UnitManager,
        range_query: IRangeQuery,
        game_map: IMap,
        seed: int | None = None,
    ) -> None:
        """初始化对战系统。

        Args:
            unit_manager: 单位管理器（用于 kill_unit）
            range_query: 范围检索接口（#2 实现）
            game_map: 地图接口（#2 实现，用于取地形加成）
            seed: 随机种子（测试用，用于溃逃判定）
        """
        self._unit_manager = unit_manager
        self._range_query = range_query
        self._game_map = game_map
        self._rng = random.Random(seed)

    # ── 主入口 ──────────────────────────────────────────────────────────

    def process_all_battles(self, current_turn: int) -> list[BattleResultPayload]:
        """处理所有敌对单位相遇的战斗。

        遍历所有存活单位，对每对相邻敌对单位结算战斗。
        使用 frozenset 去重，避免 (A,B) 和 (B,A) 重复结算。

        Args:
            current_turn: 当前回合数

        Returns:
            本回合所有战斗结果列表（供主循环做胜利判定）
        """
        results: list[BattleResultPayload] = []
        pairs = self.get_units_in_combat_range()

        processed: set[frozenset[str]] = set()

        for unit_a, unit_b in pairs:
            pair_key = frozenset({unit_a.unit_id, unit_b.unit_id})
            if pair_key in processed:
                continue
            processed.add(pair_key)

            # 确定先手方：远程单位先手
            if self._should_strike_first(unit_a, unit_b):
                attacker, defender = unit_a, unit_b
            elif self._should_strike_first(unit_b, unit_a):
                attacker, defender = unit_b, unit_a
            else:
                # 双方均为近战或无先手优势，任意顺序
                attacker, defender = unit_a, unit_b

            payload = self.resolve_battle(attacker, defender, current_turn)
            if payload is not None:
                results.append(payload)

        return results

    # ── 单场战斗 ────────────────────────────────────────────────────────

    def resolve_battle(
        self, attacker: IUnit, defender: IUnit, current_turn: int
    ) -> BattleResultPayload | None:
        """结算单场 1v1 战斗。

        完整流程:
        1. 记录战前 HP
        2. 判定先手（远程先手 / 近战同时结算）
        3. 计算伤害并应用
        4. 若防御方存活 + 反击启用：防御方反击
        5. 检查阵亡 → kill_unit
        6. 溃逃判定（仅敌军 + HP < 20%）
        7. 广播事件
        8. 返回 BattleResultPayload

        Args:
            attacker: 攻击方
            defender: 防御方
            current_turn: 当前回合数

        Returns:
            BattleResultPayload，若双方均无法攻击则返回 None
        """
        # 0. 检查战斗可行性
        if not attacker.is_alive or not defender.is_alive:
            return None
        if not attacker.can_attack(defender) and not defender.can_attack(attacker):
            return None

        # 1. 记录战前 HP
        a_hp_before = attacker.current_hp
        d_hp_before = defender.current_hp

        # 设置地形加成
        attacker.terrain_defense_bonus = self._game_map.get_defense_bonus(
            attacker.position
        )
        defender.terrain_defense_bonus = self._game_map.get_defense_bonus(
            defender.position
        )

        damage_to_defender = 0
        damage_to_attacker = 0
        defender_routed = False

        # 2. 先手判定
        ranged_first = self._is_ranged_first_strike(attacker, defender)

        if ranged_first:
            # 远程先手：攻击方先攻击，防御方不反击
            damage_to_defender = calculate_damage(attacker, defender)
            defender.take_damage(damage_to_defender, attacker)
        else:
            # 近战同时结算：攻击方攻击 → 若防御方存活且可反击 → 防御方反击
            damage_to_defender = calculate_damage(attacker, defender)
            defender.take_damage(damage_to_defender, attacker)

            # 3. 反击判定
            if (
                COMBAT_COUNTERATTACK_ENABLED
                and defender.is_alive
                and defender.can_attack(attacker)
            ):
                damage_to_attacker = calculate_damage(defender, attacker)
                attacker.take_damage(damage_to_attacker, defender)

        # 4. 阵亡检查
        attacker_killed = not attacker.is_alive
        defender_killed = not defender.is_alive

        if defender_killed:
            self._unit_manager.kill_unit(defender, attacker, current_turn)
        if attacker_killed:
            self._unit_manager.kill_unit(attacker, defender, current_turn)

        # 5. 溃逃判定（仅敌军 + HP < 20% + 非 HQ + 未阵亡）
        if (
            not defender_killed
            and defender.faction == Faction.ENEMY
            and not defender.is_hq
            and defender.hp_ratio < COMBAT_ROUT_HP_RATIO
            and self._rng.random() < COMBAT_ROUT_CHANCE
        ):
            defender_routed = True

        # 6. 判定战斗结果措辞
        a_hp_ratio = attacker.hp_ratio if attacker.is_alive else 0.0
        d_hp_ratio = defender.hp_ratio if defender.is_alive else 0.0
        outcome = self.determine_outcome(
            a_hp_ratio, d_hp_ratio, attacker_killed, defender_killed, defender_routed
        )

        # 7. 广播事件
        # ── BATTLE_RESULT ────────────────────────────────────────────
        event_bus.emit(
            GameEventType.BATTLE_RESULT,
            BattleResultPayload(
                turn=current_turn,
                attacker_id=attacker.unit_id,
                attacker_name=attacker.name,
                attacker_faction=attacker.faction.value,
                attacker_hp_before=a_hp_before,
                attacker_hp_after=attacker.current_hp,
                defender_id=defender.unit_id,
                defender_name=defender.name,
                defender_faction=defender.faction.value,
                defender_hp_before=d_hp_before,
                defender_hp_after=defender.current_hp,
                damage_to_defender=damage_to_defender,
                damage_to_attacker=damage_to_attacker,
                attacker_killed=attacker_killed,
                defender_killed=defender_killed,
                location=defender.position.to_tuple(),
                outcome=outcome,
            ),
        )

        # ── UNIT_DAMAGED (受伤但未阵亡) ──────────────────────────────
        if not attacker_killed and damage_to_attacker > 0:
            event_bus.emit(
                GameEventType.UNIT_DAMAGED,
                UnitDamagedPayload(
                    turn=current_turn,
                    unit_id=attacker.unit_id,
                    unit_name=attacker.name,
                    faction=attacker.faction.value,
                    hp_before=a_hp_before,
                    hp_after=attacker.current_hp,
                    damage=damage_to_attacker,
                    source_name=defender.name,
                    location=attacker.position.to_tuple(),
                ),
            )

        if not defender_killed and damage_to_defender > 0:
            event_bus.emit(
                GameEventType.UNIT_DAMAGED,
                UnitDamagedPayload(
                    turn=current_turn,
                    unit_id=defender.unit_id,
                    unit_name=defender.name,
                    faction=defender.faction.value,
                    hp_before=d_hp_before,
                    hp_after=defender.current_hp,
                    damage=damage_to_defender,
                    source_name=attacker.name,
                    location=defender.position.to_tuple(),
                ),
            )

        # ── HQ_UNDER_ATTACK ──────────────────────────────────────────
        if defender.is_hq and damage_to_defender > 0:
            event_bus.emit(GameEventType.HQ_UNDER_ATTACK, None)

        return BattleResultPayload(
            turn=current_turn,
            attacker_id=attacker.unit_id,
            attacker_name=attacker.name,
            attacker_faction=attacker.faction.value,
            attacker_hp_before=a_hp_before,
            attacker_hp_after=attacker.current_hp,
            defender_id=defender.unit_id,
            defender_name=defender.name,
            defender_faction=defender.faction.value,
            defender_hp_before=d_hp_before,
            defender_hp_after=defender.current_hp,
            damage_to_defender=damage_to_defender,
            damage_to_attacker=damage_to_attacker,
            attacker_killed=attacker_killed,
            defender_killed=defender_killed,
            location=defender.position.to_tuple(),
            outcome=outcome,
        )

    # ── 辅助方法 ────────────────────────────────────────────────────────

    @staticmethod
    def determine_outcome(
        attacker_hp_ratio: float,
        defender_hp_ratio: float,
        attacker_killed: bool,
        defender_killed: bool,
        defender_routed: bool = False,
    ) -> str:
        """根据战后血量比判定战斗结果（用于战报措辞）。

        Args:
            attacker_hp_ratio: 攻击方战后血量比例 (0.0~1.0)
            defender_hp_ratio: 防御方战后血量比例 (0.0~1.0)
            attacker_killed: 攻击方是否阵亡
            defender_killed: 防御方是否阵亡
            defender_routed: 防御方是否溃逃

        Returns:
            BattleOutcome 的值字符串
        """
        if defender_routed:
            return BattleOutcome.ENEMY_ROUTED.value
        if attacker_killed and defender_killed:
            return BattleOutcome.MUTUAL_KILL.value
        if attacker_killed:
            return BattleOutcome.DECISIVE_LOSS.value
        if defender_killed:
            if attacker_hp_ratio >= COMBAT_HEALTHY_HP_RATIO:
                return BattleOutcome.DECISIVE_WIN.value
            return BattleOutcome.PYRHHIC_WIN.value

        # 双方存活
        if attacker_hp_ratio >= COMBAT_HEALTHY_HP_RATIO:
            return BattleOutcome.DECISIVE_WIN.value
        if attacker_hp_ratio < COMBAT_CRITICAL_HP_RATIO:
            return BattleOutcome.PYRHHIC_WIN.value
        return BattleOutcome.DECISIVE_WIN.value

    @staticmethod
    def _should_strike_first(unit: IUnit, target: IUnit) -> bool:
        """判断 unit 是否应对 target 先手攻击。

        条件：COMBAT_RANGED_FIRST_STRIKE 启用
             且 unit.attack_range > 1
             且 unit 到 target 的距离 > 1（远程）

        Args:
            unit: 候选先手方
            target: 目标

        Returns:
            True 如果 unit 应先手
        """
        if not COMBAT_RANGED_FIRST_STRIKE:
            return False
        if unit.attack_range <= 1:
            return False
        dist = unit.position.chebyshev_distance(target.position)
        return dist > 1

    @staticmethod
    def _is_ranged_first_strike(attacker: IUnit, defender: IUnit) -> bool:
        """判定本次战斗是否为远程先手（攻击方远程 + 距离 > 1）。

        Args:
            attacker: 攻击方
            defender: 防御方

        Returns:
            True 如果攻击方发起远程先手攻击
        """
        return BattleSystem._should_strike_first(attacker, defender)

    def get_units_in_combat_range(self) -> list[tuple[IUnit, IUnit]]:
        """找出所有处于交战状态的敌对单位对。

        遍历所有存活单位，用 IRangeQuery 找到彼此攻击范围内的敌人。
        去重由 process_all_battles() 负责。

        Returns:
            (unit_a, unit_b) 列表，每对至少一方可攻击另一方

        Note:
            依赖 #2 的 IRangeQuery 实现。若 #2 未交付，此方法返回空列表。
        """
        pairs: list[tuple[IUnit, IUnit]] = []
        alive_units = self._unit_manager.get_alive_units()

        for unit in alive_units:
            if unit.attack_range == 0:
                continue  # HQ 不参与主动索敌

            # 用攻击范围检索附近的敌人
            enemies = self._range_query.get_units_in_range(
                center=unit.position,
                radius=unit.attack_range,
                faction=(
                    Faction.ENEMY if unit.faction == Faction.FRIENDLY else Faction.FRIENDLY
                ),
                exclude_ids={unit.unit_id},
            )

            for enemy in enemies:
                if unit.can_attack(enemy):
                    pairs.append((unit, enemy))
                elif enemy.can_attack(unit):
                    pairs.append((enemy, unit))

        return pairs
