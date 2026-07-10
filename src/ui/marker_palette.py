"""
MarkerPalette — 标记托盘（RTT）
================================
战报面板下方，数字 1-10 + 10 种兵种图标。
拖走再生，无限供应。
"""

from __future__ import annotations

from typing import Optional

import pygame

from src.core.constants import TILE_SIZE

MARKER_DIGIT_COLOR = (119, 119, 102)  # 灰铅笔色


class MarkerPalette:
    """标记托盘。"""

    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = rect
        self._digit_font: pygame.font.Font | None = None
        self._unit_icons: dict[str, pygame.Surface] = {}
        self._digit_surfaces: dict[int, pygame.Surface] = {}
        self._init_font()

    def _init_font(self) -> None:
        try:
            self._digit_font = pygame.font.Font(None, 24)
        except Exception:
            self._digit_font = pygame.font.Font(None, 20)

    def load_unit_icon(self, key: str, path: str) -> None:
        try:
            if path.endswith('.svg'):
                import io

                import cairosvg
                out = cairosvg.svg2png(url=path)
                img = pygame.image.load(io.BytesIO(out))
            else:
                img = pygame.image.load(path)
            img = pygame.transform.smoothscale(img, (TILE_SIZE, TILE_SIZE))
            self._unit_icons[key] = img
        except Exception as e:
            print(f"Load icon failed: {path} -> {e}")

    def get_digit_surface(self, n: int) -> pygame.Surface:
        if n not in self._digit_surfaces and self._digit_font:
            surf = self._digit_font.render(str(n), True, MARKER_DIGIT_COLOR)
            self._digit_surfaces[n] = surf
        return self._digit_surfaces.get(n, pygame.Surface((1, 1)))

    def get_unit_icon(self, key: str) -> pygame.Surface | None:
        return self._unit_icons.get(key)

    def get_item_at(self, pos: tuple[int, int]) -> str | None:
        """返回鼠标位置对应的标记 key：数字返回 "3"，图标返回 "Infantry_blue"。"""
        rx, ry = pos[0] - self.rect.x, pos[1] - self.rect.y
        # 第一行数字 1-5
        if ry < TILE_SIZE + 6:
            col = rx // (TILE_SIZE + 2)
            if 0 <= col < 5:
                return str(col + 1)
        # 第二行数字 6-10
        elif ry < (TILE_SIZE + 6) * 2:
            col = rx // (TILE_SIZE + 2)
            if 0 <= col < 5:
                return str(col + 6)
        # 第三行友军图标
        elif ry < (TILE_SIZE + 6) * 2 + TILE_SIZE + 6:
            col = rx // (TILE_SIZE + 2)
            keys = ["Infantry_blue", "Cavalry_blue", "Artillery_blue", "Scout_blue", "HQ_blue"]
            if 0 <= col < len(keys):
                return keys[col]
        # 第四行敌军图标
        elif ry < (TILE_SIZE + 6) * 2 + (TILE_SIZE + 6) * 2:
            col = rx // (TILE_SIZE + 2)
            keys = ["Infantry_red", "Cavalry_red", "Artillery_red", "Scout_red", "HQ_red"]
            if 0 <= col < len(keys):
                return keys[col]
        return None

    def draw(self, screen: pygame.Surface) -> None:
        """渲染托盘到屏幕。"""
        pygame.draw.rect(screen, (26, 26, 26), self.rect)
        x, y = self.rect.x + 4, self.rect.y + 4

        # 数字 1-10
        for i in range(1, 11):
            surf = self.get_digit_surface(i)
            screen.blit(surf, (x, y))
            x += TILE_SIZE + 2
            if i == 5:
                x = self.rect.x + 4
                y += TILE_SIZE + 2

        # 兵种图标（友军 + 敌军）
        y = self.rect.y + TILE_SIZE * 2 + 12
        x = self.rect.x + 4
        for key in ["Infantry_blue", "Cavalry_blue", "Artillery_blue", "Scout_blue", "HQ_blue"]:
            icon = self.get_unit_icon(key)
            if icon:
                screen.blit(icon, (x, y))
            x += TILE_SIZE + 2
        y += TILE_SIZE + 2
        x = self.rect.x + 4
        for key in ["Infantry_red", "Cavalry_red", "Artillery_red", "Scout_red", "HQ_red"]:
            icon = self.get_unit_icon(key)
            if icon:
                screen.blit(icon, (x, y))
            x += TILE_SIZE + 2
