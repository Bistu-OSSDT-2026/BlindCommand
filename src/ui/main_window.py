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

版本: v0.2.0 — Sprint 2
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pygame
import pygame_gui

from src.core.constants import (
    BATTLE_LOG_WIDTH_RATIO,
    COMMAND_PANEL_HEIGHT,
    WINDOW_HEIGHT,
    WINDOW_TITLE,
    WINDOW_WIDTH,
    Faction,
    GameEventType,
)
from src.core.event_bus import event_bus
from src.ui.battle_log import BattleLogPanel
from src.ui.command_panel import CommandPanel
from src.ui.fog_renderer import FogRenderer
from src.ui.map_widget import MapWidget
from src.ui.marker import MarkerSystem

if TYPE_CHECKING:
    from src.core.interfaces import ICommander, IFogOfWar, IGameLoop, IMap

logger = logging.getLogger(__name__)

# ── 颜色常量 ────────────────────────────────────────────────────────

COLOR_BG       = (30, 30, 30)    # 整体背景
COLOR_PANEL_BG = (26, 26, 26)    # 面板背景
COLOR_BORDER   = (60, 60, 60)    # 分隔线


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
        game_loop: IGameLoop | None = None,
        map_data: IMap | None = None,
        fog: IFogOfWar | None = None,
        commander: ICommander | None = None,
        player_faction: Faction = Faction.FRIENDLY,
        enable_debug_log: bool = False,
    ) -> None:
        """初始化窗口和所有子面板。

        Args:
            game_loop: #2 提供的 IGameLoop 实例（可选）
            map_data: #2 提供的 IMap 实例（可选）
            fog: #2 提供的 IFogOfWar 实例（可选）
            commander: #3 提供的 ICommander 实例（可选）
            player_faction: 玩家阵营
            enable_debug_log: 是否启用调试模式（模拟战报输出）
        """
        # ── 依赖注入存储 ──────────────────────────────────────────
        self._game_loop = game_loop
        self._map_data = map_data
        self._fog = fog
        self._commander = commander
        self._player_faction = player_faction
        self._enable_debug_log = enable_debug_log

        # ── 判断运行模式 ──────────────────────────────────────────
        self._integrated_mode = (
            game_loop is not None
            and map_data is not None
            and fog is not None
        )

        # ── pygame 初始化 ────────────────────────────────────────
        try:
            pygame.init()
            pygame.display.set_caption(WINDOW_TITLE)
            self._screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        except pygame.error as e:
            print(f"[错误] pygame 初始化失败: {e}")
            print("请确认已安装 pygame 并且显示环境可用。")
            raise SystemExit(1) from e
        self._clock = pygame.time.Clock()
        self._running = True
        self._frame_count = 0

        # ── pygame_gui 初始化 ────────────────────────────────────
        self._ui_manager = pygame_gui.UIManager(
            (WINDOW_WIDTH, WINDOW_HEIGHT),
            theme_path=None,
        )

        # ── 布局计算（BUG-2: 存储复用，避免每帧重复计算） ──────
        self._layout = self._calculate_layout(WINDOW_WIDTH, WINDOW_HEIGHT)

        # ── 子面板 ───────────────────────────────────────────────
        self.battle_log = BattleLogPanel(self._layout["battle_log_rect"], self._ui_manager)
        self.map_widget = MapWidget(self._layout["map_rect"])
        self.command_panel = CommandPanel(
            self._layout["command_rect"], self._ui_manager,
        )

        # ── Sprint 2：标记系统 ───────────────────────────────────
        self.marker_system = MarkerSystem(
            map_offset=(self._layout["map_rect"].x, self._layout["map_rect"].y),
        )
        # 构建调色板（在战报面板右侧边缘）
        self.marker_system.build_palette(
            x=self._layout["map_rect"].x - 48,
            y=self._layout["map_rect"].y,
            height=self._layout["map_rect"].height,
        )
        self.map_widget.marker_system = self.marker_system

        # ── Sprint 2：迷雾渲染器 ─────────────────────────────────
        self.fog_renderer = FogRenderer(
            fog=fog,
            player_faction=player_faction,
        )
        self.map_widget.fog_renderer = self.fog_renderer

        # ── 依赖注入到子面板 ─────────────────────────────────────
        if map_data is not None:
            self.map_widget.set_map(map_data)
        if fog is not None:
            self.map_widget.set_fog(fog)
        if commander is not None:
            self.command_panel.set_commander(commander)

        # ── 地图加载 ─────────────────────────────────────────────
        if self._integrated_mode and map_data is not None:
            # 集成模式：从 IMap 读取尺寸，但先用 JSON 填充地形数据
            # （Sprint 2 过渡期：IMap 尚未完全驱动渲染）
            if not self.map_widget.load_map_from_json():
                logger.warning("集成模式下 JSON 地图加载失败")
            # 更新地图边界校验
            self.command_panel.set_map_bounds(
                map_data.width, map_data.height
            )
        else:
            # Sprint 1 独立模式
            if self.map_widget.load_map_from_json():
                logger.info("地图加载成功（独立模式）")
                # 加载后更新 CommandPanel 的坐标校验边界
                self.command_panel.set_map_bounds(
                    self.map_widget.map_width,
                    self.map_widget.map_height,
                )
            else:
                logger.warning("地图加载失败，地图区域将为空")

        # ── Sprint 2：订阅 TURN_START/TURN_END 以同步回合和迷雾 ──
        # BUG-1 fix: _on_turn_start must subscribe BEFORE battle_log so it
        # runs first and sets _current_turn before BattleLogPanel formats it.
        self._turn_counter = 0
        event_bus.subscribe(GameEventType.TURN_START, self._on_turn_start)
        event_bus.subscribe(GameEventType.TURN_END, self._on_turn_end)

        # ── 战报面板：对接真实事件或模拟输出 ────────────────────
        if self._enable_debug_log:
            # 调试模式：模拟事件输出（不订阅 EventBus）
            self.battle_log.simulate_events()
        else:
            # 真实模式：订阅 EventBus 事件
            self.battle_log.subscribe_all()
            if self._integrated_mode:
                logger.info("BattleLogPanel 已订阅 EventBus（集成模式）")
            else:
                logger.info("BattleLogPanel 已订阅 EventBus（独立模式，等待 #3 事件）")

        logger.info(
            "MainWindow 初始化完成 (%d×%d) mode=%s",
            WINDOW_WIDTH,
            WINDOW_HEIGHT,
            "integrated" if self._integrated_mode else "standalone",
        )

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

        处理顺序（按优先级）：
            1. QUIT / ESC → 退出
            2. MarkerSystem.handle_event() → 标记拖拽
            3. pygame_gui.UIManager.process_events() → UI 控件
            4. 按钮点击 → CommandPanel.on_execute_clicked()
            5. SPACE → 打印调试信息
        """
        for event in pygame.event.get():
            # ── 退出 ────────────────────────────────────────────
            if event.type == pygame.QUIT:
                self._running = False
                return

            # ── 键盘：ESC 退出 ──────────────────────────────────
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self._running = False
                    return

            # ── 标记系统事件（在 pygame_gui 之前处理，消费拖拽） ──
            # marker_system is always initialized in __init__ — no null guard needed
            consumed = self.marker_system.handle_event(event, self.map_widget)
            if consumed:
                continue

            # ── pygame_gui 事件 ─────────────────────────────────
            self._ui_manager.process_events(event)

            # ── 键盘：SPACE 调试信息 ────────────────────────────
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    sel = self.command_panel.get_selection()
                    logger.info(
                        "[调试] Frame=%d | 指令=%s 目标=%s 坐标=(%d,%d) | 标记数=%d",
                        self._frame_count,
                        sel["command"],
                        sel["unit"],
                        sel["x"],
                        sel["y"],
                        len(self.marker_system.get_all_markers()),
                    )

            # ── pygame_gui 按钮点击 ─────────────────────────────
            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == self.command_panel.button_execute:
                    cmd_data = self.command_panel.on_execute_clicked()
                    if cmd_data is not None:
                        # 同步追加到战报面板
                        self.battle_log.append_text(
                            f"📨 指令已发出：{cmd_data['unit']} → "
                            f"{cmd_data['command']} ({cmd_data['x']}, {cmd_data['y']})"
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

        # 地图渲染
        if self._integrated_mode and self._game_loop is not None:
            self.map_widget.render(self._game_loop, self._player_faction)
        else:
            self.map_widget.render()  # Sprint 1 兼容

    # ── 私有方法：渲染 ────────────────────────────────────────────

    def _render(self) -> None:
        """每帧渲染顺序（对齐 UI_SPEC §6.1）：
            背景 → 地图(地形+单位+标记+迷雾) → 面板装饰 → UI 控件
        """
        # ── 背景 ────────────────────────────────────────────────
        self._screen.fill(COLOR_BG)

        # ── 地图区域 ────────────────────────────────────────────
        self.map_widget.draw(self._screen)

        # ── 标记调色板（Sprint 2） ──────────────────────────────
        palette_x = self._layout["map_rect"].x - 48
        self.marker_system.draw_palette(
            self._screen, (palette_x, self._layout["map_rect"].y)
        )

        # ── 面板背景和分隔线 ────────────────────────────────────
        self._draw_panel_decorations()

        # ── pygame_gui 控件（必须在最后绘制，保证在最上层） ────
        self._ui_manager.draw_ui(self._screen)

        # ── 提交帧 ──────────────────────────────────────────────
        pygame.display.flip()

    def _draw_panel_decorations(self) -> None:
        """绘制面板背景和分隔线（非 pygame_gui 控件）。"""
        # BUG-2 fix: reuse stored layout instead of recalculating
        br = self._layout["battle_log_rect"]
        pygame.draw.rect(self._screen, COLOR_PANEL_BG, br)
        pygame.draw.rect(self._screen, COLOR_BORDER, br, 1)

        # 底部指令栏背景
        cr = self._layout["command_rect"]
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

        # 调色板分隔线（标记调色板 ↔ 地图）[Sprint 2]
        palette_x = self._layout["map_rect"].x - 48
        pygame.draw.line(
            self._screen, COLOR_BORDER,
            (palette_x - 2, self._layout["map_rect"].y),
            (palette_x - 2, self._layout["map_rect"].bottom),
            1,
        )

    # ── 私有方法：退出 ────────────────────────────────────────────

    def _shutdown(self) -> None:
        """清理资源并退出。"""
        logger.info("MainWindow 正在退出 (共 %d 帧)", self._frame_count)
        self.battle_log.unsubscribe_all()
        self.fog_renderer.unsubscribe_events()
        event_bus.unsubscribe(GameEventType.TURN_START, self._on_turn_start)
        event_bus.unsubscribe(GameEventType.TURN_END, self._on_turn_end)
        pygame.quit()

    # ── 事件回调 ──────────────────────────────────────────────────

    def _on_turn_start(self, _payload: object = None) -> None:
        """TURN_START 事件回调：递增回合计数并同步到战报面板。

        解决无 payload 事件（TURN_START / COMMAND_EXPIRED / HQ_UNDER_ATTACK）
        无法从 payload 获取回合数的问题。
        """
        self._turn_counter += 1
        self.battle_log.set_turn(self._turn_counter)

    def _on_turn_end(self, _payload: object = None) -> None:
        """TURN_END 事件回调：驱逐迷雾高亮区域过期。

        FogRenderer 的高亮区域有 remaining_turns 生命周期，
        每个 TURN_END 事件递减一次，3 回合后自动清除。
        """
        self.fog_renderer.on_turn_end()

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
