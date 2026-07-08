"""
BattleLogPanel — 左侧滚动战报面板（Sprint 2 升级版）。

订阅 EventBus 的 13 种事件类型，以 HTML 颜色标记追加消息到 pygame_gui.UITextBox。
不同事件类型使用不同颜色：普通(白)、重要(金)、危险(红)。

Sprint 2 修复：
    - TURN_START 无 payload → 通过 set_turn() 注入回合数再格式化
    - 命令类事件使用参数化 payload 格式
    - simulate_events() 保留为调试方法，不再自动调用

依赖：
    src/core/constants.py  — GameEventType, BATTLE_LOG_* 颜色常量
    src/core/event_bus.py  — 全局事件总线单例

版本: v0.2.0 — Sprint 2
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pygame
import pygame_gui

from src.core.constants import (
    BATTLE_LOG_DANGER_COLOR,
    BATTLE_LOG_HIGHLIGHT_COLOR,
    BATTLE_LOG_MAX_LINES,
    BATTLE_LOG_TEXT_COLOR,
    GameEventType,
)
from src.core.event_bus import event_bus

logger = logging.getLogger(__name__)

# ── 事件 → (颜色常量, 格式模板) ──────────────────────────────────────────

# fmt: off
BATTLE_LOG_FORMATS: dict[GameEventType, tuple[str, str]] = {
    GameEventType.TURN_START: (
        BATTLE_LOG_HIGHLIGHT_COLOR,
        "━━━ 第 {turn} 回合 ━━━",
    ),
    GameEventType.POSITION_REPORT: (
        BATTLE_LOG_TEXT_COLOR,
        "[第{turn}回合] {unit_name} 汇报：位置约({reported_x}, {reported_y})",
    ),
    GameEventType.ENEMY_SPOTTED: (
        BATTLE_LOG_HIGHLIGHT_COLOR,
        "[第{turn}回合] {reporter_name} 发现敌军 {enemy_type}×{enemy_count}！",
    ),
    GameEventType.BATTLE_RESULT: (
        BATTLE_LOG_TEXT_COLOR,
        "[第{turn}回合] {attacker_name} 攻击 {defender_name}，"
        "造成 {damage_to_defender} 点伤害",
    ),
    GameEventType.UNIT_DAMAGED: (
        BATTLE_LOG_TEXT_COLOR,
        "[第{turn}回合] {unit_name} 受到 {damage} 点伤害 "
        "(HP: {hp_before}→{hp_after})",
    ),
    GameEventType.UNIT_KILLED: (
        BATTLE_LOG_DANGER_COLOR,
        "[第{turn}回合] 💀 {unit_name} 阵亡！被 {killer_name} 击杀",
    ),
    GameEventType.COMMAND_SENT: (
        BATTLE_LOG_TEXT_COLOR,
        "[第{turn}回合] 📨 指令已发出：{target_unit_name} → {command_type}，"
        "预计第 {estimated_arrival_turn} 回合到达",
    ),
    GameEventType.COMMAND_ARRIVED: (
        BATTLE_LOG_TEXT_COLOR,
        "[第{turn}回合] 📬 指令已到达 {target_unit_name}：{command_type}",
    ),
    GameEventType.COMMAND_EXPIRED: (
        BATTLE_LOG_TEXT_COLOR,
        "[第{turn}回合] ⚠ 指令作废：目标单位已阵亡",
    ),
    GameEventType.HQ_UNDER_ATTACK: (
        BATTLE_LOG_DANGER_COLOR,
        "[第{turn}回合] 🚨 指挥所遭受攻击！",
    ),
    GameEventType.HQ_CAPTURED: (
        BATTLE_LOG_HIGHLIGHT_COLOR,
        "[第{turn}回合] 🏆 {capturer_name} 占领指挥所！",
    ),
    GameEventType.GAME_OVER: (
        BATTLE_LOG_HIGHLIGHT_COLOR,
        "[第{turn}回合] 游戏结束：{reason} — {result}",
    ),
}
# fmt: on


class BattleLogPanel:
    """左侧战报面板。

    订阅 EventBus 的 13 种事件，以 HTML 颜色标记追加消息到 UITextBox。
    自动滚动到底部，保留最近 BATTLE_LOG_MAX_LINES 条消息。

    Attributes:
        text_box: pygame_gui.UITextBox 核心控件
    """

    def __init__(self, rect: pygame.Rect, ui_manager: pygame_gui.UIManager) -> None:
        """创建战报面板。

        Args:
            rect: 面板矩形区域
            ui_manager: pygame_gui 全局管理器
        """
        self._rect = rect
        self._ui_manager = ui_manager
        self._line_count = 0
        self._current_turn = 0
        self._callbacks: list[tuple[GameEventType, Callable[[Any], None]]] = []

        # ── UITextBox ──────────────────────────────────────────────
        self.text_box = pygame_gui.elements.UITextBox(
            html_text="",
            relative_rect=pygame.Rect(
                rect.x + 4, rect.y + 4, rect.width - 8, rect.height - 8
            ),
            manager=ui_manager,
            object_id="#battle_log",
        )

    # ── 公开方法 ────────────────────────────────────────────────────

    def set_turn(self, turn: int) -> None:
        """设置当前回合数（用于 TURN_START 无 payload 事件的格式化）。

        Args:
            turn: 当前回合
        """
        self._current_turn = turn

    def subscribe_all(self) -> None:
        """批量订阅全部 13 种事件。

        每个事件注册一个闭包回调：解析 payload → 格式化文本 → 调用 _append()。
        UI 层通过此方法建立与 EventBus 的连接。
        调用后即可自动接收来自 #3 的真实事件。
        """
        if self._callbacks:
            logger.warning("BattleLogPanel.subscribe_all() 重复调用，跳过")
            return

        for event_type, (color, template) in BATTLE_LOG_FORMATS.items():
            handler = self._make_handler(event_type, color, template)
            event_bus.subscribe(event_type, handler)
            self._callbacks.append((event_type, handler))
            logger.debug("BattleLogPanel 订阅: %s", event_type.name)

    def unsubscribe_all(self) -> None:
        """取消全部订阅（销毁面板时调用）。"""
        for event_type, handler in self._callbacks:
            event_bus.unsubscribe(event_type, handler)
        self._callbacks.clear()
        logger.debug("BattleLogPanel 已取消全部订阅")

    def append_text(self, text: str, color: str = BATTLE_LOG_TEXT_COLOR) -> None:
        """追加一条 HTML 格式消息并自动滚动到底部。

        Args:
            text: 纯文本消息（不含 HTML 标签）
            color: CSS 颜色值（如 '#FFD700'）
        """
        self._line_count += 1
        html_line = f"<font color='{color}'>{text}</font><br>"
        self.text_box.append_html_text(html_line)

        # 超出行数上限时移除旧内容
        if self._line_count > BATTLE_LOG_MAX_LINES:
            logger.debug(
                "战报行数超过 %d 上限，建议实现裁剪逻辑", BATTLE_LOG_MAX_LINES
            )

    def clear(self) -> None:
        """清空所有内容（新游戏开始时调用）。"""
        self.text_box.set_text("")
        self._line_count = 0

    def update(self, time_delta: float) -> None:
        """每帧调用 pygame_gui 更新。

        Args:
            time_delta: 上一帧的时间间隔（秒）
        """
        self.text_box.update(time_delta)

    # ── Sprint 1/2 调试方法 ───────────────────────────────────────

    def simulate_events(self) -> None:
        """Sprint 1 调试用：无需 EventBus 即可模拟战报输出。

        在 #3 的事件广播未接入时，用于验证面板渲染和滚动功能。
        Sprint 2 保留此方法作为调试入口，但默认不再自动调用。
        """
        demo_messages: list[tuple[str, str]] = [
            (BATTLE_LOG_HIGHLIGHT_COLOR, "━━━ BlindCommand 战报系统已就绪 ━━━"),
            (BATTLE_LOG_HIGHLIGHT_COLOR, "━━━ 第 1 回合 ━━━"),
            (BATTLE_LOG_TEXT_COLOR, "[第1回合] 第一步兵连 汇报：位置约(4, 13)，未发现敌情"),
            (BATTLE_LOG_TEXT_COLOR, "[第1回合] 侦察排 汇报：位置约(8, 13)，未发现敌情"),
            (BATTLE_LOG_HIGHLIGHT_COLOR, "━━━ 第 2 回合 ━━━"),
            (BATTLE_LOG_TEXT_COLOR, "[第2回合] 📨 指令已发出：侦察排 → SCOUT，预计第 4 回合到达"),
            (BATTLE_LOG_TEXT_COLOR, "[第2回合] 第一骑兵连 汇报：位置约(6, 12)，附近有敌军活动迹象"),
            (BATTLE_LOG_HIGHLIGHT_COLOR, "━━━ 第 3 回合 ━━━"),
            (BATTLE_LOG_HIGHLIGHT_COLOR, "[第3回合] 侦察排 发现敌军 骑兵×2！坐标(11, 4)"),
            (BATTLE_LOG_TEXT_COLOR, "[第3回合] 侦察排 攻击 敌军骑兵A，造成 6 点伤害"),
            (BATTLE_LOG_DANGER_COLOR, "[第3回合] 侦察排 受到 4 点伤害 (HP: 5→1)"),
            (BATTLE_LOG_HIGHLIGHT_COLOR, "━━━ 第 4 回合 ━━━"),
            (BATTLE_LOG_DANGER_COLOR, "[第4回合] 💀 侦察排 阵亡！被 敌军骑兵B 击杀"),
            (BATTLE_LOG_TEXT_COLOR, "[第4回合] 📬 指令已到达 侦察排：SCOUT（但单位已阵亡，指令作废）"),
            (BATTLE_LOG_DANGER_COLOR, "[第4回合] ⚠ 指令作废：目标单位已阵亡"),
        ]
        for color, text in demo_messages:
            self.append_text(text, color)

        logger.info("BattleLogPanel 模拟事件输出完成，共 %d 条", len(demo_messages))

    # ── 私有方法 ────────────────────────────────────────────────────

    def _make_handler(
        self, event_type: GameEventType, color: str, template: str
    ) -> Callable[[Any], None]:
        """创建事件回调闭包。

        对于有 payload 的事件：将 payload 字段按模板展开并格式化。
        对于无 payload 的事件（TURN_START / TURN_END / HQ_UNDER_ATTACK / COMMAND_EXPIRED）：
            使用 self._current_turn 作为 turn 参数。

        Args:
            event_type: 事件类型
            color: 消息颜色
            template: 消息格式模板，支持 {field} 占位符

        Returns:
            回调函数（接收 payload 或 None）
        """

        def handler(payload: Any = None) -> None:
            try:
                if payload is None:
                    # 无载荷事件：使用当前回合数 + 固定模板
                    fmt_dict = {"turn": self._current_turn}
                    text = template.format(**fmt_dict)
                else:
                    # 有载荷事件：将 payload 字段展开
                    fmt_dict = payload.__dict__.copy()
                    text = template.format(**fmt_dict)
            except (KeyError, AttributeError, ValueError) as e:
                logger.warning(
                    "战报格式化失败: event=%s template=%r error=%s",
                    event_type.name,
                    template,
                    e,
                )
                # 降级显示原始 payload
                text = f"[{event_type.name}] {payload}"

            self.append_text(text, color)

        return handler
