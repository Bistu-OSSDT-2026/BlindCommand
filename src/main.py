"""
BlindCommand RTT 游戏入口 — 选关 → 游戏 → 结算 → 循环
=========================================================
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.constants import Faction, GameEventType, GameResult
from src.core.engine import RealTimeEngine
from src.core.event_bus import event_bus
from src.ui.level_select import show_level_select
from src.ui.main_window import MainWindow
from src.ui.result_screen import show_result

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    logger = logging.getLogger("main")

    while True:
        # 0. 关卡选择
        level = show_level_select()
        if level is None:
            break

        # 1. 生成地图
        map_path = Path("data/maps/map_01.json")
        if map_path.exists():
            map_path.unlink()
        from src.core.map_generator import MapGenerator
        MapGenerator.generate_to_json(
            map_path, level["width"], level["height"],
            unit_count=level["units"], seed=None,
            difficulty=level["name"])

        # 2. 创建引擎
        engine = RealTimeEngine.from_map_file(map_path)
        from src.battle.ai import EnemyAI
        from src.battle.battle_system import resolve_combat_round
        from src.battle.commander import Commander
        commander = Commander(engine.get_map())
        ai = EnemyAI(engine.get_map(), engine.get_range_query(), commander,
                     difficulty=level["name"])
        engine._commander = commander
        engine._combat_resolver = lambda a, b, t: resolve_combat_round(a, b, t)
        engine._ai_decider = ai.decide_all

        # 击杀计数
        kills = 0
        initial_enemy = len(engine.get_all_units(Faction.ENEMY))
        def _on_kill(payload):
            nonlocal kills
            if payload and getattr(payload, "faction", "") == "ENEMY":
                kills += 1
        event_bus.subscribe(GameEventType.UNIT_KILLED, _on_kill)

        logger.info("引擎就绪")

        # 3. 启动 UI
        window = MainWindow(engine=engine, commander=commander)

        # 等待游戏结束
        result = None
        while result is None:
            time_delta = window._clock.tick(60) / 1000.0
            window._handle_events()
            window._update(time_delta)
            window._render()
            window._frame_count += 1
            if not window._running:
                break
            result = engine.get_game_result()

        window._shutdown()
        event_bus.unsubscribe(GameEventType.UNIT_KILLED, _on_kill)

        if result is None:
            break

        # 4. 结算
        alive_f = len(engine.get_all_units(Faction.FRIENDLY))
        victory = result == GameResult.VICTORY
        restart = show_result(victory, kills, alive_f, engine.get_elapsed_time())
        if not restart:
            break


if __name__ == "__main__":
    main()
