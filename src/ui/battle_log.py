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
from collections import deque
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
        # Sprint 3: 消息缓冲区 (html_line, color)，用于裁剪和重建
        self._line_buffer: deque[tuple[str, str]] = deque()
        self._trim_batch_size = 50  # 每超出 50 行触发一次裁剪重建

        # Sprint 3: 最新消息高亮
        # (line_index, highlight_start_time, final_color)
        self._highlighted_lines: list[tuple[int, float, str]] = []
        self._highlight_duration: float = 2.0  # 高亮持续秒数
        self._highlight_rebuild_timer: float = 0.0  # 距离下次重建的计时器

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

        每 BATTLE_LOG_MAX_LINES 行为上限，超出时裁剪最旧的消息。
        采用缓冲 + 批量重建策略：超出上限的增量超过 _trim_batch_size 行时才重建，
        避免每行都触发昂贵的 set_text() 操作。

        Args:
            text: 纯文本消息（不含 HTML 标签）
            color: CSS 颜色值（如 '#FFD700'）
        """
        self._line_count += 1
        html_line = f"<font color='{color}'>{text}</font><br>"
        self._line_buffer.append((html_line, color))
        self.text_box.append_html_text(html_line)

        # Sprint 3: 记录新消息用于高亮渐变
        self._highlighted_lines.append((
            self._line_count - 1,
            pygame.time.get_ticks() / 1000.0,
            color,
        ))

        # Sprint 3: 实际裁剪（替代只 log 警告的旧实现）
        overflow = self._line_count - BATTLE_LOG_MAX_LINES
        if overflow > 0 and overflow % self._trim_batch_size == 0:
            self._trim_old_lines(overflow)

    def _trim_old_lines(self, overflow: int) -> None:
        """裁剪最旧的超出行数，用 set_text 重建 UITextBox。

        保留最近 BATTLE_LOG_MAX_LINES 条消息。
        Bug 1 fix: 同步调整 _highlighted_lines 的索引偏移。

        Args:
            overflow: 超出 BATTLE_LOG_MAX_LINES 的行数
        """
        drop_count = overflow
        while drop_count > 0 and self._line_buffer:
            self._line_buffer.popleft()
            drop_count -= 1

        # Bug 1 fix: 同步偏移高亮索引
        actual_dropped = overflow - drop_count
        if actual_dropped > 0:
            new_highlights: list[tuple[int, float, str]] = []
            for line_idx, start_time, final_color in self._highlighted_lines:
                shifted = line_idx - actual_dropped
                if shifted >= 0:
                    new_highlights.append((shifted, start_time, final_color))
                # shifted < 0 意味着该高亮对应的行已被删除 → 丢弃
            self._highlighted_lines = new_highlights

        self._line_count = len(self._line_buffer)

        # 重建 UITextBox 内容
        rebuilt = "".join(line for line, _ in self._line_buffer)
        self.text_box.set_text(rebuilt)
        logger.debug(
            "BattleLog 裁剪完成: 保留 %d 行 (上限 %d)",
            self._line_count,
            BATTLE_LOG_MAX_LINES,
        )

    def clear(self) -> None:
        """清空所有内容（新游戏开始时调用）。"""
        self.text_box.set_text("")
        self._line_count = 0
        self._line_buffer.clear()
        self._highlighted_lines.clear()
        self._highlight_rebuild_timer = 0.0  # Bug 2 fix: reset timer

    def update(self, time_delta: float) -> None:
        """每帧调用 pygame_gui 更新。Sprint 3: 处理消息高亮过期。

        Args:
            time_delta: 上一帧的时间间隔（秒）
        """
        self.text_box.update(time_delta)

        # Sprint 3: 高亮渐变 — 每 0.5 秒检查是否需要重建
        self._highlight_rebuild_timer += time_delta
        if self._highlight_rebuild_timer >= 0.5 and self._highlighted_lines:
            self._highlight_rebuild_timer = 0.0
            self._recolor_highlights()

    def _recolor_highlights(self) -> None:
        """将已过期的高亮消息从白色渐变到最终颜色。"""
        now_sec = pygame.time.get_ticks() / 1000.0
        dirty = False
        new_highlights: list[tuple[int, float, str]] = []

        for line_idx, start_time, final_color in self._highlighted_lines:
            age = now_sec - start_time
            if age >= self._highlight_duration:
                dirty = True  # 过期 → 重建移除高亮
            else:
                new_highlights.append((line_idx, start_time, final_color))

        self._highlighted_lines = new_highlights

        # Bug 4 fix: 仅在确实有变化时重建
        if dirty and self._line_buffer:
            self._rebuild_with_colors()

    def _rebuild_with_colors(self) -> None:
        """用当前高亮颜色重建 UITextBox。

        对仍在高亮期的消息用亮色，其余用最终颜色。
        高亮色 = lerp(白色, 最终色, age/duration)。
        """
        now_sec = pygame.time.get_ticks() / 1000.0
        # 构建当前活跃高亮的快速索引
        active: dict[int, tuple[float, str]] = {}
        for line_idx, start_time, final_color in self._highlighted_lines:
            active[line_idx] = (start_time, final_color)

        rebuilt_parts: list[str] = []
        for i, (html_line, stored_color) in enumerate(self._line_buffer):
            if i in active:
                start_time, final_color = active[i]
                age = now_sec - start_time
                t = min(1.0, age / self._highlight_duration)  # 0→1
                # lerp from white (#FFFFFF) to final_color
                blended = self._lerp_color("#FFFFFF", final_color, t)
                # Reconstruct HTML with blended color
                text = html_line.replace(f"color='{stored_color}'", f"color='{blended}'", 1)
                rebuilt_parts.append(text)
            else:
                rebuilt_parts.append(html_line)

        self.text_box.set_text("".join(rebuilt_parts))

    @staticmethod
    def _lerp_color(c1: str, c2: str, t: float) -> str:
        """线性插值两个 CSS 十六进制颜色。

        Args:
            c1: 起始颜色 (如 '#FFFFFF')
            c2: 目标颜色 (如 '#CCCCCC')
            t: 0.0=c1, 1.0=c2

        Returns:
            插值后的颜色字符串
        """
        def _parse(hex_str: str) -> tuple[int, int, int]:
            h = hex_str.lstrip("#")
            # Bug 3 fix: 处理 3 位和 6 位十六进制
            if len(h) == 3:
                h = h[0]*2 + h[1]*2 + h[2]*2
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

        r1, g1, b1 = _parse(c1)
        r2, g2, b2 = _parse(c2)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02X}{g:02X}{b:02X}"

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
