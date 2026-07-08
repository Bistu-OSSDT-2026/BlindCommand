"""
CommandPanel — 底部指令选择栏（Sprint 2 升级版）。

提供指令类型选择、目标单位选择、坐标输入和执行按钮。
Sprint 2 新增：
    - 坐标输入校验（地图边界检查）
    - 结构化 get_command_data() 返回
    - 通过 ICommander 接口下达真实指令（由 MainWindow 注入）
    - 执行按钮状态反馈（禁用/启用/错误提示）

依赖：
    src/core/constants.py  — CommandType, COMMAND_PANEL_HEIGHT, ...
    src/core/interfaces.py — ICommander, ICommand（通过 MainWindow 注入）

版本: v0.2.0 — Sprint 2
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import pygame
import pygame_gui

from src.core.constants import (
    COMMAND_PANEL_BG_COLOR,
    COMMAND_PANEL_HEIGHT,
    CommandType,
    MAP_DEFAULT_HEIGHT,
    MAP_DEFAULT_WIDTH,
)

if TYPE_CHECKING:
    from src.core.interfaces import ICommander

logger = logging.getLogger(__name__)

# ── 指令下拉选项 ──────────────────────────────────────────────────────

COMMAND_OPTIONS: list[str] = [cmd.value for cmd in CommandType]

# ── 占位单位列表（Sprint 1 无真实数据时使用） ──────────────────────────

PLACEHOLDER_UNITS: list[str] = ["第一步兵连", "第二步兵连", "第一骑兵连", "第一炮兵连", "侦察排"]


class CommandPanel:
    """底部指令选择栏。

    Sprint 2 功能：
        - 指令类型下拉菜单（7 种指令）
        - 目标单位下拉菜单（动态更新）
        - 坐标 X / Y 输入框（含边界校验）
        - 执行按钮（对接 ICommander 或回调）
        - 状态消息标签（反馈执行结果）
    """

    def __init__(
        self,
        rect: pygame.Rect,
        ui_manager: pygame_gui.UIManager,
        map_width: int = MAP_DEFAULT_WIDTH,
        map_height: int = MAP_DEFAULT_HEIGHT,
    ) -> None:
        """创建指令面板控件。

        Args:
            rect: 面板矩形区域
            ui_manager: pygame_gui 全局管理器
            map_width: 地图最大 X 坐标（用于输入校验）
            map_height: 地图最大 Y 坐标（用于输入校验）
        """
        self._rect = rect
        self._ui_manager = ui_manager
        self._available_units: list[str] = PLACEHOLDER_UNITS.copy()
        self._map_width = map_width
        self._map_height = map_height
        self._commander: Optional[ICommander] = None

        # ── 布局计算 ──────────────────────────────────────────────
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

        # ── 状态标签（显示校验错误或执行结果） ────────────────────
        self._label_status = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect(
                cur_x + btn_w + margin,
                item_y,
                200,
                item_h,
            ),
            text="",
            manager=ui_manager,
        )

        logger.info("CommandPanel 初始化完成，%d 个控件", 9)

    # ── 公开方法 ────────────────────────────────────────────────────

    def set_commander(self, commander: ICommander | None) -> None:
        """注入指令系统接口（由 MainWindow 调用）。

        Args:
            commander: #3 提供的 ICommander 实例，None 表示无对接
        """
        self._commander = commander
        if commander is not None:
            logger.info("CommandPanel 已绑定 ICommander")
        else:
            logger.debug("CommandPanel 运行在模拟模式（无 ICommander）")

    def set_available_units(self, unit_names: list[str]) -> None:
        """更新可选单位列表。

        Args:
            unit_names: 存活友军单位名称列表
        """
        self._available_units = unit_names
        self.dropdown_unit.kill()
        self.dropdown_unit = pygame_gui.elements.UIDropDownMenu(
            options_list=unit_names if unit_names else ["—"],
            starting_option=unit_names[0] if unit_names else "—",
            relative_rect=self.dropdown_unit.rect,
            manager=self._ui_manager,
        )
        logger.debug("单位列表已更新: %s", unit_names)

    def set_map_bounds(self, width: int, height: int) -> None:
        """更新地图边界（用于坐标校验）。

        Args:
            width: 地图宽度
            height: 地图高度
        """
        self._map_width = width
        self._map_height = height

    def get_selection(self) -> dict:
        """获取当前选中的指令参数。

        Returns:
            {
                "command": str,    # 指令类型值（如 "MOVE"）
                "unit": str,       # 目标单位名称
                "x": int,          # 目标 X 坐标
                "y": int,          # 目标 Y 坐标
            }
        """
        try:
            x = int(self.entry_x.get_text())
        except ValueError:
            x = -1
        try:
            y = int(self.entry_y.get_text())
        except ValueError:
            y = -1

        return {
            "command": self.dropdown_command.selected_option,
            "unit": self.dropdown_unit.selected_option,
            "x": x,
            "y": y,
        }

    def get_command_data(self) -> dict | None:
        """获取经过校验的结构化指令数据。

        校验规则：
            - 坐标 X 必须在 [0, map_width) 范围内
            - 坐标 Y 必须在 [0, map_height) 范围内
            - 目标单位不能是占位符 "—"

        Returns:
            校验通过的指令 dict，或 None（校验失败）
        """
        sel = self.get_selection()

        errors: list[str] = []

        if sel["unit"] == "—" or not sel["unit"]:
            errors.append("请选择目标单位")

        if sel["x"] < 0 or sel["x"] >= self._map_width:
            errors.append(f"X 坐标需在 0~{self._map_width - 1} 之间")
        if sel["y"] < 0 or sel["y"] >= self._map_height:
            errors.append(f"Y 坐标需在 0~{self._map_height - 1} 之间")

        if errors:
            self._set_status(" ⚠ " + "；".join(errors), "#FF4444")
            logger.warning("指令参数校验失败: %s", errors)
            return None

        # 校验通过
        self._set_status(" ✓ 指令参数有效", "#44FF44")
        return sel

    def on_execute_clicked(self) -> dict | None:
        """执行按钮回调。

        Sprint 2 行为：
            1. 调用 get_command_data() 校验参数
            2. 若校验通过且 commander 存在 → 调用 commander.issue_command()
            3. 若校验通过但 commander 不存在 → 返回指令数据（由 MainWindow 处理）
            4. 若校验失败 → 显示错误，返回 None

        Returns:
            校验通过的指令 dict，或 None
        """
        cmd_data = self.get_command_data()
        if cmd_data is None:
            return None

        if self._commander is not None:
            # ── Sprint 2：通过 ICommander 下达真实指令 ──────────────
            try:
                unit_name = cmd_data["unit"]
                # 查找单位 ID（简化：直接使用名称匹配 — #3 应提供更好的匹配）
                params: dict = {"x": cmd_data["x"], "y": cmd_data["y"]}
                # 注：需要 unit_id 而非 name，此处为简化对接。
                # #3 的 Commander 若能通过 name 查找，则此处可行；
                # 否则需由 MainWindow 做 name→id 转换后调用。
                success = self._commander.issue_command(
                    unit_id=unit_name,  # Sprint 2 简化：用名称作为 ID
                    command_type=CommandType(cmd_data["command"]),
                    params=params,
                )
                if success:
                    self._set_status(
                        f" ✓ 指令已发出：{unit_name} → {cmd_data['command']}",
                        "#44FF44",
                    )
                    logger.info(
                        "指令已发出: %s → %s (%d,%d)",
                        unit_name,
                        cmd_data["command"],
                        cmd_data["x"],
                        cmd_data["y"],
                    )
                else:
                    self._set_status(" ⚠ 指令发送失败", "#FF4444")
                    return None
            except Exception as e:
                self._set_status(f" ⚠ 错误: {e}", "#FF4444")
                logger.exception("指令执行异常")
                return None
        else:
            # ── Sprint 1 兼容模式：仅日志 ───────────────────────────
            logger.info(
                "指令执行(模拟): %s → %s (%d, %d)",
                cmd_data["command"],
                cmd_data["unit"],
                cmd_data["x"],
                cmd_data["y"],
            )
            self._set_status(
                f" (模拟) {cmd_data['unit']} → {cmd_data['command']}",
                "#FFD700",
            )

        return cmd_data

    def update(self, time_delta: float) -> None:
        """每帧更新（预留扩展点）。

        Args:
            time_delta: 上一帧的时间间隔（秒）
        """
        # pygame_gui 控件由 UIManager 统一驱动
        pass

    # ── 私有方法 ────────────────────────────────────────────────────

    def _set_status(self, text: str, color: str = "#CCCCCC") -> None:
        """设置状态标签文本和颜色。

        Args:
            text: 状态文本
            color: HTML 颜色值
        """
        self._label_status.set_text(f"<font color='{color}'>{text}</font>")

    def _get_placeholder_unit(self, index: int) -> str:
        """获取占位单位名称（Sprint 1 用）。"""
        if 0 <= index < len(self._available_units):
            return self._available_units[index]
        return "—"
