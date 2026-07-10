"""
BattleLogPanel — RTT 战报面板（原生 pygame 渲染，支持中文）
============================================================
使用 simhei.ttf 渲染中文战报。滚动文本区域。
"""

from __future__ import annotations

import logging
from typing import Callable, Any, Optional

import pygame

from src.core.constants import (
    BATTLE_LOG_MAX_LINES,
    GameEventType,
    TerrainType,
)
from src.core.event_bus import event_bus

logger = logging.getLogger(__name__)

import random

# ── 战斗中战报用语池 ──────────────────────────────────────────────

_SITUATION = ["我军占优", "势均力敌", "我军受创", "危急"]
_INTENSITY = ["轻微交火", "交战中", "激战中", "损失惨重"]

_rng = random.Random()
COLOR_BG = (26, 26, 26)
COLOR_TEXT = (204, 204, 204)
COLOR_HIGHLIGHT = (255, 215, 0)
COLOR_DANGER = (255, 68, 68)
COLOR_BORDER = (60, 60, 60)

FONT_PATH = "C:/Windows/Fonts/simhei.ttf"
FONT_SIZE = 13
LINE_HEIGHT = 18
PADDING = 6
MAX_VISIBLE = 40


class BattleLogPanel:
    """战报面板——原生 pygame 渲染，支持中文。"""

    def __init__(self, rect: pygame.Rect) -> None:
        self._rect = rect
        self._messages: list[tuple[str, tuple[int, int, int]]] = []
        self._font: pygame.font.Font | None = None
        self._surface = pygame.Surface((rect.width, rect.height))
        self._callbacks: list = []
        self._terrain_data = None
        self._map_w = 0
        self._map_h = 0
        self._scroll_offset = 0

        try:
            self._font = pygame.font.Font(FONT_PATH, FONT_SIZE)
        except Exception:
            self._font = pygame.font.Font(None, FONT_SIZE)
        logger.info("BattleLogPanel 初始化 (font=%s)", "simhei" if self._font else "default")

    # ── 公开方法 ────────────────────────────────────────────────────

    def append_text(self, text: str, color_hex: str = "#CCCCCC") -> None:
        """追加一条战报。"""
        color = _hex_to_rgb(color_hex)
        self._messages.append((text, color))
        if len(self._messages) > BATTLE_LOG_MAX_LINES:
            self._messages = self._messages[-BATTLE_LOG_MAX_LINES:]

    def clear(self) -> None:
        self._messages.clear()
        self._scroll_offset = 0

    def update(self, time_delta: float) -> None:
        pass

    def subscribe_all(self) -> None:
        """订阅所有游戏事件。"""
        handlers = {
            GameEventType.POSITION_REPORT: self._on_position_report,
            GameEventType.ENEMY_SPOTTED: self._on_enemy_spotted,
            GameEventType.BATTLE_RESULT: self._on_battle_result,
            GameEventType.UNIT_KILLED: self._on_unit_killed,
            GameEventType.HQ_CAPTURED: self._on_hq_captured,
            GameEventType.HQ_UNDER_ATTACK: self._on_hq_attacked,
            GameEventType.GAME_OVER: self._on_game_over,
        }
        for event_type, handler in handlers.items():
            event_bus.subscribe(event_type, handler)
            self._callbacks.append((event_type, handler))

    def set_terrain(self, data, w: int, h: int) -> None:
        self._terrain_data = data
        self._map_w = w
        self._map_h = h

    def _on_position_report(self, payload) -> None:
        name = getattr(payload, "unit_name", "?")
        x = getattr(payload, "reported_x", 0)
        y = getattr(payload, "reported_y", 0)
        if self._terrain_data:
            desc = describe_position(self._terrain_data, x, y, self._map_w, self._map_h)
            self._messages.append((f"{name} 汇报：我部{desc}", COLOR_TEXT))
        else:
            self._messages.append((f"{name} 汇报", COLOR_TEXT))

    def _on_enemy_spotted(self, payload) -> None:
        name = getattr(payload, "reporter_name", "?")
        etype = getattr(payload, "enemy_type", "")
        text = f"{name} 汇报：遭遇敌军"
        if etype:
            text += f" {etype}"
        text += "，交火中！"
        self._messages.append((text, COLOR_HIGHLIGHT))

    def _on_battle_result(self, payload) -> None:
        a = getattr(payload, "attacker_name", "")
        d = getattr(payload, "defender_name", "")
        fa = getattr(payload, "attacker_faction", "")
        sit = _rng.choice(_SITUATION)
        intens = _rng.choice(_INTENSITY)
        if fa == "FRIENDLY":
            self._messages.append(
                (f"⚔ {a} 汇报：与 {d}{intens}，{sit}！", COLOR_HIGHLIGHT))
        else:
            self._messages.append((f"交战中——{intens}，{sit}。", COLOR_TEXT))

    def _on_unit_killed(self, payload) -> None:
        name = ""
        if payload is not None:
            name = getattr(payload, "unit_name", "")
        if name:
            self._messages.append((f"💀 {name} 阵亡！", COLOR_DANGER))
        else:
            self._messages.append(("💀 有部队阵亡", COLOR_DANGER))

    def _on_command_arrived(self, payload) -> None:
        name = getattr(payload, "target_unit_name", "")
        # 只汇报友军
        if "敌军" not in name and "指挥部" not in name:
            self._messages.append((f"📬 {name} 开始行动", COLOR_TEXT))

    def _on_hq_attacked(self, payload) -> None:
        self._messages.append(("🚨 我军指挥部遭受攻击！", COLOR_DANGER))

    def _on_hq_captured(self, payload) -> None:
        name = getattr(payload, "capturer_name", "?")
        self._messages.append((f"🏆 {name} 占领指挥所！", COLOR_HIGHLIGHT))

    def _on_game_over(self, payload) -> None:
        self._messages.append(("游戏结束", COLOR_HIGHLIGHT))

    def unsubscribe_all(self) -> None:
        for event_type, cb in self._callbacks:
            event_bus.unsubscribe(event_type, cb)
        self._callbacks.clear()

    # ── 渲染 ────────────────────────────────────────────────────────

    def draw(self, screen: pygame.Surface) -> None:
        self._surface.fill(COLOR_BG)
        if self._font is None:
            screen.blit(self._surface, self._rect.topleft)
            return

        max_visible = (self._rect.height - PADDING * 2) // LINE_HEIGHT
        total = len(self._messages)
        self._scroll_offset = max(0, min(self._scroll_offset, total - max_visible))
        start = max(0, total - max_visible - self._scroll_offset)

        y = PADDING
        for text, color in self._messages[start:]:
            if y > self._rect.height - LINE_HEIGHT:
                break
            max_chars = (self._rect.width - PADDING * 2) // max(1, FONT_SIZE // 2)
            if len(text) > max_chars:
                text = text[:max_chars - 2] + ".."
            surf = self._font.render(text, True, color)
            self._surface.blit(surf, (PADDING, y))
            y += LINE_HEIGHT

        pygame.draw.rect(self._surface, COLOR_BORDER, (0, 0, self._rect.width, self._rect.height), 1)
        screen.blit(self._surface, self._rect.topleft)

    def handle_scroll(self, direction: int) -> None:
        """direction: +1 向下滚, -1 向上滚"""
        self._scroll_offset += direction * 3

    # ── 调试 ────────────────────────────────────────────────────────

    def simulate_events(self) -> None:
        """模拟战报输出（调试用）。"""
        msgs = [
            (COLOR_HIGHLIGHT, "━━━ 我军已就位，等待命令 ━━━"),
            (COLOR_TEXT, "第一步兵连 汇报：我部在指挥所附近，未发现敌情"),
            (COLOR_TEXT, "侦察排 汇报：我部在开阔地带，一切正常"),
        ]
        for color, text in msgs:
            self._messages.append((text, color))


# ── 辅助 ────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return (204, 204, 204)


_TERRAIN_NAMES = {0: "平原", 1: "森林", 2: "山地", 3: "河流", 4: "指挥所", 5: "桥梁"}


def describe_position(terrain_data, x: int, y: int, w: int, h: int) -> str:
    """用地形参照描述坐标位置。扫描周围 5 格找最近地标。"""
    landmarks = []
    for dy in range(-5, 6):
        for dx in range(-5, 6):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and terrain_data[ny][nx] in (1, 2, 3, 4):
                dist = max(abs(dx), abs(dy))
                t_name = _TERRAIN_NAMES.get(terrain_data[ny][nx], "?")
                landmarks.append((dist, t_name, dx, dy))
    landmarks.sort()

    if not landmarks:
        return "在开阔地带"

    dist, name, dx, dy = landmarks[0]
    if dist == 1:
        return f"在{name}附近"
    if dist <= 3:
        dirstr = _dir_name(-dx, -dy)
        return f"在{name}{dirstr}约{dist}格"
    return f"在{name}方向约{dist}格"


def _dir_name(dx: int, dy: int) -> str:
    if dx == 0 and dy == 0:
        return ""
    parts = []
    if dy < 0: parts.append("北")
    if dy > 0: parts.append("南")
    if dx < 0: parts.append("西")
    if dx > 0: parts.append("东")
    return "".join(parts) + "偏" if len(parts) > 1 else "".join(parts)
