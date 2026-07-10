"""
src/ui — UI 表现层（#4 负责，RTT）

模块:
    main_window.py   — RTT 主窗口
    battle_log.py    — 战报面板
    map_widget.py    — 地图渲染（地形+标记+汇报圈）
    command_panel.py — 指令栏（MOVE+RETREAT+罗盘）
    marker.py        — 标记系统
    marker_palette.py— 标记托盘（数字+兵种图标）
"""

from src.ui.battle_log import BattleLogPanel
from src.ui.command_panel import CommandPanel
from src.ui.main_window import MainWindow
from src.ui.map_widget import MapWidget
from src.ui.marker import Marker, MarkerSystem
from src.ui.marker_palette import MarkerPalette

__all__ = [
    "BattleLogPanel",
    "CommandPanel",
    "MainWindow",
    "MapWidget",
    "Marker",
    "MarkerPalette",
    "MarkerSystem",
]
