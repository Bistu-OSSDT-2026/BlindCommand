"""
CommandPanel — 原生 pygame 浮动单位选择面板（simhei 字体）
=============================================================
"""

from __future__ import annotations

import contextlib
from typing import Optional

import pygame

_SHORT_NAMES = {
    "第一步兵连": "1连", "第二步兵连": "2连", "第三步兵连": "3连", "第四步兵连": "4连",
    "第一骑兵连": "骑1", "第二骑兵连": "骑2",
    "第一炮兵连": "炮1", "第二炮兵连": "炮2",
    "侦察一排": "侦1", "侦察二排": "侦2",
}
FONT_PATH = "C:/Windows/Fonts/simhei.ttf"
FONT_SIZE = 16
ITEM_H = 24
PAD = 4
COLOR_BG = (42, 42, 42, 220)
COLOR_HOVER = (80, 80, 60, 220)
COLOR_TEXT = (220, 220, 200)


class CommandPanel:
    """原生 pygame 浮动面板。"""

    def __init__(self) -> None:
        self._visible = False
        self._items: list[tuple[str, str]] = []  # (label, full_name)
        self._rects: list[pygame.Rect] = []
        self._panel_rect: Optional[pygame.Rect] = None
        self._target_coord = None
        self._font: Optional[pygame.font.Font] = None
        self._clicked: Optional[str] = None
        with contextlib.suppress(Exception):
            self._font = pygame.font.Font(FONT_PATH, FONT_SIZE)

    def show(self, screen_pos: tuple[int, int], unit_names: list[str]) -> None:
        x, y = screen_pos
        self._items = [(_SHORT_NAMES.get(n, n[:4]), n) for n in unit_names]
        w = 80
        h = len(self._items) * ITEM_H + PAD * 2
        self._panel_rect = pygame.Rect(x, y, w, h)
        self._rects = [
            pygame.Rect(x + PAD, y + PAD + i * ITEM_H, w - PAD * 2, ITEM_H)
            for i in range(len(self._items))
        ]
        self._visible = True

    def hide(self) -> None:
        self._visible = False
        self._items.clear()
        self._rects.clear()
        self._clicked = None

    def handle_click(self, pos: tuple[int, int]) -> Optional[str]:
        if not self._visible:
            return None
        for i, r in enumerate(self._rects):
            if r.collidepoint(pos):
                name = self._items[i][1]
                self.hide()
                return name
        return None

    def draw(self, screen: pygame.Surface) -> None:
        if not self._visible or not self._font or not self._panel_rect:
            return
        # 背景
        s = pygame.Surface((self._panel_rect.width, self._panel_rect.height), pygame.SRCALPHA)
        s.fill(COLOR_BG)
        # 条目
        for i, (label, _) in enumerate(self._items):
            ry = PAD + i * ITEM_H
            text = self._font.render(label, True, COLOR_TEXT)
            s.blit(text, (PAD + 4, ry + 2))
        screen.blit(s, self._panel_rect.topleft)

    def set_target(self, coord) -> None:
        self._target_coord = coord

    def get_target(self):
        return self._target_coord

    @property
    def is_visible(self) -> bool:
        return self._visible
