"""
FogRenderer — 迷雾视觉效果渲染器（Sprint 2）。

在不可见区域绘制半透明黑色遮罩；在友军汇报位置周围绘制"大致位置"高亮圈。
订阅 POSITION_REPORT 事件以维护汇报区域列表。

依赖：
    src/core/interfaces.py — IFogOfWar
    src/core/constants.py  — FOG_ALPHA, FOG_COLOR, FOG_APPROXIMATE_RADIUS, TILE_SIZE
    src/core/event_bus.py  — 订阅 POSITION_REPORT

版本: v0.1.0 — Sprint 2
"""

from __future__ import annotations

import logging
from typing import Optional

import pygame

from src.core.constants import (
    FOG_ALPHA,
    FOG_APPROXIMATE_RADIUS,
    FOG_COLOR,
    Coordinate,
    Faction,
    GameEventType,
    PositionReportPayload,
    TILE_SIZE,
)
from src.core.event_bus import event_bus
from src.core.interfaces import IFogOfWar

logger = logging.getLogger(__name__)

# ── 迷雾遮罩颜色解析 ──────────────────────────────────────────────────


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """将 CSS 十六进制颜色字符串转换为 RGB 元组。"""
    hex_str = hex_color.lstrip("#")
    if len(hex_str) == 6:
        return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))
    raise ValueError(f"无效的颜色格式: {hex_color}")


# ── "大致位置"数据模型 ────────────────────────────────────────────────


class ApproximateZone:
    """友军汇报的大致位置区域。

    Attributes:
        coord: 汇报的坐标（带误差）
        remaining_turns: 剩余显示回合数（过期后不再高亮）
    """

    def __init__(self, coord: Coordinate, duration: int = 3) -> None:
        self.coord = coord
        self.remaining_turns = duration


# ── FogRenderer ────────────────────────────────────────────────────────


class FogRenderer:
    """迷雾视觉渲染器。

    职责：
        - 对不可见格子绘制半透明黑色遮罩
        - 对 POSITION_REPORT 汇报位置绘制高亮圈
        - 订阅 EventBus 的 POSITION_REPORT 事件以更新汇报区域

    约束：
        - 只调用 IFogOfWar 查询接口，不修改游戏数据
        - 不 import src/battle/
    """

    def __init__(
        self,
        fog: IFogOfWar | None = None,
        player_faction: Faction = Faction.FRIENDLY,
        map_width: int = 20,
        map_height: int = 15,
        tile_size: int = TILE_SIZE,
    ) -> None:
        """初始化迷雾渲染器。

        Args:
            fog: #2 提供的 IFogOfWar 接口实例（可为 None，表示无迷雾）
            player_faction: 玩家阵营
            map_width: 地图宽度（列数）
            map_height: 地图高度（行数）
            tile_size: 每格像素尺寸
        """
        self._fog = fog
        self._player_faction = player_faction
        self._map_width = map_width
        self._map_height = map_height
        self._tile_size = tile_size

        # ── 大致位置区域列表 ────────────────────────────────────────
        self._approx_zones: list[ApproximateZone] = []

        # ── 预创建遮罩 Surface（每帧复用） ───────────────────────────
        self._fog_overlay: Optional[pygame.Surface] = None
        self._highlight_overlay: Optional[pygame.Surface] = None

        self._fog_color_rgb = _hex_to_rgb(FOG_COLOR)

        # ── 订阅 POSITION_REPORT ─────────────────────────────────────
        self._subscribe_events()

    # ── 公开方法 ──────────────────────────────────────────────────────

    def set_fog(self, fog: IFogOfWar | None) -> None:
        """更新迷雾数据源。

        Args:
            fog: 新的 IFogOfWar 实例
        """
        self._fog = fog

    def set_player_faction(self, faction: Faction) -> None:
        """更新玩家阵营。

        Args:
            faction: 新的玩家阵营
        """
        self._player_faction = faction

    def set_map_size(self, width: int, height: int) -> None:
        """更新地图尺寸（重建遮罩 Surface 时使用）。

        Args:
            width: 地图宽度
            height: 地图高度
        """
        self._map_width = width
        self._map_height = height
        self._fog_overlay = None       # 强制重建
        self._highlight_overlay = None

    def render_fog(
        self,
        surface: pygame.Surface,
    ) -> None:
        """在指定 Surface 上绘制迷雾遮罩层。

        对每个不可见格子绘制半透明黑色方块。

        BUG-18 note: This fully redraws every frame which is acceptable for
        the current map size (20×15 = 300 tiles).  For larger maps, the
        fog overlay should be cached and only rebuilt when visibility changes.

        Args:
            surface: 目标 Surface（通常为 MapWidget 的 _map_surface）
        """
        if self._fog is None:
            return

        pw = self._map_width * self._tile_size
        ph = self._map_height * self._tile_size

        # 按需重建遮罩 Surface
        if self._fog_overlay is None or self._fog_overlay.get_size() != (pw, ph):
            self._fog_overlay = pygame.Surface((pw, ph), pygame.SRCALPHA)
            self._fog_overlay.fill((0, 0, 0, 0))

        # 逐格检查可见性并绘制遮罩
        self._fog_overlay.fill((0, 0, 0, 0))
        for col in range(self._map_width):
            for row in range(self._map_height):
                coord = Coordinate(col, row)
                if not self._fog.is_visible_to_faction(coord, self._player_faction):
                    rect = pygame.Rect(
                        col * self._tile_size,
                        row * self._tile_size,
                        self._tile_size,
                        self._tile_size,
                    )
                    pygame.draw.rect(
                        self._fog_overlay,
                        (*self._fog_color_rgb, FOG_ALPHA),
                        rect,
                    )

        surface.blit(self._fog_overlay, (0, 0))

    def render_highlights(
        self,
        surface: pygame.Surface,
    ) -> None:
        """在指定 Surface 上绘制"大致位置"高亮圈。

        Args:
            surface: 目标 Surface
        """
        if not self._approx_zones:
            return

        pw = self._map_width * self._tile_size
        ph = self._map_height * self._tile_size

        if self._highlight_overlay is None or self._highlight_overlay.get_size() != (pw, ph):
            self._highlight_overlay = pygame.Surface((pw, ph), pygame.SRCALPHA)
            self._highlight_overlay.fill((0, 0, 0, 0))

        self._highlight_overlay.fill((0, 0, 0, 0))

        for zone in self._approx_zones:
            # 绘制半径范围内的半透明高亮圈
            r = FOG_APPROXIMATE_RADIUS
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    gx = zone.coord.x + dx
                    gy = zone.coord.y + dy
                    if 0 <= gx < self._map_width and 0 <= gy < self._map_height:
                        # 距中心越远越透明
                        dist = max(abs(dx), abs(dy))
                        alpha = max(20, 80 - dist * 20)
                        rect = pygame.Rect(
                            gx * self._tile_size + 1,
                            gy * self._tile_size + 1,
                            self._tile_size - 2,
                            self._tile_size - 2,
                        )
                        # 使用金色高亮
                        pygame.draw.rect(
                            self._highlight_overlay,
                            (255, 215, 0, alpha),
                            rect,
                            border_radius=4,
                        )

        surface.blit(self._highlight_overlay, (0, 0))

    def on_turn_end(self) -> None:
        """回合结束时调用，减少汇报区域的剩余显示回合。"""
        # BUG-19 fix: removed redundant first filter pass — the second
        # list comprehension already handles filtering after decrement.
        for z in self._approx_zones:
            z.remaining_turns -= 1
        # 过滤已过期
        self._approx_zones = [
            z for z in self._approx_zones if z.remaining_turns > 0
        ]

    def clear_highlights(self) -> None:
        """清空所有汇报高亮区域。"""
        self._approx_zones.clear()

    # ── 事件回调 ──────────────────────────────────────────────────────

    def _on_position_report(self, payload: PositionReportPayload) -> None:
        """POSITION_REPORT 事件回调：添加汇报区域高亮。

        Args:
            payload: 位置汇报载荷
        """
        if not isinstance(payload, PositionReportPayload):
            return

        coord = Coordinate(payload.reported_x, payload.reported_y)
        zone = ApproximateZone(coord, duration=3)
        self._approx_zones.append(zone)
        logger.debug(
            "收到位置汇报: %s @(%d,%d) 附近有敌人=%s",
            payload.unit_name,
            payload.reported_x,
            payload.reported_y,
            payload.has_enemy_nearby,
        )

    def _subscribe_events(self) -> None:
        """订阅 EventBus 事件。"""
        event_bus.subscribe(GameEventType.POSITION_REPORT, self._on_position_report)

    def unsubscribe_events(self) -> None:
        """取消事件订阅（清理时调用）。"""
        event_bus.unsubscribe(GameEventType.POSITION_REPORT, self._on_position_report)

    def dispose(self) -> None:
        """BUG-17 fix: guaranteed cleanup method.
        
        Calls unsubscribe_events() and releases cached surfaces.
        Should be called when the FogRenderer is no longer needed.
        """
        self.unsubscribe_events()
        self._fog_overlay = None
        self._highlight_overlay = None
        self._approx_zones.clear()
        logger.debug("FogRenderer disposed")
