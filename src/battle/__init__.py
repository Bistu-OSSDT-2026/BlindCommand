"""
src/battle — 战斗业务层（#3 负责）

本包对外暴露:
    - units:         兵种子类 (Infantry, Cavalry, Artillery, Scout, HQ)
    - unit_manager:  单位实例管理器 (UnitManager)
    - battle_system: 对战结算系统 (BattleSystem)
    - commander:     指令解析与执行 (Commander) — 待实现
    - command_queue: 通信延迟队列 (CommandQueue) — 待实现
    - ai:            敌军 AI 决策 (EnemyAI) — 待实现
"""

from src.battle.battle_system import BattleSystem, calculate_damage
from src.battle.unit_manager import UnitManager
from src.battle.units import HQ, Artillery, Cavalry, Infantry, Scout, Unit

__all__ = [
    "Artillery",
    "BattleSystem",
    "calculate_damage",
    "Cavalry",
    "HQ",
    "Infantry",
    "Scout",
    "Unit",
    "UnitManager",
]
