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
import math
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
        created_at_ms: 创建时间戳（毫秒），用于呼吸动画相位
    """

    def __init__(self, coord: Coordinate, duration: int = 3) -> None:
        self.coord = coord
        self.remaining_turns = duration
        self.created_at_ms = pygame.time.get_ticks()  # Sprint 3: 雷达 ping 动画


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

        # ── Sprint 3: dirty flags ──────────────────────────────────────
        self._fog_dirty: bool = True           # 迷雾遮罩需重建
        self._highlights_dirty: bool = True     # 高亮圈需重建

        # ── Sprint 3: Alpha 插值网格 ────────────────────────────────────
        # 每个格子的当前 alpha 和目标 alpha (0=可见, FOG_ALPHA=不可见)
        self._fog_alpha_grid: list[list[float]] = []     # 当前值
        self._target_alpha_grid: list[list[float]] = []  # 目标值
        self._fog_lerp_speed: float = 900.0  # alpha 变化速度（单位/秒）
        self._fog_transitioning: bool = True  # 是否有格子仍在过渡中
        self._init_alpha_grid()

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
        self._fog_dirty = True

    def set_player_faction(self, faction: Faction) -> None:
        """更新玩家阵营。

        Args:
            faction: 新的玩家阵营
        """
        self._player_faction = faction
        self._fog_dirty = True

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
        self._fog_dirty = True
        self._highlights_dirty = True
        self._init_alpha_grid()

    def mark_fog_dirty(self) -> None:
        """标记迷雾为脏（外部在单位移动后调用，触发迷雾目标更新）。"""
        self._fog_dirty = True

    def render_fog(
        self,
        surface: pygame.Surface,
        time_delta: float = 0.033,
    ) -> None:
        """Sprint 3: 平滑迷雾 Alpha 插值渲染。

        维护每个格子的当前 alpha 值和目标 alpha 值（0=可见, FOG_ALPHA=不可见）。
        每帧对每个格子做 lerp 向目标值收敛，产生平滑的"驱散迷雾"效果。
        软边缘：处于视野边界的格子目标 alpha=120（而非全黑 180），形成渐变边。

        Args:
            surface: 目标 Surface（通常为 MapWidget 的 _map_surface）
            time_delta: 上一帧时间间隔（秒），用于帧率无关的 lerp 速度
        """
        if self._fog is None:
            return

        pw = self._map_width * self._tile_size
        ph = self._map_height * self._tile_size

        # 按需创建遮罩 Surface
        if self._fog_overlay is None or self._fog_overlay.get_size() != (pw, ph):
            self._fog_overlay = pygame.Surface((pw, ph), pygame.SRCALPHA)
            self._fog_dirty = True

        # ── 更新目标 alpha 值（仅在脏时） ──────────────────────────
        if self._fog_dirty:
            self._update_target_alphas()
            self._fog_dirty = False

        # ── Lerp 当前 alpha 向目标 alpha 收敛 ─────────────────────
        lerp_factor = min(1.0, self._fog_lerp_speed * time_delta)
        self._fog_transitioning = False
        self._fog_overlay.fill((0, 0, 0, 0))

        for row in range(self._map_height):
            for col in range(self._map_width):
                current = self._fog_alpha_grid[row][col]
                target = self._target_alpha_grid[row][col]

                if abs(current - target) < 0.5:
                    new_alpha = target
                else:
                    new_alpha = current + (target - current) * lerp_factor
                    self._fog_transitioning = True

                self._fog_alpha_grid[row][col] = new_alpha

                # 仅在 alpha > 阈值时绘制（跳过近乎透明的格子以节省 blit）
                if new_alpha > 2:
                    rect = pygame.Rect(
                        col * self._tile_size,
                        row * self._tile_size,
                        self._tile_size,
                        self._tile_size,
                    )
                    pygame.draw.rect(
                        self._fog_overlay,
                        (*self._fog_color_rgb, int(new_alpha)),
                        rect,
                    )

        surface.blit(self._fog_overlay, (0, 0))

    def _update_target_alphas(self) -> None:
        """根据当前 IFogOfWar 查询结果更新所有格子的目标 alpha。

        可见格: target=0
        不可见格: target=FOG_ALPHA (180)
        视野边界格（可见但邻接不可见）: target=120（软边缘）
        """
        if self._fog is None:
            return

        for row in range(self._map_height):
            for col in range(self._map_width):
                coord = Coordinate(col, row)
                visible = self._fog.is_visible_to_faction(coord, self._player_faction)

                if visible:
                    self._target_alpha_grid[row][col] = 0.0
                else:
                    # 软边缘：若该不可见格周围有可见格，使用降低的 alpha
                    edge_alpha = self._soft_edge_alpha(col, row)
                    self._target_alpha_grid[row][col] = edge_alpha

    def _soft_edge_alpha(self, col: int, row: int) -> float:
        """计算不可见格子的软边缘 alpha。

        检查切比雪夫距离为 2 的邻域。若邻域中有可见格，返回降低的 alpha
        以创造渐变边缘；否则返回全 FOG_ALPHA。

        Args:
            col: 列索引
            row: 行索引

        Returns:
            alpha 值 (120~180)
        """
        if self._fog is None:
            return float(FOG_ALPHA)

        has_visible_adjacent = False
        has_visible_near = False
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                nr, nc = row + dr, col + dc
                if 0 <= nr < self._map_height and 0 <= nc < self._map_width:
                    coord = Coordinate(nc, nr)
                    if self._fog.is_visible_to_faction(coord, self._player_faction):
                        if abs(dr) <= 1 and abs(dc) <= 1:
                            has_visible_adjacent = True
                        else:
                            has_visible_near = True
            # Bug 11 fix: 不再提前 break，完整扫描邻域

        if has_visible_adjacent:
            return 120.0  # 紧邻可见格 → 较淡迷雾
        if has_visible_near:
            return 150.0  # 距离 2 → 中等迷雾
        return float(FOG_ALPHA)  # 深处 → 完全迷雾

    def _init_alpha_grid(self) -> None:
        """初始化 alpha 网格（全部设为全迷雾）。"""
        self._fog_alpha_grid = [
            [float(FOG_ALPHA)] * self._map_width
            for _ in range(self._map_height)
        ]
        self._target_alpha_grid = [
            [float(FOG_ALPHA)] * self._map_width
            for _ in range(self._map_height)
        ]
        self._fog_dirty = True
        self._fog_transitioning = True

    def render_highlights(
        self,
        surface: pygame.Surface,
    ) -> None:
        """Sprint 3: 绘制"大致位置"呼吸高亮圈。

        高亮圈 alpha 以正弦波脉动（周期 ~2 秒），创造呼吸效果。
        新建 zone 的前 400ms 有额外"雷达 ping"亮度。
        最后一回合（remaining_turns == 1）渐隐消失。

        Args:
            surface: 目标 Surface
        """
        if not self._approx_zones:
            return

        pw = self._map_width * self._tile_size
        ph = self._map_height * self._tile_size

        if self._highlight_overlay is None or self._highlight_overlay.get_size() != (pw, ph):
            self._highlight_overlay = pygame.Surface((pw, ph), pygame.SRCALPHA)
            self._highlights_dirty = True

        if self._highlights_dirty:  # Bug 12 fix: remove dead `or True`
            self._highlight_overlay.fill((0, 0, 0, 0))
            now_ms = pygame.time.get_ticks()

            for zone in self._approx_zones:
                r = FOG_APPROXIMATE_RADIUS

                # ── 呼吸脉冲：正弦波 alpha 60~120，周期 ~2s ──────────
                age_ms = now_ms - zone.created_at_ms
                pulse = 0.5 + 0.5 * math.sin(age_ms * 0.003)  # 0.0 ~ 1.0
                base_alpha = 60 + int(pulse * 60)  # 60 ~ 120

                # ── 雷达 ping：新建时前 400ms 额外亮度 ──────────────
                ping_bonus = 0
                if age_ms < 400:
                    ping_decay = 1.0 - age_ms / 400.0
                    ping_bonus = int(100 * ping_decay)

                # ── 渐隐：最后一回合 alpha 降为 0 ────────────────────
                fade_mult = 1.0
                if zone.remaining_turns == 1:
                    fade_mult = 0.4

                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        gx = zone.coord.x + dx
                        gy = zone.coord.y + dy
                        if 0 <= gx < self._map_width and 0 <= gy < self._map_height:
                            dist = max(abs(dx), abs(dy))
                            dist_alpha = max(10, (base_alpha + ping_bonus) - dist * 20)
                            dist_alpha = int(dist_alpha * fade_mult)
                            rect = pygame.Rect(
                                gx * self._tile_size + 1,
                                gy * self._tile_size + 1,
                                self._tile_size - 2,
                                self._tile_size - 2,
                            )
                            pygame.draw.rect(
                                self._highlight_overlay,
                                (255, 215, 0, dist_alpha),
                                rect,
                                border_radius=4,
                            )
            self._highlights_dirty = False

        surface.blit(self._highlight_overlay, (0, 0))

    def on_turn_end(self) -> None:
        """回合结束时调用，减少汇报区域的剩余显示回合。"""
        for z in self._approx_zones:
            z.remaining_turns -= 1
        # Bug 13 fix: 移除冗余的第一个过滤器，只在递减后过滤
        prev_count = len(self._approx_zones)
        self._approx_zones = [
            z for z in self._approx_zones if z.remaining_turns > 0
        ]
        if prev_count != len(self._approx_zones):
            self._highlights_dirty = True

    def clear_highlights(self) -> None:
        """清空所有汇报高亮区域。"""
        self._approx_zones.clear()
        self._highlights_dirty = True

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
        self._highlights_dirty = True
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
