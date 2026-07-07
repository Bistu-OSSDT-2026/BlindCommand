"""
CommandPanel — 底部指令选择栏。

提供指令类型选择、目标单位选择、坐标输入和执行按钮。
Sprint 1 为 UI 骨架（菜单可展开、按钮可点击打印日志），
Sprint 2 对接 ICommander 事件实现真实指令下达。
"""

import logging
from typing import Optional

import pygame
import pygame_gui

from src.core.constants import (
    COMMAND_PANEL_BG_COLOR,
    COMMAND_PANEL_HEIGHT,
    CommandType,
)

logger = logging.getLogger(__name__)

# ── 指令下拉选项 ──────────────────────────────────────────────────────

COMMAND_OPTIONS: list[str] = [cmd.value for cmd in CommandType]

# ── 占位单位列表（Sprint 1 无真实数据时使用） ──────────────────────────

PLACEHOLDER_UNITS: list[str] = ["第一步兵连", "第二步兵连", "第一骑兵连", "第一炮兵连", "侦察排"]


class CommandPanel:
    """底部指令选择栏。

    Sprint 1 功能：
    - 指令类型下拉菜单（7 种指令）
    - 目标单位下拉菜单（占位列表）
    - 坐标 X / Y 输入框
    - 执行按钮（点击打印日志）
    """

    def __init__(self, rect: pygame.Rect, ui_manager: pygame_gui.UIManager) -> None:
        """创建指令面板控件。

        Args:
            rect: 面板矩形区域
            ui_manager: pygame_gui 全局管理器
        """
        self._rect = rect
        self._ui_manager = ui_manager
        self._available_units: list[str] = PLACEHOLDER_UNITS.copy()

        # ── 布局计算 ──────────────────────────────────────────────
        # 水平排列：指令 | 单位 | X | Y | 执行
        margin = 8
        item_h = 36
        item_y = rect.top + (COMMAND_PANEL_HEIGHT - item_h) // 2

        dropdown_w = 130
        input_w = 60
        btn_w = 120
        label_w = 30

        cur_x = rect.left + margin

        # ── 标签：指令 ────────────────────────────────────────────
        self._label_cmd = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(cur_x, item_y - 4, 40, item_h),
            text="指令:",
            manager=ui_manager,
        )
        cur_x += 40

        # ── 指令类型下拉菜单 ──────────────────────────────────────
        self.dropdown_command = pygame_gui.elements.UIDropDownMenu(
            options_list=COMMAND_OPTIONS,
            starting_option=CommandType.MOVE.value,
            relative_rect=pygame.Rect(cur_x, item_y, dropdown_w, item_h),
            manager=ui_manager,
        )
        cur_x += dropdown_w + margin

        # ── 标签：目标 ────────────────────────────────────────────
        self._label_unit = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(cur_x, item_y - 4, 40, item_h),
            text="目标:",
            manager=ui_manager,
        )
        cur_x += 40

        # ── 目标单位下拉菜单 ──────────────────────────────────────
        self.dropdown_unit = pygame_gui.elements.UIDropDownMenu(
            options_list=self._available_units,
            starting_option=self._available_units[0],
            relative_rect=pygame.Rect(cur_x, item_y, dropdown_w, item_h),
            manager=ui_manager,
        )
        cur_x += dropdown_w + margin

        # ── 标签：X ───────────────────────────────────────────────
        self._label_x = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(cur_x, item_y - 4, label_w, item_h),
            text="X:",
            manager=ui_manager,
        )
        cur_x += label_w

        # ── 坐标 X 输入框 ─────────────────────────────────────────
        self.entry_x = pygame_gui.elements.UITextEntryLine(
            relative_rect=pygame.Rect(cur_x, item_y, input_w, item_h),
            manager=ui_manager,
        )
        self.entry_x.set_text("0")
        cur_x += input_w + margin

        # ── 标签：Y ───────────────────────────────────────────────
        self._label_y = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(cur_x, item_y - 4, label_w, item_h),
            text="Y:",
            manager=ui_manager,
        )
        cur_x += label_w

        # ── 坐标 Y 输入框 ─────────────────────────────────────────
        self.entry_y = pygame_gui.elements.UITextEntryLine(
            relative_rect=pygame.Rect(cur_x, item_y, input_w, item_h),
            manager=ui_manager,
        )
        self.entry_y.set_text("0")
        cur_x += input_w + margin * 2

        # ── 执行按钮 ──────────────────────────────────────────────
        self.button_execute = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(cur_x, item_y, btn_w, item_h),
            text="▶ 执行指令",
            manager=ui_manager,
        )

        logger.info("CommandPanel 初始化完成，%d 个控件", 8)

    # ── 公开方法 ────────────────────────────────────────────────────

    def set_available_units(self, unit_names: list[str]) -> None:
        """更新可选单位列表。

        Args:
            unit_names: 存活友军单位名称列表
        """
        self._available_units = unit_names
        self.dropdown_unit.kill()
        self.dropdown_unit = pygame_gui.elements.UIDropDownMenu(
            options_list=unit_names,
            starting_option=unit_names[0] if unit_names else "—",
            relative_rect=self.dropdown_unit.rect,
            manager=self._ui_manager,
        )
        logger.debug("单位列表已更新: %s", unit_names)

    def get_selection(self) -> dict:
        """获取当前选中的指令参数。

        Returns:
            {
                "command": str,    # 指令类型值
                "unit": str,       # 目标单位名称
                "x": int,          # 目标 X 坐标
                "y": int,          # 目标 Y 坐标
            }
        """
        try:
            x = int(self.entry_x.get_text())
        except ValueError:
            x = 0
        try:
            y = int(self.entry_y.get_text())
        except ValueError:
            y = 0

        return {
            "command": self.dropdown_command.selected_option,
            "unit": self.dropdown_unit.selected_option,
            "x": x,
            "y": y,
        }

    def on_execute_clicked(self) -> None:
        """执行按钮回调。

        Sprint 1: 打印选中参数到日志（等待 #3 ICommander 对接后改为事件广播）。
        """
        sel = self.get_selection()
        logger.info(
            "指令执行(模拟): %s → %s (%d, %d)",
            sel["command"],
            sel["unit"],
            sel["x"],
            sel["y"],
        )

    def update(self, time_delta: float) -> None:
        """每帧更新（预留扩展点）。

        Args:
            time_delta: 上一帧的时间间隔（秒）
        """
        # pygame_gui 控件由 UIManager 统一驱动
        pass

    # ── 私有方法 ────────────────────────────────────────────────────

    def _get_placeholder_unit(self, index: int) -> str:
        """获取占位单位名称（Sprint 1 用）。"""
        if 0 <= index < len(self._available_units):
            return self._available_units[index]
        return "—"
