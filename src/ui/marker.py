"""
MarkerSystem — 玩家地图标记系统（Sprint 2）。

支持从调色板拖拽标记到地图格、吸附格子中心、右键删除、数字键切换类型。
标记仅存在于 UI 层，不影响游戏实际状态。

依赖：
    src/core/constants.py — MarkerType, Coordinate, TILE_SIZE, 标记颜色
    src/ui/map_widget.py  — MapWidget.pixel_to_coord() / coord_to_rect()

版本: v0.1.0 — Sprint 2
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pygame

from src.core.constants import (
    Coordinate,
    MarkerType,
)

logger = logging.getLogger(__name__)


# ── 字体辅助 ──────────────────────────────────────────────────────────

def _create_font(size: int) -> pygame.font.Font:
    """创建字体。优先系统字体绝对路径 → 捆绑字体 → 默认字体。"""
    import os as _os
    import sys as _sys
    from pathlib import Path as _Path

    # 1) 系统字体目录
    _fonts_dir = _os.environ.get("WINDIR", "C:/Windows") + "/Fonts"
    for _name in ("msyh.ttc", "msyh.ttf", "simkai.ttf", "simsun.ttc"):
        _fp = _os.path.join(_fonts_dir, _name)
        if _os.path.exists(_fp):
            try:
                return pygame.font.Font(_fp, size)
            except Exception:
                continue
    # 2) 捆绑字体
    if getattr(_sys, "frozen", False):
        _base = _Path(_sys._MEIPASS)
    else:
        _base = _Path(__file__).resolve().parent.parent.parent
    _bundled = _base / "data" / "chinese.ttf"
    if _bundled.exists():
        try:
            return pygame.font.Font(str(_bundled), size)
        except Exception:
            pass
    return pygame.font.Font(None, size)


# ── 标记颜色映射 ──────────────────────────────────────────────────────

MARKER_COLORS: dict[MarkerType, str] = {
    MarkerType.FRIENDLY_GUESS: "#4488FF40",
    MarkerType.ENEMY_GUESS: "#FF444440",
    MarkerType.HQ_GUESS: "#FFD70040",
    MarkerType.CUSTOM_NOTE: "#FFFFFF40",
}

MARKER_LABELS: dict[MarkerType, str] = {
    MarkerType.FRIENDLY_GUESS: "?",
    MarkerType.ENEMY_GUESS: "?",
    MarkerType.HQ_GUESS: "HQ",
    MarkerType.CUSTOM_NOTE: "?",
}

# 调色板配置
PALETTE_WIDTH: int = 44
PALETTE_ITEM_SIZE: int = 32
PALETTE_MARGIN: int = 6

# ── 颜色解析 ──────────────────────────────────────────────────────────


def _hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    """将 CSS 十六进制颜色（6 位或 8 位）转换为 RGBA 元组。

    Args:
        hex_color: 如 '#4488FF80'

    Returns:
        (R, G, B, A) 整数元组
    """
    hex_str = hex_color.lstrip("#")
    if len(hex_str) == 6:
        return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16), 255)
    if len(hex_str) == 8:
        return (
            int(hex_str[0:2], 16),
            int(hex_str[2:4], 16),
            int(hex_str[4:6], 16),
            int(hex_str[6:8], 16),
        )
    raise ValueError(f"无效的颜色格式: {hex_color}")


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class Marker:
    """单个玩家标记的数据模型。

    Attributes:
        marker_id: 全局唯一标识（自动生成）
        marker_type: 标记类型
        coord: 地图坐标（非像素）
        label: 自定义备注文字（仅 CUSTOM_NOTE 使用）
    """

    marker_id: str
    marker_type: MarkerType
    coord: Coordinate
    label: str = ""

    # ── 工厂方法 ──────────────────────────────────────────────────

    _counter: int = field(default=0, init=False, repr=False)

    @classmethod
    def create(cls, marker_type: MarkerType, coord: Coordinate, label: str = "") -> Marker:
        """创建标记并自动分配 ID。

        Args:
            marker_type: 标记类型
            coord: 地图坐标
            label: 可选标签

        Returns:
            新 Marker 实例
        """
        cls._counter += 1
        return cls(
            marker_id=f"marker_{cls._counter}",
            marker_type=marker_type,
            coord=coord,
            label=label,
        )


# ── MarkerSystem ───────────────────────────────────────────────────────


class MarkerSystem:
    """玩家地图标记管理。

    职责：
        - 管理标记列表（增/删/改/查）
        - 处理鼠标拖拽：从调色板拖到地图格 → 吸附 → 创建标记
        - 处理右键删除
        - 处理数字键 1-4 切换选中标记类型
        - 渲染调色板和地图上的标记

    调色板位置：紧贴 MapWidget 左侧或上方（由构造参数决定）。
    """

    def __init__(self, map_offset: tuple[int, int] = (0, 0)) -> None:
        """初始化标记系统。

        Args:
            map_offset: 地图在窗口中的像素偏移 (x, y)
        """
        self._markers: list[Marker] = []
        self._map_offset = map_offset

        # ── 拖拽状态 ──────────────────────────────────────────────
        self._dragging_type: Optional[MarkerType] = None  # 正在拖拽的标记类型
        self._dragging_pos: tuple[int, int] = (0, 0)       # 当前鼠标位置
        self._selected_marker: Optional[str] = None         # 当前选中的 marker_id

        # ── 调色板 Surface（按需创建） ────────────────────────────
        self._palette_surface: Optional[pygame.Surface] = None
        self._palette_rects: dict[MarkerType, pygame.Rect] = {}

        # ── RTT 标记托盘对接 ──────────────────────────────────────
        self._rtt_palette = None
        self._rtt_palette_rect: Optional[pygame.Rect] = None
        self._rtt_dragging_key: Optional[str] = None  # 正在拖拽的托盘 key

        # ── 移动跟踪（数字拖拽 A→B 记录） ─────────────────────────
        self._last_digit_drag: dict | None = None
        self._rtt_drag_from = None

    def get_last_drag(self) -> dict | None:
        """返回最近一次数字标记拖拽信息 {digit, from_coord, to_coord}。"""
        return self._last_digit_drag

    def set_palette(self, palette, rect: pygame.Rect) -> None:
        """对接 RTT MarkerPalette。"""
        self._rtt_palette = palette
        self._rtt_palette_rect = rect

    # ── 公开方法：标记管理 ──────────────────────────────────────────

    def add_marker(self, marker_type: MarkerType, coord: Coordinate, label: str = "") -> Marker:
        """添加一个标记。

        Args:
            marker_type: 标记类型
            coord: 地图坐标
            label: 可选标签

        Returns:
            创建的 Marker
        """
        marker = Marker.create(marker_type, coord, label)
        self._markers.append(marker)
        logger.debug("添加标记: %s @(%d,%d)", marker.marker_type.value, coord.x, coord.y)
        return marker

    def remove_marker(self, marker_id: str) -> bool:
        """移除指定标记。保存到撤销缓冲以供 Ctrl+Z 恢复。

        Args:
            marker_id: 标记 ID

        Returns:
            True 如果成功移除
        """
        for i, m in enumerate(self._markers):
            if m.marker_id == marker_id:
                self._last_deleted = m  # Sprint 3: 撤销缓冲
                self._markers.pop(i)
                if self._selected_marker == marker_id:
                    self._selected_marker = None
                logger.debug("移除标记: %s", marker_id)
                return True
        return False

    def undo_last_delete(self) -> Optional[Marker]:
        """恢复最近删除的标记（Ctrl+Z）。

        Returns:
            恢复的 Marker，若无待恢复返回 None
        """
        if self._last_deleted is None:
            return None
        restored = self._last_deleted
        self._markers.append(restored)
        self._last_deleted = None
        logger.debug("撤销删除，恢复标记: %s @(%d,%d)",
                     restored.marker_id, restored.coord.x, restored.coord.y)
        return restored

    def get_marker_at_coord(self, coord: Coordinate) -> Optional[Marker]:
        """获取指定坐标上的第一个标记。

        Args:
            coord: 地图坐标

        Returns:
            找到的 Marker，无则返回 None
        """
        for m in self._markers:
            if m.coord == coord:
                return m
        return None

    def get_all_markers(self) -> list[Marker]:
        """获取所有标记的副本。"""
        return list(self._markers)

    def clear(self) -> None:
        """清空所有标记。"""
        self._markers.clear()
        self._selected_marker = None

    # ── 公开方法：事件处理 ──────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, map_widget: object) -> bool:
        """处理鼠标/键盘事件。

        应由 MainWindow._handle_events() 在 pygame_gui 处理之后调用。
        返回 True 表示事件已被 MarkerSystem 消费（不应再传给其他处理器）。

        Args:
            event: pygame 事件
            map_widget: MapWidget 实例（用于 pixel_to_coord / coord_to_rect）

        Returns:
            True 如果事件被消费
        """
        # ── 鼠标按下 ──────────────────────────────────────────────
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # 左键
                # ── RTT 托盘拖拽 ──────────────────────────────────
                if self._rtt_palette is not None and self._rtt_palette_rect is not None:
                    if self._rtt_palette_rect.collidepoint(event.pos):
                        item = self._rtt_palette.get_item_at(event.pos)
                        if item is None:
                            return False  # 空白区域，不拖拽
                        self._dragging_type = MarkerType.FRIENDLY_GUESS
                        self._dragging_pos = event.pos
                        self._rtt_dragging_key = item
                        return True

                # 检查是否点击了调色板
                marker_type = self._hit_test_palette(event.pos)
                if marker_type is not None:
                    self._dragging_type = marker_type
                    self._dragging_pos = event.pos
                    logger.debug("开始拖拽标记: %s", marker_type.value)
                    return True

                # 检查是否点击了已有的标记（开始移动）
                if map_widget is not None:
                    coord = map_widget.pixel_to_coord(
                        event.pos[0] - self._map_offset[0],
                        event.pos[1] - self._map_offset[1],
                    )
                    if coord is not None:
                        marker = self.get_marker_at_coord(coord)
                        if marker is not None:
                            self._selected_marker = marker.marker_id
                            self._dragging_type = marker.marker_type
                            self._dragging_pos = event.pos
                            self._rtt_dragging_key = marker.label or None
                            self._rtt_drag_from = coord
                            self.remove_marker(marker.marker_id)
                            return True

            elif event.button == 3:  # 右键删除
                if map_widget is not None:
                    coord = map_widget.pixel_to_coord(
                        event.pos[0] - self._map_offset[0],
                        event.pos[1] - self._map_offset[1],
                    )
                    if coord is not None:
                        marker = self.get_marker_at_coord(coord)
                        if marker is not None:
                            self.remove_marker(marker.marker_id)
                            logger.debug("右键删除标记: %s", marker.marker_id)
                            return True

        # ── 鼠标移动 ──────────────────────────────────────────────
        elif event.type == pygame.MOUSEMOTION:
            if self._dragging_type is not None:
                self._dragging_pos = event.pos
                return True
            # Sprint 3: 调色板悬停检测
            hovered = self._hit_test_palette(event.pos)
            if hovered != self._hovered_type:
                self._hovered_type = hovered
                self._palette_dirty = True
                return True

        # ── 鼠标释放（放置标记） ──────────────────────────────────
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1 and self._dragging_type is not None:
                if map_widget is not None:
                    coord = map_widget.pixel_to_coord(
                        event.pos[0] - self._map_offset[0],
                        event.pos[1] - self._map_offset[1],
                    )
                    if coord is not None:
                        # RTT 托盘标记
                        if self._rtt_dragging_key is not None:
                            self.add_marker(MarkerType.FRIENDLY_GUESS, coord, self._rtt_dragging_key)
                            # 如果是数字且拖动了已有标记，记录 from→to
                            if self._rtt_dragging_key.isdigit() and self._rtt_drag_from is not None:
                                self._last_digit_drag = {
                                    "digit": self._rtt_dragging_key,
                                    "from_coord": self._rtt_drag_from,
                                    "to_coord": coord,
                                }
                            self._rtt_dragging_key = None
                            self._rtt_drag_from = None
                        else:
                            self.add_marker(self._dragging_type, coord)
                self._dragging_type = None
                return True

        # ── 键盘事件：数字键切换选中标记类型 ────────────────────────
        elif event.type == pygame.KEYDOWN and self._selected_marker is not None:
            type_map: dict[int, MarkerType] = {
                pygame.K_1: MarkerType.FRIENDLY_GUESS,
                pygame.K_2: MarkerType.ENEMY_GUESS,
                pygame.K_3: MarkerType.HQ_GUESS,
                pygame.K_4: MarkerType.CUSTOM_NOTE,
            }
            new_type = type_map.get(event.key)
            if new_type is not None:
                for m in self._markers:
                    if m.marker_id == self._selected_marker:
                        m.marker_type = new_type
                        logger.debug("切换标记类型: %s → %s", m.marker_id, new_type.value)
                        return True

        return False

    # ── 公开方法：渲染 ──────────────────────────────────────────────

    def build_palette(self, x: int, y: int, height: int) -> None:
        """构建调色板 Surface（通常在初始化或窗口 resize 时调用一次）。

        Args:
            x: 调色板左上角 x
            y: 调色板左上角 y
            height: 调色板可用高度
        """
        types = [
            MarkerType.FRIENDLY_GUESS,
            MarkerType.ENEMY_GUESS,
            MarkerType.HQ_GUESS,
            MarkerType.CUSTOM_NOTE,
        ]
        item_h = PALETTE_ITEM_SIZE + PALETTE_MARGIN * 2
        total_h = len(types) * item_h
        start_y = y + max(0, (height - total_h) // 2)

        self._palette_surface = pygame.Surface((PALETTE_WIDTH, height), pygame.SRCALPHA)
        self._palette_surface.fill((0, 0, 0, 0))
        self._palette_rects.clear()

        font = self._font

        for i, mtype in enumerate(types):
            item_x = (PALETTE_WIDTH - PALETTE_ITEM_SIZE) // 2
            item_y = start_y + i * item_h + PALETTE_MARGIN

            rect = pygame.Rect(item_x, item_y, PALETTE_ITEM_SIZE, PALETTE_ITEM_SIZE)
            self._palette_rects[mtype] = pygame.Rect(
                x + item_x, y + item_y, PALETTE_ITEM_SIZE, PALETTE_ITEM_SIZE
            )

            rgba = _hex_to_rgba(MARKER_COLORS[mtype])

            # Sprint 3: 悬停项 100% 亮度，其余 60%
            is_hovered = self._hovered_type == mtype
            if not is_hovered:
                rgba = (rgba[0], rgba[1], rgba[2], int(rgba[3] * 0.6))

            pygame.draw.rect(self._palette_surface, rgba, rect, border_radius=4)
            border_alpha = 255 if is_hovered else 120
            pygame.draw.rect(
                self._palette_surface,
                (rgba[0], rgba[1], rgba[2], border_alpha),
                rect,
                2,
                border_radius=4,
            )

            label = MARKER_LABELS[mtype]
            label_color = (255, 255, 255, 255) if mtype != MarkerType.CUSTOM_NOTE else (0, 0, 0, 255)
            text = font.render(label, True, label_color)
            text_rect = text.get_rect(center=rect.center)
            self._palette_surface.blit(text, text_rect)

    def draw_palette(self, screen: pygame.Surface, dest: tuple[int, int]) -> None:
        """将调色板 blit 到屏幕。Sprint 3: 悬停变化时重建。

        Args:
            screen: 目标 Surface
            dest: 调色板在屏幕上的位置
        """
        if self._palette_dirty:
            # 重建调色板以反映悬停状态
            palette_rect = self._palette_rects.get(MarkerType.FRIENDLY_GUESS)
            if palette_rect is not None:
                self.build_palette(dest[0], dest[1], self._palette_surface.get_height() if self._palette_surface else 200)
            self._palette_dirty = False

        if self._palette_surface is not None:
            screen.blit(self._palette_surface, dest)

    def draw_markers(
        self, surface: pygame.Surface, map_widget,
    ) -> None:
        """RTT 渲染标记：数字用字体，图标用图片，不再用色块。"""
        for marker in self._markers:
            rect = map_widget.coord_to_rect(marker.coord)
            local_rect = pygame.Rect(
                rect.x - map_widget.rect.x - map_widget._map_offset[0],
                rect.y - map_widget.rect.y - map_widget._map_offset[1],
                rect.width, rect.height,
            )

            if marker.label and marker.label.isdigit():
                # 数字标记：灰铅笔色大号数字
                font = pygame.font.Font("C:/Windows/Fonts/simhei.ttf", max(12, rect.width))
                text = font.render(marker.label, True, (90, 85, 75))
                text_rect = text.get_rect(center=local_rect.center)
                surface.blit(text, text_rect)
            elif marker.label and "_" in marker.label:
                # 兵种图标标记
                icon = self._rtt_palette.get_unit_icon(marker.label) if self._rtt_palette else None
                if icon:
                    scaled = pygame.transform.smoothscale(icon, (rect.width, rect.height))
                    surface.blit(scaled, local_rect.topleft)
                else:
                    # fallback 小灰点
                    pygame.draw.circle(surface, (128, 128, 128, 100),
                                       local_rect.center, rect.width // 3)
            else:
                # 无标签标记：小灰点
                pygame.draw.circle(surface, (128, 128, 128, 100),
                                   local_rect.center, rect.width // 3)

        # 不渲染拖拽幽灵（消除残影）

    # ── 私有方法 ──────────────────────────────────────────────────

    def _hit_test_palette(self, pos: tuple[int, int]) -> Optional[MarkerType]:
        """测试鼠标位置是否在调色板某个按钮上。

        Args:
            pos: 屏幕像素坐标

        Returns:
            命中的 MarkerType，无命中返回 None
        """
        for mtype, rect in self._palette_rects.items():
            if rect.collidepoint(pos):
                return mtype
        return None
