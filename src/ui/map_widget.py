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
    src/core/interfaces.py — IMap, IUnit, IEngine
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
    TILE_SIZE,
    Coordinate,
    Faction,
    GameEventType,
    TerrainType,
)
from src.core.event_bus import event_bus

if TYPE_CHECKING:
    from src.core.interfaces import IEngine, IMap, IUnit
    from src.ui.marker import MarkerSystem

logger = logging.getLogger(__name__)

# ── 地形符号缩放系数（>1 = 比格子大） ──────────────────────────────
TERRAIN_SYMBOL_SCALE = 1.5  # 符号 = TILE_SIZE × 1.5

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
        self._tile_image_cache: dict = {}  # key: TerrainType or "_base_"
        self._unit_image_cache: dict[str, Optional[pygame.Surface]] = {}
        self._images_loaded: bool = False
        self._friendly_hq: Optional[Coordinate] = None
        self._dev_units: list = []  # 开发者模式单位列表  # 友军 HQ 坐标

        # ── 注入的子系统（Sprint 2） ──────────────────────────────
        self.marker_system: Optional[MarkerSystem] = None

        # ── 汇报圈 ──────────────────────────────────────────────
        self._report_circles: list[dict] = []
        event_bus.subscribe(GameEventType.POSITION_REPORT, self._on_report)

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

    def set_fog(self, fog) -> None:
        pass  # RTT 无迷雾

    # ── 公开方法：地图加载 ──────────────────────────────────────────

    def set_dev_units(self, units: list) -> None:
        self._dev_units = units

    def set_friendly_hq(self, coord: Coordinate) -> None:
        self._friendly_hq = coord

    def _render_dev_units(self) -> None:
        """开发者模式：用兵种图标渲染所有单位。"""
        if not self._dev_units or self._map_surface is None:
            return
        for u in self._dev_units:
            if not u.is_alive:
                continue
            cache_key = f"{u.unit_type.value}_{u.faction.value}"
            icon = self._unit_image_cache.get(cache_key)
            x = u.position.x * self._tile_size
            y = u.position.y * self._tile_size
            if icon is not None:
                self._map_surface.blit(icon, (x, y))
            else:
                color = (100, 150, 255, 200) if u.faction.value == "FRIENDLY" else (255, 100, 100, 200)
                s = pygame.Surface((self._tile_size, self._tile_size), pygame.SRCALPHA)
                pygame.draw.circle(s, color, (self._tile_size // 2, self._tile_size // 2), self._tile_size // 2 - 2)
                self._map_surface.blit(s, (x, y))

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

        # 通知 FogRenderer 更新地图尺寸（已弃用，RTT 无迷雾）
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
        markers: list | None = None,
        report_circles: list | None = None,
    ) -> None:
        """RTT 渲染：层0地形 → 层1标记 → 层2汇报圈。"""
        if self._map_surface is None:
            return
        self._render_terrain_layer()
        # 标记
        if self.marker_system is not None:
            self.marker_system.draw_markers(self._map_surface, self)
        # 汇报圈
        self._render_report_circles(self._report_circles)
        # 开发模式单位
        self._render_dev_units()

    def _render_markers(self, markers: list) -> None:
        """渲染玩家标记（委托给外部系统或直接 blit）。"""
        if self.marker_system is not None:
            self.marker_system.draw_markers(self._map_surface, self)

    def _render_report_circles(self, circles: list) -> None:
        """渲染汇报圈。"""
        from src.core.constants import REPORT_CIRCLE_ALPHA, REPORT_CIRCLE_RADIUS
        for c in circles:
            coord = c.get('coord')
            alpha = c.get('alpha', REPORT_CIRCLE_ALPHA)
            r = c.get('radius', REPORT_CIRCLE_RADIUS) * self._tile_size
            if coord is None:
                continue
            cx = coord.x * self._tile_size + self._tile_size // 2
            cy = coord.y * self._tile_size + self._tile_size // 2
            # 限制渲染范围
            if cx < 0 or cy < 0 or cx > self._map_surface.get_width() or cy > self._map_surface.get_height():
                continue
            s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(s, (90, 85, 75, min(255, alpha)), s.get_rect(), 3)
            self._map_surface.blit(s, (cx - r, cy - r))

    def _on_report(self, payload) -> None:
        """POSITION_REPORT 事件：添加汇报圈。"""
        from src.core.constants import REPORT_CIRCLE_ALPHA, REPORT_CIRCLE_RADIUS, REPORT_CIRCLE_DURATION, Coordinate
        x = getattr(payload, 'reported_x', 0)
        y = getattr(payload, 'reported_y', 0)
        self._report_circles.append({
            'coord': Coordinate(x, y),
            'alpha': REPORT_CIRCLE_ALPHA,
            'radius': REPORT_CIRCLE_RADIUS,
            'duration': REPORT_CIRCLE_DURATION,
        })

    def update_report_circles(self, dt: float) -> None:
        """每帧更新汇报圈（递减计时，移除过期）。"""
        for c in self._report_circles:
            c['duration'] -= dt
            c['alpha'] = max(0, int(80 * (c['duration'] / 5.0)))
        self._report_circles = [c for c in self._report_circles if c['duration'] > 0]

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

    @staticmethod
    def _load_svg(path: str) -> pygame.Surface:
        import cairosvg, io
        out = cairosvg.svg2png(url=path)
        return pygame.image.load(io.BytesIO(out))

    def _load_tile_images(self) -> None:
        """预加载地形图片 + 兵种图标。"""
        assets_path = Path(ASSETS_DIR) / "terrain"
        units_path = Path("src/ui/assets/units")

        # 兵种图标（开发者模式用，蓝=友军，红=敌军）
        for key in ["Infantry", "Cavalry", "Artillery", "Scout", "HQ"]:
            for color, cache_key in [("blue", f"{key}_FRIENDLY"), ("red", f"{key}_ENEMY")]:
                for ext in [".png", ".svg"]:
                    p = units_path / f"{key}_{color}{ext}"
                    if p.exists():
                        try:
                            img = pygame.image.load(str(p)) if ext == ".png" else self._load_svg(str(p))
                            img = pygame.transform.smoothscale(img, (self._tile_size, self._tile_size))
                            self._unit_image_cache[cache_key] = img
                        except Exception:
                            pass
                        break

        # 基底纹理
        base_path = assets_path / "MapBase.png"
        if base_path.exists():
            try:
                self._tile_image_cache["_base_"] = pygame.image.load(str(base_path))
            except pygame.error as e:
                logger.warning("基底加载失败: %s", e)

        # 地形符号
        for terrain_type, filename in TERRAIN_IMAGE_FILES.items():
            if not filename:
                self._tile_image_cache[terrain_type] = None
                continue
            filepath = assets_path / filename
            if filepath.exists():
                try:
                    img = pygame.image.load(str(filepath))
                    symbol_size = int(self._tile_size * TERRAIN_SYMBOL_SCALE)
                    img = pygame.transform.smoothscale(img, (symbol_size, symbol_size))
                    self._tile_image_cache[terrain_type] = img
                except pygame.error as e:
                    logger.warning("地形图片加载失败: %s — %s", filepath, e)
                    self._tile_image_cache[terrain_type] = None
            else:
                self._tile_image_cache[terrain_type] = None

        self._images_loaded = True

    # ── 私有方法：渲染层 ─────────────────────────────────────────────

    def _render_terrain_layer(self) -> None:
        """RTT 渲染：基底纹理平铺 + 逐格 stamp 地形符号。平原格不贴符号。"""
        if self._map_surface is None:
            return

        # 层 0：基底纹理（一张大图铺满整个地图）
        base = self._tile_image_cache.get("_base_")
        if base is not None:
            pw, ph = self._map_surface.get_size()
            scaled = pygame.transform.smoothscale(base, (pw, ph))
            self._map_surface.blit(scaled, (0, 0))
        else:
            self._map_surface.fill((232, 213, 176))

        # 层 1：地形符号
        from src.core.constants import TerrainType
        for row_idx, row_data in enumerate(self._terrain_data):
            for col_idx, terrain_code in enumerate(row_data):
                try:
                    terrain = TerrainType(terrain_code)
                except ValueError:
                    terrain = TerrainType.PLAIN
                if terrain == TerrainType.PLAIN:
                    continue
                # HQ 只显示友军
                if terrain == TerrainType.HQ_CELL:
                    if self._friendly_hq is None or (col_idx != self._friendly_hq.x or row_idx != self._friendly_hq.y):
                        continue
                tile_img = self._tile_image_cache.get(terrain)
                if tile_img is not None:
                    sym_w = tile_img.get_width()
                    sym_h = tile_img.get_height()
                    offset_x = (self._tile_size - sym_w) // 2
                    offset_y = (self._tile_size - sym_h) // 2
                    rect = pygame.Rect(
                        col_idx * self._tile_size + offset_x,
                        row_idx * self._tile_size + offset_y,
                        sym_w, sym_h,
                    )
                    self._map_surface.blit(tile_img, rect)

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
        self, game_loop, player_faction: Faction
    ) -> None:
        """[已弃用] RTT 下单位不渲染。保留用于兼容。"""
        pass
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
