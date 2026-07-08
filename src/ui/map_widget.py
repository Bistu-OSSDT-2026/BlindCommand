"""
MapWidget — 中央地图渲染组件（Sprint 2 升级版）。

支持四层渲染（由底到顶）：
    层 0: 地形瓦片（优先加载 .png 图片，无素材时回退纯色方块）
    层 1: 单位精灵（蓝/红方块，仅渲染可见单位）
    层 2: 玩家标记（半透明拖拽方块，由 MarkerSystem 注入）
    层 3: 迷雾遮罩（半透明黑色，由 FogRenderer 注入）

Sprint 2 新增：
    - 加载 .png 地形图片（TERRAIN_IMAGE_FILES），素材缺失则降级纯色
    - 可见性过滤（调用 IFogOfWar.is_unit_visible）
    - set_map() / set_fog() 依赖注入桩已升级为真实对接

依赖：
    src/core/constants.py  — TerrainType, TILE_SIZE, COLOR_FRIENDLY/ENEMY, ...
    src/core/interfaces.py — IMap, IFogOfWar, IGameLoop, IUnit
    src/ui/marker.py       — MarkerSystem（可选注入）
    src/ui/fog_renderer.py — FogRenderer（可选注入）

版本: v0.2.0 — Sprint 2
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import pygame

from src.core.constants import (
    ASSETS_DIR,
    COLOR_ENEMY,
    COLOR_FRIENDLY,
    DEFAULT_MAP_FILE,
    TERRAIN_IMAGE_FILES,
    Faction,
    TILE_SIZE,
    Coordinate,
    TerrainType,
)

if TYPE_CHECKING:
    from src.core.interfaces import IFogOfWar, IGameLoop, IMap, IUnit
    from src.ui.fog_renderer import FogRenderer
    from src.ui.marker import MarkerSystem

logger = logging.getLogger(__name__)

# ── 地形色块映射（Sprint 1 占位，无图片素材时使用） ──────────────────────

TERRAIN_COLORS: dict[TerrainType, tuple[int, int, int]] = {
    TerrainType.PLAIN:    (144, 238, 144),  # 浅绿
    TerrainType.FOREST:   (34, 139, 34),    # 深绿
    TerrainType.MOUNTAIN: (139, 137, 137),  # 灰色
    TerrainType.RIVER:    (65, 105, 225),   # 蓝色
    TerrainType.HQ_CELL:  (255, 215, 0),    # 金色
    TerrainType.BRIDGE:   (160, 82, 45),    # 棕色
}

GRID_LINE_COLOR: tuple[int, int, int] = (51, 51, 51)   # #333333
GRID_LINE_WIDTH: int = 1

# ── 单位兵种简写 ──────────────────────────────────────────────────────

UNIT_ABBREVIATIONS: dict[str, str] = {
    "Infantry":  "步兵",
    "Cavalry":   "骑兵",
    "Artillery": "炮兵",
    "Scout":     "侦察",
    "HQ":        "HQ",
}


def _get_unit_abbreviation(unit_type_str: str) -> str:
    """兵种英文 → 2 字中文简写。"""
    return UNIT_ABBREVIATIONS.get(unit_type_str, "??")


# ── 颜色解析工具 ──────────────────────────────────────────────────────


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """将 CSS 十六进制颜色字符串转换为 RGB 元组。

    Args:
        hex_color: 如 '#4488FF'

    Returns:
        (R, G, B) 整数元组
    """
    hex_str = hex_color.lstrip("#")
    if len(hex_str) == 6:
        return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))
    if len(hex_str) == 8:
        return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))
    raise ValueError(f"无效的颜色格式: {hex_color}")


# ── MapWidget ─────────────────────────────────────────────────────────


class MapWidget:
    """中央地图渲染组件。

    Sprint 2 功能：
        - 从 JSON 文件加载地图数据（Sprint 1 兼容）
        - 对接 #2 IMap 接口作为数据源（Sprint 2）
        - 渲染 20×15 地形图块（优先 .png 图片，降级纯色）
        - 渲染可见单位方块（调用 IFogOfWar.is_unit_visible 过滤）
        - 集成 MarkerSystem 和 FogRenderer 的渲染层
        - 像素坐标 ↔ 地图坐标互换
    """

    def __init__(self, rect: pygame.Rect) -> None:
        """初始化地图组件。

        Args:
            rect: 地图区域矩形（窗口像素坐标）
        """
        self.rect = rect
        self._terrain_data: list[list[int]] = []
        self._map_width: int = 0
        self._map_height: int = 0
        self._units: list[dict] = []           # Sprint 1: 从 JSON 加载的单位列表
        self._tile_size: int = TILE_SIZE
        self._map_data: IMap | None = None     # Sprint 2: #2 提供的 IMap 实例
        self._fog: IFogOfWar | None = None     # Sprint 2: #2 提供的 IFogOfWar 实例

        # ── 地图画布 ──────────────────────────────────────────────
        self._map_surface: Optional[pygame.Surface] = None
        self._map_offset: tuple[int, int] = (0, 0)  # 地图在画布中的偏移（公开给 marker/fog）

        # ── 图片缓存 ──────────────────────────────────────────────
        self._tile_image_cache: dict[TerrainType, Optional[pygame.Surface]] = {}
        self._unit_image_cache: dict[str, Optional[pygame.Surface]] = {}
        self._images_loaded: bool = False

        # ── 注入的子系统（Sprint 2） ──────────────────────────────
        self.marker_system: Optional[MarkerSystem] = None
        self.fog_renderer: Optional[FogRenderer] = None

        # ── 预加载图片 ────────────────────────────────────────────
        self._load_tile_images()

    # ── 属性 ────────────────────────────────────────────────────────

    @property
    def map_width(self) -> int:
        """地图宽度（列数）。"""
        return self._map_width

    @property
    def map_height(self) -> int:
        """地图高度（行数）。"""
        return self._map_height

    @property
    def pixel_width(self) -> int:
        """地图像素宽度。"""
        return self._map_width * self._tile_size

    @property
    def pixel_height(self) -> int:
        """地图像素高度。"""
        return self._map_height * self._tile_size

    # ── 公开方法：依赖注入 ──────────────────────────────────────────

    def set_map(self, map_data: IMap) -> None:
        """绑定地图数据源（Sprint 2 对接 #2 的 IMap 实现）。

        Args:
            map_data: #2 提供的 IMap 接口实例
        """
        self._map_data = map_data
        logger.info("MapWidget 已绑定 IMap 数据源")

    def set_fog(self, fog: IFogOfWar) -> None:
        """绑定迷雾查询接口（Sprint 2 对接 #2 的 IFogOfWar 实现）。

        Args:
            fog: #2 提供的 IFogOfWar 接口实例
        """
        self._fog = fog
        if self.fog_renderer is not None:
            self.fog_renderer.set_fog(fog)
        logger.info("MapWidget 已绑定 IFogOfWar 数据源")

    # ── 公开方法：地图加载 ──────────────────────────────────────────

    def load_map_from_json(self, filepath: str = DEFAULT_MAP_FILE) -> bool:
        """从 JSON 文件加载地图数据。

        在 #2 的 IMap 实现就绪之前，此方法直接读取 JSON 作为数据源。
        Sprint 2 仍保留此方法作为独立运行模式的后备。

        Args:
            filepath: 地图 JSON 文件路径

        Returns:
            True 如果加载成功
        """
        path = Path(filepath)
        if not path.exists():
            logger.error("地图文件不存在: %s", path)
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("地图文件解析失败: %s", e)
            return False

        size = data.get("map_size", {})
        self._map_width = int(size.get("width", 20))
        self._map_height = int(size.get("height", 15))
        self._terrain_data = data.get("terrain", [])

        # 加载并标记阵营
        friendly = data.get("friendly_units", [])
        for u in friendly:
            u["faction"] = "FRIENDLY"
        enemy = data.get("enemy_units", [])
        for u in enemy:
            u["faction"] = "ENEMY"
        self._units = friendly + enemy

        # 创建地图 Surface
        self._map_surface = pygame.Surface(
            (self._map_width * self._tile_size, self._map_height * self._tile_size)
        )

        # 计算地图在显示区域中的偏移（居中）
        offset_x = (self.rect.width - self.pixel_width) // 2
        offset_y = (self.rect.height - self.pixel_height) // 2
        self._map_offset = (max(0, offset_x), max(0, offset_y))

        # 通知 FogRenderer 更新地图尺寸
        if self.fog_renderer is not None:
            self.fog_renderer.set_map_size(self._map_width, self._map_height)

        logger.info(
            "地图加载成功: %s, 尺寸 %d×%d, 单位 %d",
            path.name,
            self._map_width,
            self._map_height,
            len(self._units),
        )
        return True

    # ── 公开方法：渲染 ──────────────────────────────────────────────

    def render(
        self,
        game_loop: IGameLoop | None = None,
        player_faction: Faction = Faction.FRIENDLY,
    ) -> None:
        """完整渲染一帧：地形层 + 网格线 + 单位层 + 标记层 + 迷雾层。

        渲染顺序（由底到顶）：
            1. 地形瓦片
            2. 网格线
            3. 单位精灵（可见性过滤）
            4. 玩家标记（由 MarkerSystem 提供）
            5. 迷雾遮罩 + 大致位置高亮（由 FogRenderer 提供）

        Args:
            game_loop: #2 提供的 IGameLoop 实例（获取单位列表）
            player_faction: 玩家阵营（用于可见性判定）
        """
        if self._map_surface is None:
            return

        # ── 层 0: 地形 ────────────────────────────────────────────
        self._render_terrain_layer()

        # ── 层 1: 网格线 ──────────────────────────────────────────
        self._render_grid_lines()

        # ── 层 2: 单位 ────────────────────────────────────────────
        if game_loop is not None:
            self._render_unit_layer_from_gameloop(game_loop, player_faction)
        else:
            # Sprint 1 兼容模式：无可见性过滤
            self._render_unit_layer_legacy()

        # ── 层 3: 标记（Sprint 2） ─────────────────────────────────
        if self.marker_system is not None:
            self.marker_system.draw_markers(self._map_surface, self)

        # ── 层 4: 迷雾（Sprint 2） ─────────────────────────────────
        if self.fog_renderer is not None:
            self.fog_renderer.render_highlights(self._map_surface)
            self.fog_renderer.render_fog(self._map_surface)

    def draw(self, screen: pygame.Surface) -> None:
        """将渲染结果 blit 到主屏幕。

        Args:
            screen: 主窗口 Surface
        """
        if self._map_surface is None:
            return

        dest_x = self.rect.x + self._map_offset[0]
        dest_y = self.rect.y + self._map_offset[1]
        screen.blit(self._map_surface, (dest_x, dest_y))

    # ── 公开方法：坐标转换 ──────────────────────────────────────────

    def pixel_to_coord(self, px: int, py: int) -> Optional[Coordinate]:
        """像素坐标 → 地图坐标。

        Args:
            px: 相对于 self.rect 的像素 x
            py: 相对于 self.rect 的像素 y

        Returns:
            地图坐标，若点击在地图区域外返回 None
        """
        map_x = px - self._map_offset[0]
        map_y = py - self._map_offset[1]

        col = map_x // self._tile_size
        row = map_y // self._tile_size

        if 0 <= col < self._map_width and 0 <= row < self._map_height:
            return Coordinate(col, row)
        return None

    def coord_to_rect(self, coord: Coordinate) -> pygame.Rect:
        """地图坐标 → 像素矩形（用于鼠标碰撞检测和渲染定位）。

        Args:
            coord: 地图坐标

        Returns:
            该格子的窗口像素矩形
        """
        return pygame.Rect(
            self.rect.x + self._map_offset[0] + coord.x * self._tile_size,
            self.rect.y + self._map_offset[1] + coord.y * self._tile_size,
            self._tile_size,
            self._tile_size,
        )

    # ── 私有方法：图片加载 ──────────────────────────────────────────

    def _load_tile_images(self) -> None:
        """预加载地形图片到缓存。素材缺失时缓存 None（运行时降级纯色）。"""
        assets_path = Path(ASSETS_DIR) / "terrain"
        for terrain_type, filename in TERRAIN_IMAGE_FILES.items():
            filepath = assets_path / filename
            if filepath.exists():
                try:
                    img = pygame.image.load(str(filepath))
                    # 缩放到 TILE_SIZE
                    img = pygame.transform.scale(img, (self._tile_size, self._tile_size))
                    self._tile_image_cache[terrain_type] = img
                except pygame.error as e:
                    logger.warning("地形图片加载失败: %s — %s", filepath, e)
                    self._tile_image_cache[terrain_type] = None
            else:
                logger.debug("地形图片不存在，将使用纯色方块: %s", filepath)
                self._tile_image_cache[terrain_type] = None

        self._images_loaded = True

    # ── 私有方法：渲染层 ─────────────────────────────────────────────

    def _render_terrain_layer(self) -> None:
        """渲染地形层（优先图片，降级纯色方块）。"""
        if self._map_surface is None:
            return

        for row_idx, row_data in enumerate(self._terrain_data):
            for col_idx, terrain_code in enumerate(row_data):
                try:
                    terrain = TerrainType(terrain_code)
                except ValueError:
                    terrain = TerrainType.PLAIN

                rect = pygame.Rect(
                    col_idx * self._tile_size,
                    row_idx * self._tile_size,
                    self._tile_size,
                    self._tile_size,
                )

                # 优先使用图片
                tile_img = self._tile_image_cache.get(terrain)
                if tile_img is not None:
                    self._map_surface.blit(tile_img, rect.topleft)
                else:
                    # 降级纯色方块
                    color = TERRAIN_COLORS.get(terrain, (128, 128, 128))
                    pygame.draw.rect(self._map_surface, color, rect)

    def _render_grid_lines(self) -> None:
        """渲染网格线。"""
        if self._map_surface is None:
            return

        # 垂直线
        for col in range(self._map_width + 1):
            x = col * self._tile_size
            pygame.draw.line(
                self._map_surface,
                GRID_LINE_COLOR,
                (x, 0),
                (x, self.pixel_height),
                GRID_LINE_WIDTH,
            )

        # 水平线
        for row in range(self._map_height + 1):
            y = row * self._tile_size
            pygame.draw.line(
                self._map_surface,
                GRID_LINE_COLOR,
                (0, y),
                (self.pixel_width, y),
                GRID_LINE_WIDTH,
            )

    def _render_unit_layer_from_gameloop(
        self, game_loop: IGameLoop, player_faction: Faction
    ) -> None:
        """Sprint 2：从 IGameLoop 获取单位并做可见性过滤。

        Args:
            game_loop: #2 提供的 IGameLoop 实例
            player_faction: 玩家阵营
        """
        if self._map_surface is None:
            return

        color_friendly = _hex_to_rgb(COLOR_FRIENDLY)
        color_enemy = _hex_to_rgb(COLOR_ENEMY)

        all_units = game_loop.get_all_units()
        for unit in all_units:
            # ── 可见性过滤 ──────────────────────────────────────────
            if self._fog is not None:
                if not self._fog.is_unit_visible(unit, player_faction):
                    continue

            is_friendly = unit.faction == player_faction
            color = color_friendly if is_friendly else color_enemy

            x = unit.position.x * self._tile_size
            y = unit.position.y * self._tile_size

            unit_rect = pygame.Rect(
                x + 2, y + 2,
                self._tile_size - 4, self._tile_size - 4,
            )
            pygame.draw.rect(self._map_surface, color, unit_rect, border_radius=4)

            # 兵种简写标签
            abbr = _get_unit_abbreviation(unit.unit_type.value)
            self._draw_centered_text(abbr, x, y, (255, 255, 255))

            # 阵亡标记
            if not unit.is_alive:
                self._draw_centered_text("✕", x, y, (255, 0, 0))

    def _render_unit_layer_legacy(self) -> None:
        """Sprint 1 兼容：从 JSON 加载的单位列表渲染（无可见性过滤）。"""
        if self._map_surface is None:
            return

        color_friendly = _hex_to_rgb(COLOR_FRIENDLY)
        color_enemy = _hex_to_rgb(COLOR_ENEMY)

        for unit in self._units:
            faction = unit.get("faction", "FRIENDLY")
            color = color_friendly if faction == "FRIENDLY" else color_enemy

            x = unit.get("start_x", 0) * self._tile_size
            y = unit.get("start_y", 0) * self._tile_size

            unit_rect = pygame.Rect(
                x + 2, y + 2,
                self._tile_size - 4, self._tile_size - 4,
            )
            pygame.draw.rect(self._map_surface, color, unit_rect, border_radius=4)

            # 兵种简写标签
            unit_type_str = unit.get("unit_type", "?")
            abbr = _get_unit_abbreviation(unit_type_str)
            self._draw_centered_text(abbr, x, y, (255, 255, 255))

    def _draw_centered_text(
        self, text: str, tile_x: int, tile_y: int, color: tuple[int, int, int]
    ) -> None:
        """在指定格子的中央绘制文字（使用 pygame 默认字体）。

        Args:
            text: 要绘制的文字
            tile_x: 格子的像素 x 坐标（地图 Surface 坐标系）
            tile_y: 格子的像素 y 坐标
            color: 文字颜色
        """
        if self._map_surface is None:
            return

        font = pygame.font.Font(None, 14)
        text_surf = font.render(text, True, color)
        text_rect = text_surf.get_rect(
            center=(
                tile_x + self._tile_size // 2,
                tile_y + self._tile_size // 2,
            )
        )
        self._map_surface.blit(text_surf, text_rect)
