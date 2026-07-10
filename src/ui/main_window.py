"""
MainWindow — 游戏主窗口，组装所有 UI 子面板（Sprint 2 升级版）。

负责 pygame 初始化、布局计算、主循环（事件 / 更新 / 渲染）。
依赖四个子面板：BattleLogPanel、MapWidget、CommandPanel、MarkerSystem、FogRenderer。

Sprint 2 新增：
    - 依赖注入：IGameLoop / IMap / IFogOfWar / ICommander（均可选）
    - 集成 MarkerSystem（拖拽标记）和 FogRenderer（迷雾遮罩）
    - 渲染管线升级：地形 → 单位 → 标记 → 迷雾 → UI 控件
    - 指令执行对接 ICommander（真实指令下达）
    - BattleLogPanel 对接真实 EventBus 事件

约束（UI_SPEC §1.2）：
    C1: 禁止 import src.battle
    C2: 禁止 import src.core 内部实现模块
    C3: 禁止直接读写任何 Unit 实例属性
    C4: 禁止直接修改地图数据
    C5: 所有游戏状态变化只能通过 EventBus 获知

	版本: v1.0.0
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Optional

import pygame
import pygame_gui

from src.core.constants import (
    BATTLE_LOG_WIDTH_RATIO,
    COMMAND_PANEL_HEIGHT,
    MAP_AREA_WIDTH_RATIO,
    WINDOW_HEIGHT,
    WINDOW_TITLE,
    WINDOW_WIDTH,
    Faction,
    GameEventType,
)
from src.core.event_bus import event_bus
from src.ui.battle_log import BattleLogPanel
from src.ui.command_panel import CommandPanel
from src.ui.map_widget import MapWidget
from src.ui.marker import MarkerSystem
from src.ui.marker_palette import MarkerPalette

if TYPE_CHECKING:
    from src.core.interfaces import ICommander, IEngine, IMap

logger = logging.getLogger(__name__)

# ── 颜色常量 ────────────────────────────────────────────────────────

COLOR_BG       = (30, 30, 30)    # 整体背景
COLOR_PANEL_BG = (26, 26, 26)    # 面板背景
COLOR_BORDER   = (60, 60, 60)    # 分隔线


def _find_cjk_font(base_dir: Path) -> str | None:
    """查找可用中文字体。优先系统绝对路径（PyInstaller 中 SDL 搜索失效仍可用）。

    Args:
        base_dir: 项目根目录（用于定位捆绑字体）

    Returns:
        字体文件绝对路径，若未找到任何可用字体返回 None
    """
    import os as _os
    # 1) 系统字体目录（SDL 无法搜索，但绝对路径仍可加载）
    _fonts_dir = _os.environ.get("WINDIR", "C:/Windows") + "/Fonts"
    for _name in ("msyh.ttc", "msyh.ttf", "simkai.ttf", "simsun.ttc"):
        _fp = _os.path.join(_fonts_dir, _name)
        if _os.path.exists(_fp):
            return _fp
    # 2) 捆绑字体
    _bundled = base_dir / "data" / "chinese.ttf"
    if _bundled.exists():
        return str(_bundled)
    # 3) SDL 搜索（开发环境）
    for _name in ("microsoftyahei", "simhei"):
        _path = pygame.font.match_font(_name)
        if _path:
            return _path
    return None


class MainWindow:
    """游戏主窗口。

    组装子面板并运行主循环：
        1. pygame 初始化 + pygame_gui UIManager
        2. 创建 BattleLogPanel（左 28%）
        3. 创建 MapWidget（中 72% 上）
        4. 创建 MarkerSystem（标记拖拽，Sprint 2）
        5. 创建 FogRenderer（迷雾遮罩，Sprint 2）
        6. 创建 CommandPanel（底部 80px）
        7. 主循环：事件分发 → 更新 → 渲染

    Sprint 2 支持两种运行模式：
        - 独立模式（无注入）：加载 JSON 地图 + 模拟战报（Sprint 1 兼容）
        - 集成模式（有注入）：对接 #2/3 接口 + 真实事件订阅
    """

    def __init__(
        self,
        engine: IEngine | None = None,
        commander: ICommander | None = None,
        player_faction: Faction = Faction.FRIENDLY,
        enable_debug_log: bool = False,
    ) -> None:
        """RTT 主窗口。

        Args:
            engine: RTT 引擎实例
            commander: 指令系统（可空）
            player_faction: 玩家阵营
            enable_debug_log: 调试模式
        """
        self._engine = engine
        self._commander = commander
        self._player_faction = player_faction
        self._enable_debug_log = enable_debug_log
        self._integrated_mode = engine is not None

        # ── pygame 初始化 ────────────────────────────────────────
        pygame.init()
        pygame.display.set_caption(WINDOW_TITLE)
        self._screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        self._clock = pygame.time.Clock()
        self._running = True
        self._frame_count = 0
        self._confirming = False
        self._confirm_data = None
        self._dev_mode = False
        self._dev_input = ""
        self._dev_prompt = False

        # ── pygame_gui ────────────────────────────────────────────
        self._ui_manager = pygame_gui.UIManager(
            (WINDOW_WIDTH, WINDOW_HEIGHT))

        # ── 布局 ──────────────────────────────────────────────────
        layout = self._calculate_layout(WINDOW_WIDTH, WINDOW_HEIGHT)

        # ── 子面板 ────────────────────────────────────────────────
        self.battle_log = BattleLogPanel(layout["battle_log_rect"])
        self.map_widget = MapWidget(layout["map_rect"])
        self.command_panel = CommandPanel()

        # ── 标记面板（战报下方） ──────────────────────────────────
        self.marker_palette = MarkerPalette(layout["tray_rect"])
        self.marker_system = MarkerSystem(
            map_offset=(layout["map_rect"].x, layout["map_rect"].y))
        self.map_widget.marker_system = self.marker_system
        # 对接：MarkerPalette 的拖动事件通过 MarkerSystem 处理
        self.marker_system.set_palette(self.marker_palette, layout["tray_rect"])

        # ── 加载兵种图标到托盘 ────────────────────────────────────
        from pathlib import Path
        assets = Path("src/ui/assets/units")
        for name in ["Infantry_blue", "Cavalry_blue", "Artillery_blue", "Scout_blue", "HQ_blue",
                      "Infantry_red", "Cavalry_red", "Artillery_red", "Scout_red", "HQ_red"]:
            for ext in [".svg", ".png"]:
                p = assets / f"{name}{ext}"
                if p.exists():
                    self.marker_palette.load_unit_icon(name, str(p))
                    break

        # ── 引擎对接 ──────────────────────────────────────────────
        if engine is not None:
            self.map_widget.load_map_from_json()
            # 从地图数据读取友军 HQ
            import json
            with open("data/maps/map_01.json", encoding="utf-8") as f:
                d = json.load(f)
            hq = d.get("friendly_hq", {})
            from src.core.constants import Coordinate
            self.map_widget.set_friendly_hq(Coordinate(hq["x"], hq["y"]))
            self.battle_log.set_terrain(
                self.map_widget._terrain_data,
                self.map_widget.map_width,
                self.map_widget.map_height)
            self.battle_log.subscribe_all()
            self.battle_log.append_text("━━━ 我军已就位，等待命令 ━━━", "#FFD700")

        logger.info("MainWindow RTT 初始化完成")

    # ── 主循环 ────────────────────────────────────────────────────

    def run(self) -> None:
        logger.info("MainWindow 进入主循环")
        try:
            while self._running:
                time_delta = self._clock.tick(60) / 1000.0
                self._handle_events()
                self._update(time_delta)
                self._render()
                self._frame_count += 1
        except Exception as e:
            logger.exception("主循环异常: %s", e)
        finally:
            self._shutdown()

    # ── 私有方法：事件处理 ────────────────────────────────────────

    def _handle_events(self) -> None:
        """RTT 事件处理。"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                return

            if event.type == pygame.KEYDOWN:
                # DEV 密码优先
                if self._dev_prompt:
                    if event.key == pygame.K_RETURN:
                        if self._dev_input == "123456":
                            self._dev_mode = True
                        self._dev_prompt = False
                        self._dev_input = ""
                    elif event.key == pygame.K_ESCAPE:
                        self._dev_prompt = False
                        self._dev_input = ""
                    elif event.key == pygame.K_BACKSPACE:
                        self._dev_input = self._dev_input[:-1]
                    elif event.unicode and event.unicode.isdigit():
                        self._dev_input += event.unicode
                    continue
                if event.key == pygame.K_ESCAPE:
                    if self._dev_mode:
                        self._dev_mode = False
                        continue
                    self._running = False
                    return
                if event.key == pygame.K_SPACE:
                    if self._engine is not None:
                        if self._engine.is_paused:
                            self._engine.resume()
                        else:
                            self._engine.pause()
                    continue
                # 确认/取消移动
                if self._confirming and self._confirm_data:
                    if event.key == pygame.K_y:
                        self._do_move()
                    elif event.key == pygame.K_n:
                        self._cancel_move()
                    continue
                # P 键也暂停
                if event.key == pygame.K_p:
                    if self._engine is not None:
                        if self._engine.is_paused:
                            self._engine.resume()
                        else:
                            self._engine.pause()
                    continue
                # DEV 密码输入（在标记处理之前）
                if self._dev_prompt:
                    if event.key == pygame.K_RETURN:
                        if self._dev_input == "123456":
                            self._dev_mode = True
                        self._dev_prompt = False
                        self._dev_input = ""
                    elif event.key == pygame.K_ESCAPE:
                        self._dev_prompt = False
                        self._dev_input = ""
                    elif event.key == pygame.K_BACKSPACE:
                        self._dev_input = self._dev_input[:-1]
                    elif event.unicode and event.unicode.isdigit():
                        self._dev_input += event.unicode
                    continue

            # 地图点击 → 浮出单位面板
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # 暂停按钮
                if pygame.Rect(4, 4, 50, 22).collidepoint(event.pos):
                    if self._engine is not None:
                        if self._engine.is_paused:
                            self._engine.resume()
                        else:
                            self._engine.pause()
                    continue
                # DEV 按钮
                if pygame.Rect(58, 4, 40, 22).collidepoint(event.pos):
                    if self._dev_mode:
                        self._dev_mode = False
                    else:
                        self._dev_prompt = True
                        self._dev_input = ""
                    continue
                if self.command_panel.is_visible:
                    clicked = self.command_panel.handle_click(event.pos)
                    if clicked and self._engine:
                        self._on_unit_selected(clicked)
                    else:
                        self.command_panel.hide()
                        coord = self.map_widget.pixel_to_coord(
                            event.pos[0] - self.map_widget.rect.x,
                            event.pos[1] - self.map_widget.rect.y,
                        )
                        if coord is not None and self._engine is not None:
                            friendly = [u for u in self._engine.get_all_units(Faction.FRIENDLY)
                                        if not u.is_hq and u.is_alive]
                            if friendly:
                                self.command_panel.set_target(coord)
                                self.command_panel.show(event.pos, [u.name for u in friendly])
                else:
                    coord = self.map_widget.pixel_to_coord(
                        event.pos[0] - self.map_widget.rect.x,
                        event.pos[1] - self.map_widget.rect.y,
                    )
                    if coord is not None and self._engine is not None:
                        friendly = [u for u in self._engine.get_all_units(Faction.FRIENDLY)
                                    if not u.is_hq and u.is_alive]
                        if friendly:
                            self.command_panel.set_target(coord)
                            self.command_panel.show(event.pos, [u.name for u in friendly])

            # 右键 → 关闭弹窗
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                if self.command_panel.is_visible:
                    self.command_panel.hide()

            # 标记拖拽
            consumed = self.marker_system.handle_event(event, self.map_widget)
            if consumed:
                continue

            # pygame_gui
            self._ui_manager.process_events(event)

            # 滚轮 → 战报滚动
            if event.type == pygame.MOUSEWHEEL:
                if event.x < WINDOW_WIDTH * BATTLE_LOG_WIDTH_RATIO:
                    self.battle_log.handle_scroll(-event.y)

    def _on_unit_selected(self, unit_name: str) -> None:
        """选单位 → 显示确认，Y 执行。"""
        target = self.command_panel.get_target()
        self.command_panel.hide()
        if target is None or self._engine is None:
            return
        friendly = [u for u in self._engine.get_all_units(Faction.FRIENDLY)
                    if not u.is_hq and u.is_alive]
        unit = None
        for u in friendly:
            if u.name == unit_name:
                unit = u
                break
        if unit is None:
            return
        dx = target.x - unit.position.x
        dy = target.y - unit.position.y
        direction = self._calc_direction(dx, dy)
        dist = max(1, max(abs(dx), abs(dy)))
        self._confirm_data = {
            "unit": unit,
            "direction": direction,
            "distance": dist,
        }
        self._confirming = True
        self.battle_log.append_text(
            f"⚡ {unit_name} → {direction}方向{dist}格 [Y/N]",
        )

    def _do_move(self) -> None:
        """确认移动。"""
        if self._confirm_data is None or self._commander is None:
            self._confirming = False
            return
        cd = self._confirm_data
        from src.core.constants import CommandType
        self._commander.issue_command(
            cd["unit"].unit_id, CommandType.MOVE,
            {"direction": cd["direction"], "distance": cd["distance"]},
            self._engine.get_elapsed_time(),
        )
        self.battle_log.append_text(
            f"📨 指令已发出：{cd['unit'].name} → {cd['direction']}方向{cd['distance']}格",
        )
        self._confirming = False
        self._confirm_data = None

    def _cancel_move(self) -> None:
        self._confirming = False
        self._confirm_data = None
        self.battle_log.append_text("已取消", "#888888")

    @staticmethod
    def _calc_direction(dx: int, dy: int) -> str:
        if dx == 0 and dy == 0:
            return "·"
        parts = []
        if dy < 0: parts.append("N")
        if dy > 0: parts.append("S")
        if dx < 0: parts.append("W")
        if dx > 0: parts.append("E")
        return "".join(parts)

            # ── Sprint 3: 文本输入变化 → 实时坐标校验 ────────────
            if event.type == pygame_gui.UI_TEXT_ENTRY_CHANGED:
                if event.ui_element in (self.command_panel.entry_x, self.command_panel.entry_y):
                    self.command_panel.validate_inputs()

    # ── 私有方法：更新 ────────────────────────────────────────────

    def _update(self, time_delta: float) -> None:
        """RTT 每帧更新。"""
        self._ui_manager.update(time_delta)
        self.battle_log.update(time_delta)

        # RTT 引擎 tick
        if self._engine is not None and not self._engine.is_paused:
            self._engine.update(time_delta)

        # 汇报圈更新
        self.map_widget.update_report_circles(time_delta)
        # 开发者模式单位
        if self._dev_mode and self._engine is not None:
            self.map_widget.set_dev_units(list(self._engine.get_all_units()))  # 强制新列表

        # 地图渲染
        self.map_widget.render()

    # ── 私有方法：渲染 ────────────────────────────────────────────

    def _render(self) -> None:
        """RTT 渲染。"""
        self._screen.fill(COLOR_BG)
        self._draw_panel_decorations()
        self.map_widget.draw(self._screen)
        self.battle_log.draw(self._screen)
        self.marker_palette.draw(self._screen)
        self.command_panel.draw(self._screen)
        self._draw_pause_btn()
        self._ui_manager.draw_ui(self._screen)
        pygame.display.flip()

    def _draw_pause_btn(self) -> None:
        paused = self._engine.is_paused if self._engine else False
        color = (180, 60, 60) if paused else (60, 160, 60)
        rect = pygame.Rect(4, 4, 50, 22)
        pygame.draw.rect(self._screen, color, rect, border_radius=3)
        font = pygame.font.Font("C:/Windows/Fonts/simhei.ttf", 13)
        text = font.render("暂停" if not paused else "继续", True, (255, 255, 255))
        self._screen.blit(text, (rect.x + 6, rect.y + 2))
        # DEV 按钮
        dev_rect = pygame.Rect(58, 4, 40, 22)
        dev_color = (60, 60, 160) if self._dev_mode else (60, 60, 60)
        pygame.draw.rect(self._screen, dev_color, dev_rect, border_radius=3)
        dev_text = font.render("DEV", True, (255, 255, 255))
        self._screen.blit(dev_text, (dev_rect.x + 4, dev_rect.y + 2))
        # 密码输入提示
        if self._dev_prompt:
            prompt = font.render(f"密码: {'*' * len(self._dev_input)}_", True, (255, 200, 100))
            self._screen.blit(prompt, (dev_rect.right + 8, 4))

    def _draw_panel_decorations(self) -> None:
        """绘制面板背景和分隔线（非 pygame_gui 控件）。"""
        layout = self._layout

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

    @staticmethod
    def _calculate_layout(window_w: int, window_h: int) -> dict[str, pygame.Rect]:
        map_area_bottom = window_h - COMMAND_PANEL_HEIGHT
        battle_log_width = int(window_w * BATTLE_LOG_WIDTH_RATIO)
        map_width = window_w - battle_log_width
        tray_height = 140  # 标记托盘（加高：2行数字 + 2行图标）

        return {
            "battle_log_rect": pygame.Rect(0, 30, battle_log_width, map_area_bottom - 30 - tray_height),
            "tray_rect": pygame.Rect(0, map_area_bottom - tray_height, battle_log_width, tray_height),
            "map_rect": pygame.Rect(battle_log_width, 0, map_width, map_area_bottom),
            "command_rect": pygame.Rect(0, map_area_bottom, window_w, COMMAND_PANEL_HEIGHT),
        }
