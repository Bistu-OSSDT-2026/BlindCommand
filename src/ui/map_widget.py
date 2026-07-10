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
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import pygame

# ── PyInstaller onefile 路径解析 ──────────────────────────────────────


def _get_base_path() -> Path:
    """返回项目根目录路径（兼容 PyInstaller onefile 模式）。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent.parent


def _create_font(size: int) -> pygame.font.Font:
    """创建字体。优先系统字体绝对路径 → 捆绑字体 → 默认字体。"""
    # 扫描系统字体目录（PyInstaller 中 SDL 搜索失效，直接路径仍可用）
    import os as _os
    _fonts_dir = _os.environ.get("WINDIR", "C:/Windows") + "/Fonts"
    for _name in ("msyh.ttc", "msyh.ttf", "simkai.ttf", "simsun.ttc", "FZYTK.TTF"):
        _fp = _os.path.join(_fonts_dir, _name)
        if _os.path.exists(_fp):
            try:
                return pygame.font.Font(_fp, size)
            except Exception:
                continue
    # 捆绑字体
    bundled = _get_base_path() / "data" / "chinese.ttf"
    if bundled.exists():
        try:
            return pygame.font.Font(str(bundled), size)
        except Exception:
            pass
    return pygame.font.Font(None, size)

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
    "Infantry":  "In",
    "Cavalry":   "Cv",
    "Artillery": "Ar",
    "Scout":     "Sc",
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


# ── Sprint 3: 动画效果数据类 ────────────────────────────────────────────


@dataclass
class CombatEffect:
    """战斗视觉效果（攻击闪现 + 浮动伤害数字）。

    Attributes:
        coord: 效果发生的地图坐标
        damage: 伤害数值（负数=回血，0=只闪现）
        start_ms: 效果开始时间戳（必须显式传入）
        duration_ms: 总持续时间
    """
    coord: Coordinate
    damage: int = 0
    start_ms: int = field(default_factory=pygame.time.get_ticks)  # Bug 7 fix
    duration_ms: int = 600

    @property
    def progress(self) -> float:
        """0.0 ~ 1.0 的进度。"""
        elapsed = pygame.time.get_ticks() - self.start_ms
        return min(1.0, elapsed / self.duration_ms)


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

        # ── Sprint 3: 性能缓存 ─────────────────────────────────────
        self._terrain_cache_surface: Optional[pygame.Surface] = None  # 地形+网格静态缓存
        self._font = _create_font(14)  # 预创建字体（支持中文），避免每帧分配
        self._rgb_friendly = _hex_to_rgb(COLOR_FRIENDLY)  # 预计算 RGB
        self._rgb_enemy = _hex_to_rgb(COLOR_ENEMY)

        # ── 注入的子系统（Sprint 2） ──────────────────────────────
        self.marker_system: Optional[MarkerSystem] = None

        # ── 汇报圈 ──────────────────────────────────────────────
        self._report_circles: list[dict] = []
        event_bus.subscribe(GameEventType.POSITION_REPORT, self._on_report)

        # ── Sprint 3: 动画与视觉效果 ─────────────────────────────────
        # 单位移动插值: unit_id → (prev_coord, target_coord, start_ms, duration_ms)
        self._unit_animations: dict[str, tuple[Coordinate, Coordinate, int, int]] = {}
        self._prev_unit_positions: dict[str, Coordinate] = {}  # 上帧位置
        # 战斗效果队列
        self._combat_effects: list[CombatEffect] = []
        # 阵亡单位淡化: unit_id → death_time_ms
        self._dead_unit_times: dict[str, int] = {}
        self._dead_unit_display_ms: int = 3000  # 3 秒后完全消失
        # 单位选择（Sprint 3 Day 5）
        self._selected_unit_id: Optional[str] = None

        # ── 预加载图片 ────────────────────────────────────────────
        self._load_tile_images()
        self._load_unit_images()

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

        Bug 6 fix: 如果已有 terrain_data，同步重建缓存。

        Args:
            map_data: #2 提供的 IMap 接口实例
        """
        self._map_data = map_data
        # Bug 6 fix: 确保 terrain cache 可用
        if self._terrain_data and self._terrain_cache_surface is None:
            self._build_terrain_cache()
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

        Args:
            filepath: 地图 JSON 文件路径

        Returns:
            True 如果加载成功
        """
        path = _get_base_path() / filepath
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

        # Sprint 3: 预渲染地形+网格到静态缓存（消除 ~337 次/帧 draw）
        self._build_terrain_cache()

        # 计算地图在显示区域中的偏移（居中）

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

    # ── 私有方法：地形缓存（Sprint 3 性能优化）───────────────────────

    def _build_terrain_cache(self) -> None:
        """预渲染地形瓦片 + 网格线到静态缓存 Surface。

        地形完全静态，网格线也完全静态。将它们预渲染到 _terrain_cache_surface，
        之后每帧只需一次 blit，消除 ~337 次/帧 draw 调用。
        """
        if self._map_width == 0 or self._map_height == 0:
            return

        pw = self._map_width * self._tile_size
        ph = self._map_height * self._tile_size
        self._terrain_cache_surface = pygame.Surface((pw, ph))

        # ── 地形瓦片 ────────────────────────────────────────────────
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

                tile_img = self._tile_image_cache.get(terrain)
                if tile_img is not None:
                    self._terrain_cache_surface.blit(tile_img, rect.topleft)
                else:
                    color = TERRAIN_COLORS.get(terrain, (128, 128, 128))
                    pygame.draw.rect(self._terrain_cache_surface, color, rect)

        # ── 网格线 ──────────────────────────────────────────────────
        # 垂直线
        for col in range(self._map_width + 1):
            x = col * self._tile_size
            pygame.draw.line(
                self._terrain_cache_surface,
                GRID_LINE_COLOR,
                (x, 0),
                (x, ph),
                GRID_LINE_WIDTH,
            )
        # 水平线
        for row in range(self._map_height + 1):
            y = row * self._tile_size
            pygame.draw.line(
                self._terrain_cache_surface,
                GRID_LINE_COLOR,
                (0, y),
                (pw, y),
                GRID_LINE_WIDTH,
            )

        logger.debug(
            "地形缓存已构建: %d×%d (%d px)", self._map_width, self._map_height, pw
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

    def _load_unit_images(self) -> None:
        """预加载单位图片到缓存。文件名格式: {unit_type}_{color}.png。"""
        assets_path = _get_base_path() / ASSETS_DIR / "units"
        for unit_type in ("infantry", "cavalry", "artillery", "scout", "hq"):
            for color in ("blue", "red"):
                key = f"{unit_type}_{color}"
                filepath = assets_path / f"{key}.png"
                if filepath.exists():
                    try:
                        img = pygame.image.load(str(filepath))
                        img = pygame.transform.scale(img, (self._tile_size - 4, self._tile_size - 4))
                        self._unit_image_cache[key] = img
                    except pygame.error as e:
                        logger.warning("单位图片加载失败: %s — %s", filepath, e)
                else:
                    logger.debug("单位图片不存在: %s", filepath)

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

        now_ms = pygame.time.get_ticks()
        anim_duration_ms = 300  # 移动动画持续时间

        all_units = game_loop.get_all_units()
        for unit in all_units:
            # ── 可见性过滤 ──────────────────────────────────────────
            if self._fog is not None:
                if not self._fog.is_unit_visible(unit, player_faction):
                    continue

            is_friendly = unit.faction == player_faction
            is_dead = not unit.is_alive

            # ── Sprint 3: 检测位置变化，启动移动动画 ────────────────
            actual_pos = unit.position
            prev_pos = self._prev_unit_positions.get(unit.unit_id)
            if prev_pos is not None and prev_pos != actual_pos:
                self._unit_animations[unit.unit_id] = (
                    prev_pos, actual_pos, now_ms, anim_duration_ms
                )

            # ── Sprint 3: 计算插值后的绘制位置 ─────────────────────
            draw_pos = actual_pos
            if unit.unit_id in self._unit_animations:
                prev, target, start, dur = self._unit_animations[unit.unit_id]
                elapsed = now_ms - start
                if elapsed >= dur:
                    del self._unit_animations[unit.unit_id]
                else:
                    t = elapsed / dur
                    # ease-out quad
                    t = 1.0 - (1.0 - t) ** 2
                    fx = prev.x + (target.x - prev.x) * t
                    fy = prev.y + (target.y - prev.y) * t
                    draw_pos = Coordinate(round(fx), round(fy))  # Bug 9 fix: round for smooth lerp

            # 更新位置追踪
            self._prev_unit_positions[unit.unit_id] = actual_pos

            # ── Sprint 3: 阵亡单位淡化 ─────────────────────────────
            if is_dead:
                if unit.unit_id not in self._dead_unit_times:
                    self._dead_unit_times[unit.unit_id] = now_ms
                death_elapsed = now_ms - self._dead_unit_times[unit.unit_id]
                if death_elapsed > self._dead_unit_display_ms:
                    continue
                alpha = max(30, 120 - int(120 * death_elapsed / self._dead_unit_display_ms))
                color = (128, 128, 128)
            else:
                color = self._rgb_friendly if is_friendly else self._rgb_enemy
                alpha = 255

            # Bug 5 fix: 清理超时死单位条目（每 5 秒执行一次）
            if is_dead and now_ms % 5000 < int(time_delta * 1000):
                expired_ids = [
                    uid for uid, t in self._dead_unit_times.items()
                    if now_ms - t > self._dead_unit_display_ms + 5000
                ]
                for uid in expired_ids:
                    self._dead_unit_times.pop(uid, None)
                    self._prev_unit_positions.pop(uid, None)
                    self._unit_animations.pop(uid, None)

            x = draw_pos.x * self._tile_size
            y = draw_pos.y * self._tile_size

            # ── Sprint 3: 选中单位高亮 ─────────────────────────────
            if unit.unit_id == self._selected_unit_id:
                pulse = 0.5 + 0.5 * math.sin(now_ms * 0.004)
                border_color = (255, 255, int(128 + 127 * pulse))
                border_rect = pygame.Rect(x - 1, y - 1, self._tile_size - 2, self._tile_size - 2)
                pygame.draw.rect(self._map_surface, border_color, border_rect, 2, border_radius=4)

            unit_rect = pygame.Rect(
                x + 2, y + 2,
                self._tile_size - 4, self._tile_size - 4,
            )

            # ── 优先使用单位图片，无图片时降级纯色方块 ────────────
            img_key = f"{unit.unit_type.value.lower()}_{'blue' if is_friendly else 'red'}"
            unit_img = self._unit_image_cache.get(img_key)

            if unit_img is not None:
                if alpha < 255:
                    unit_img.set_alpha(alpha)
                self._map_surface.blit(unit_img, unit_rect.topleft)
            elif alpha < 255:
                unit_overlay = pygame.Surface(
                    (unit_rect.width, unit_rect.height), pygame.SRCALPHA
                )
                pygame.draw.rect(unit_overlay, (*color, alpha),
                                 unit_overlay.get_rect(), border_radius=4)
                self._map_surface.blit(unit_overlay, unit_rect.topleft)
            else:
                pygame.draw.rect(self._map_surface, color, unit_rect, border_radius=4)

            # 兵种简写标签
            if not is_dead:
                abbr = _get_unit_abbreviation(unit.unit_type.value)
                self._draw_centered_text(abbr, x, y, (255, 255, 255))

    def _render_unit_layer_legacy(self) -> None:
        """Sprint 1 兼容：从 JSON 加载的单位列表渲染（无可见性过滤）。"""
        if self._map_surface is None:
            return

        color_friendly = self._rgb_friendly
        color_enemy = self._rgb_enemy

        for unit in self._units:
            faction = unit.get("faction", "FRIENDLY")
            color = color_friendly if faction == "FRIENDLY" else color_enemy

            x = unit.get("start_x", 0) * self._tile_size
            y = unit.get("start_y", 0) * self._tile_size

            unit_rect = pygame.Rect(
                x + 2, y + 2,
                self._tile_size - 4, self._tile_size - 4,
            )

            # ── 优先使用单位图片 ──────────────────────────────────
            unit_type = unit.get("unit_type", "?").lower()
            color_name = "blue" if faction == "FRIENDLY" else "red"
            img_key = f"{unit_type}_{color_name}"
            unit_img = self._unit_image_cache.get(img_key)

            if unit_img is not None:
                self._map_surface.blit(unit_img, unit_rect.topleft)
            else:
                pygame.draw.rect(self._map_surface, color, unit_rect, border_radius=4)

            # 兵种简写标签
            unit_type_str = unit.get("unit_type", "?")
            abbr = _get_unit_abbreviation(unit_type_str)
            self._draw_centered_text(abbr, x, y, (255, 255, 255))

    def _draw_centered_text(
        self, text: str, tile_x: int, tile_y: int, color: tuple[int, int, int]
    ) -> None:
        """在指定格子的中央绘制文字（使用缓存的字体对象）。

        Args:
            text: 要绘制的文字
            tile_x: 格子的像素 x 坐标（地图 Surface 坐标系）
            tile_y: 格子的像素 y 坐标
            color: 文字颜色
        """
        if self._map_surface is None:
            return

        # Sprint 3: 使用 __init__ 中缓存的字体，避免每帧分配
        text_surf = self._font.render(text, True, color)
        text_rect = text_surf.get_rect(
            center=(
                tile_x + self._tile_size // 2,
                tile_y + self._tile_size // 2,
            )
        )
        self._map_surface.blit(text_surf, text_rect)

    # ── Sprint 3: 单位选择 API (Bug 20 fix: 封装公开方法) ───────────

    def select_unit(self, unit_id: str | None) -> None:
        """选择单位（显示脉冲高亮边框）。None 取消选择。"""
        self._selected_unit_id = unit_id

    @property
    def selected_unit_id(self) -> str | None:
        """当前选中单位的 ID，无选中返回 None。"""
        return self._selected_unit_id

    # ── Sprint 3: 战斗效果渲染 ────────────────────────────────────────

    def add_combat_effect(self, coord: Coordinate, damage: int = 0) -> None:
        """添加一个战斗视觉效果（攻击闪现 + 浮动伤害数字）。

        在指定坐标产生 200ms 红色闪现和一个向上飘动的伤害数字。

        Args:
            coord: 地图坐标
            damage: 伤害数值（正数=受到伤害，0=只闪现）
        """
        self._combat_effects.append(CombatEffect(
            coord=coord,
            damage=damage,
            start_ms=pygame.time.get_ticks(),
            duration_ms=600,
        ))

    def _render_combat_effects(self) -> None:
        """渲染所有活跃的战斗效果（闪现 + 浮动伤害数字）。"""
        if self._map_surface is None:
            return

        now_ms = pygame.time.get_ticks()

        # 清理已完成的 effect
        self._combat_effects = [
            e for e in self._combat_effects
            if now_ms - e.start_ms < e.duration_ms  # Bug 8 fix: use cached now_ms
        ]

        for effect in self._combat_effects:
            elapsed = now_ms - effect.start_ms
            t = effect.progress

            px = effect.coord.x * self._tile_size
            py = effect.coord.y * self._tile_size

            # ── 闪现（前 200ms） ──────────────────────────────────
            if t < 0.33:
                flash_alpha = int(180 * (1.0 - t / 0.33))
                flash_rect = pygame.Rect(
                    px + 1, py + 1,
                    self._tile_size - 2, self._tile_size - 2,
                )
                flash_surf = pygame.Surface(
                    (flash_rect.width, flash_rect.height), pygame.SRCALPHA
                )
                pygame.draw.rect(
                    flash_surf, (255, 80, 80, flash_alpha),
                    flash_surf.get_rect(), border_radius=4,
                )
                self._map_surface.blit(flash_surf, flash_rect.topleft)

            # ── 浮动伤害数字 ──────────────────────────────────────
            if effect.damage != 0:
                float_y = py - int(20 * t)  # 向上飘动
                alpha = int(255 * (1.0 - t))  # 渐隐
                damage_text = f"-{effect.damage}"
                text_color = (255, 80, 80, alpha) if effect.damage > 0 else (80, 255, 80, alpha)
                text_surf = self._font.render(damage_text, True, text_color[:3])
                # 半透明处理
                text_overlay = pygame.Surface(text_surf.get_size(), pygame.SRCALPHA)
                text_overlay.blit(text_surf, (0, 0))
                text_overlay.set_alpha(alpha)
                text_x = px + (self._tile_size - text_surf.get_width()) // 2
                self._map_surface.blit(text_overlay, (text_x, float_y))

    # ── Sprint 3: HQ 脉冲高亮 ─────────────────────────────────────────

    def _render_hq_pulse_overlay(self) -> None:
        """在所有 HQ_CELL 格上绘制金色呼吸脉冲。"""
        for row_idx, row_data in enumerate(self._terrain_data):
            for col_idx, terrain_code in enumerate(row_data):
                if terrain_code == TerrainType.HQ_CELL.value:
                    self._render_hq_pulse(Coordinate(col_idx, row_idx))

    def _render_hq_pulse(self, coord: Coordinate) -> None:
        """在指定 HQ 坐标绘制金色呼吸脉冲效果。

        Args:
            coord: HQ 格的地图坐标
        """
        if self._map_surface is None:
            return

        now_ms = pygame.time.get_ticks()
        pulse = 0.5 + 0.5 * math.sin(now_ms * 0.003)
        alpha = int(60 + 60 * pulse)  # 60 ~ 120

        px = coord.x * self._tile_size
        py = coord.y * self._tile_size
        pulse_rect = pygame.Rect(px + 2, py + 2, self._tile_size - 4, self._tile_size - 4)
        pulse_surf = pygame.Surface(
            (pulse_rect.width, pulse_rect.height), pygame.SRCALPHA
        )
        pygame.draw.rect(
            pulse_surf, (255, 215, 0, alpha),
            pulse_surf.get_rect(), border_radius=4,
        )
        self._map_surface.blit(pulse_surf, pulse_rect.topleft)
