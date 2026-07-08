"""
src/ui — UI 表现层（#4 负责）

Sprint 2 模块：
    main_window.py  — 主窗口，组装所有子面板 + 依赖注入
    battle_log.py   — 左侧战报面板，订阅 EventBus 13 种事件
    map_widget.py   — 中央地图渲染，四层架构（地形/单位/标记/迷雾）
    command_panel.py— 底部指令栏，7 种指令 + 坐标校验 + ICommander 对接
    marker.py       — 标记拖拽系统，调色板→地图吸附→右键删除
    fog_renderer.py — 迷雾视觉效果，半透明遮罩 + 大致位置高亮
    assets/         — 图片素材目录（#5 维护）
"""

from src.ui.battle_log import BattleLogPanel
from src.ui.command_panel import CommandPanel
from src.ui.fog_renderer import FogRenderer
from src.ui.main_window import MainWindow
from src.ui.map_widget import MapWidget
from src.ui.marker import Marker, MarkerSystem

__all__ = [
    "BattleLogPanel",
    "CommandPanel",
    "FogRenderer",
    "MainWindow",
    "MapWidget",
    "Marker",
    "MarkerSystem",
]
