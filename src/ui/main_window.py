"""
MainWindow — 游戏主窗口，组装所有 UI 子面板。

负责 pygame 初始化、布局计算、主循环（事件 / 更新 / 渲染）。
依赖三个子面板：BattleLogPanel、MapWidget、CommandPanel。
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import pygame
import pygame_gui

from src.core.constants import (
    BATTLE_LOG_BG_COLOR,
    BATTLE_LOG_WIDTH_RATIO,
    COMMAND_PANEL_BG_COLOR,
    COMMAND_PANEL_HEIGHT,
    MAP_AREA_WIDTH_RATIO,
    WINDOW_HEIGHT,
    WINDOW_TITLE,
    WINDOW_WIDTH,
)
from src.ui.battle_log import BattleLogPanel
from src.ui.command_panel import CommandPanel
from src.ui.map_widget import MapWidget

logger = logging.getLogger(__name__)

# ── 颜色常量 ────────────────────────────────────────────────────────

COLOR_BG       = (30, 30, 30)    # 整体背景
COLOR_PANEL_BG = (26, 26, 26)    # 面板背景
COLOR_BORDER   = (60, 60, 60)    # 分隔线


class MainWindow:
    """游戏主窗口。

    组装三个子面板并运行主循环：
    1. pygame 初始化 + pygame_gui UIManager
    2. 创建 BattleLogPanel（左 28%）
    3. 创建 MapWidget（中 72% 上）
    4. 创建 CommandPanel（底部 80px）
    5. 主循环：事件分发 → 更新 → 渲染
    """

    def __init__(self) -> None:
        """初始化窗口和所有子面板。"""
        # ── pygame 初始化 ────────────────────────────────────────
        pygame.init()
        pygame.display.set_caption(WINDOW_TITLE)

        self._screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        self._clock = pygame.time.Clock()
        self._running = True
        self._frame_count = 0

        # ── pygame_gui 初始化 ────────────────────────────────────
        self._ui_manager = pygame_gui.UIManager(
            (WINDOW_WIDTH, WINDOW_HEIGHT),
            theme_path=None,  # 使用默认主题
        )

        # ── 布局计算 ─────────────────────────────────────────────
        layout = self._calculate_layout(WINDOW_WIDTH, WINDOW_HEIGHT)

        # ── 子面板 ───────────────────────────────────────────────
        self.battle_log = BattleLogPanel(layout["battle_log_rect"], self._ui_manager)
        self.map_widget = MapWidget(layout["map_rect"])
        self.command_panel = CommandPanel(layout["command_rect"], self._ui_manager)

        # ── Sprint 1：加载地图并输出模拟战报 ────────────────────
        if self.map_widget.load_map_from_json():
            logger.info("地图加载成功，准备渲染")
        else:
            logger.warning("地图加载失败，地图区域将为空")

        # 模拟战报（无需 EventBus，直接调用 BattleLogPanel.simulate_events()）
        self.battle_log.simulate_events()

        logger.info("MainWindow 初始化完成 (%d×%d)", WINDOW_WIDTH, WINDOW_HEIGHT)

    # ── 主循环 ────────────────────────────────────────────────────

    def run(self) -> None:
        """启动主循环。阻塞直到用户关闭窗口或按 ESC。"""
        logger.info("MainWindow 进入主循环")

        while self._running:
            time_delta = self._clock.tick(30) / 1000.0  # 秒

            self._handle_events()
            self._update(time_delta)
            self._render()

            self._frame_count += 1

        self._shutdown()

    # ── 私有方法：事件处理 ────────────────────────────────────────

    def _handle_events(self) -> None:
        """分发 pygame 事件。

        处理：
        - QUIT / ESC → 退出
        - pygame_gui 事件 → UIManager
        - 执行按钮点击 → CommandPanel.on_execute_clicked()
        - SPACE → 打印调试信息
        """
        for event in pygame.event.get():
            # ── 退出 ────────────────────────────────────────────
            if event.type == pygame.QUIT:
                self._running = False
                return

            # ── pygame_gui 事件 ─────────────────────────────────
            self._ui_manager.process_events(event)

            # ── 键盘事件 ────────────────────────────────────────
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self._running = False
                    return
                elif event.key == pygame.K_SPACE:
                    sel = self.command_panel.get_selection()
                    logger.info(
                        "[调试] Frame=%d | 指令=%s 目标=%s 坐标=(%d,%d)",
                        self._frame_count,
                        sel["command"],
                        sel["unit"],
                        sel["x"],
                        sel["y"],
                    )

            # ── pygame_gui 按钮点击 ─────────────────────────────
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == self.command_panel.button_execute:
                    self.command_panel.on_execute_clicked()
                    # 同步追加到战报面板
                    sel = self.command_panel.get_selection()
                    self.battle_log.append_text(
                        f"📨 指令已发出：{sel['unit']} → {sel['command']} ({sel['x']}, {sel['y']})"
                    )

    # ── 私有方法：更新 ────────────────────────────────────────────

    def _update(self, time_delta: float) -> None:
        """每帧更新所有子面板和 UI 管理器。

        Args:
            time_delta: 上一帧的时间间隔（秒）
        """
        self._ui_manager.update(time_delta)
        self.battle_log.update(time_delta)
        self.command_panel.update(time_delta)

        # 地图渲染（只在需要时刷新）
        self.map_widget.render()

    # ── 私有方法：渲染 ────────────────────────────────────────────

    def _render(self) -> None:
        """每帧渲染顺序：背景 → 地图 → 面板装饰 → UI 控件。"""
        # ── 背景 ────────────────────────────────────────────────
        self._screen.fill(COLOR_BG)

        # ── 地图区域 ────────────────────────────────────────────
        self.map_widget.draw(self._screen)

        # ── 面板背景和分隔线 ────────────────────────────────────
        self._draw_panel_decorations()

        # ── pygame_gui 控件（必须在最后绘制，保证在最上层） ────
        self._ui_manager.draw_ui(self._screen)

        # ── 提交帧 ──────────────────────────────────────────────
        pygame.display.flip()

    def _draw_panel_decorations(self) -> None:
        """绘制面板背景和分隔线（非 pygame_gui 控件）。"""
        layout = self._calculate_layout(WINDOW_WIDTH, WINDOW_HEIGHT)

        # 左侧战报面板背景
        br = layout["battle_log_rect"]
        pygame.draw.rect(self._screen, COLOR_PANEL_BG, br)
        pygame.draw.rect(self._screen, COLOR_BORDER, br, 1)

        # 底部指令栏背景
        cr = layout["command_rect"]
        pygame.draw.rect(self._screen, (42, 42, 42), cr)
        pygame.draw.rect(self._screen, COLOR_BORDER, cr, 1)

        # 垂直分隔线（战报 ↔ 地图）
        pygame.draw.line(
            self._screen, COLOR_BORDER,
            (br.right, 0), (br.right, br.bottom), 2,
        )

        # 水平分隔线（地图 ↔ 指令栏）
        pygame.draw.line(
            self._screen, COLOR_BORDER,
            (0, cr.top), (WINDOW_WIDTH, cr.top), 2,
        )

    # ── 私有方法：退出 ────────────────────────────────────────────

    def _shutdown(self) -> None:
        """清理资源并退出。"""
        logger.info("MainWindow 正在退出 (共 %d 帧)", self._frame_count)
        self.battle_log.unsubscribe_all()
        pygame.quit()

    # ── 静态方法 ──────────────────────────────────────────────────

    @staticmethod
    def _calculate_layout(window_w: int, window_h: int) -> dict[str, pygame.Rect]:
        """根据窗口尺寸计算各面板的矩形区域。

        Args:
            window_w: 窗口宽度
            window_h: 窗口高度

        Returns:
            {
                "battle_log_rect": pygame.Rect,   # 左侧战报面板
                "map_rect":        pygame.Rect,   # 中间地图区域
                "command_rect":    pygame.Rect,   # 底部指令栏
            }
        """
        map_area_bottom = window_h - COMMAND_PANEL_HEIGHT

        battle_log_width = int(window_w * BATTLE_LOG_WIDTH_RATIO)
        map_width = window_w - battle_log_width

        return {
            "battle_log_rect": pygame.Rect(0, 0, battle_log_width, map_area_bottom),
            "map_rect": pygame.Rect(battle_log_width, 0, map_width, map_area_bottom),
            "command_rect": pygame.Rect(0, map_area_bottom, window_w, COMMAND_PANEL_HEIGHT),
        }
