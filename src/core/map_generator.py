"""
BlindCommand 地图随机生成器 — Perlin噪声 + 对边河流 + 智能桥梁 + 防困校验
============================================================================
"""

from __future__ import annotations

import json
import random
from collections import deque
from pathlib import Path

from noise import pnoise2

from src.core.constants import MAP_MAX_SIZE, MAP_MIN_SIZE, Coordinate, TerrainType


class MapGenerator:
    """随机地图生成器。"""

    _OCTAVES = 6
    _PERSISTENCE = 0.6
    _LACUNARITY = 2.0
    _SCALE = 11.0
    _ANGLE = 0.3      # 小幅旋转打破轴对齐，但不过度斜向
    _PLAIN_MAX = 0.40
    _FOREST_MAX = 0.65
    _RIVER_CHANCE = 0.6  # 默认中等
    _RIVER_CHANCE_EASY = 0.25
    _RIVER_MAX_WIDTH = 3
    _HQ_MIN_DIST_RATIO = 0.7

    @classmethod
    def generate(cls, w=34, h=25, seed=None, unit_count=10, difficulty="中等", max_retries=200):
        cls._validate_size(w, h)
        rng = random.Random(seed)
        base = rng.randint(0, 9999)
        river_chance = cls._RIVER_CHANCE_EASY if difficulty == "简单" else cls._RIVER_CHANCE

        for _ in range(max_retries):
            terrain = cls._noise_terrain(w, h, base)
            terrain = cls._place_river(terrain, w, h, rng, river_chance)
            terrain = cls._place_bridges(terrain, w, h, rng)
            a, b = cls._place_hqs(terrain, w, h, rng)
            if a is None:
                continue
            terrain[a.y][a.x] = TerrainType.HQ_CELL.value
            terrain[b.y][b.x] = TerrainType.HQ_CELL.value
            if not cls._connected(terrain, w, h, a, b):
                continue
            cls._clear_trapped(terrain, w, h, a, b)
            f_units = cls._gen_units("friendly", a, terrain, w, h, rng, unit_count)
            e_units = cls._gen_units("enemy", b, terrain, w, h, rng, unit_count)
            f_poses = [(u["start_x"], u["start_y"]) for u in f_units]
            e_poses = [(u["start_x"], u["start_y"]) for u in e_units]
            if cls._units_ok(terrain, w, h, f_poses, e_poses, a, b):
                return terrain, a, b

        raise RuntimeError(f"无法在{max_retries}次尝试内生成合法地图")

    @classmethod
    def generate_to_json(cls, path, w=34, h=25, seed=None, unit_count=10, difficulty="中等"):
        terrain, a, b = cls.generate(w, h, seed, unit_count, difficulty)
        rng = random.Random(seed)
        f_units = cls._gen_units("friendly", a, terrain, w, h, rng, unit_count)
        e_units = cls._gen_units("enemy", b, terrain, w, h, rng, unit_count)
        data = {
            "map_size": {"width": w, "height": h},
            "terrain": terrain,
            "friendly_hq": {"x": a.x, "y": a.y},
            "enemy_hq": {"x": b.x, "y": b.y},
            "friendly_units": f_units,
            "enemy_units": e_units,
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ── 噪声 ──────────────────────────────────────────────────────

    @classmethod
    def _noise_terrain(cls, w, h, base):
        from math import cos, sin
        ca, sa = cos(cls._ANGLE), sin(cls._ANGLE)
        samples = [pnoise2((x * ca - y * sa) / cls._SCALE, (x * sa + y * ca) / cls._SCALE,
                           octaves=cls._OCTAVES, persistence=cls._PERSISTENCE,
                           lacunarity=cls._LACUNARITY, base=base)
                   for y in range(h) for x in range(w)]
        lo, hi = min(samples), max(samples)
        rng = hi - lo if hi > lo else 1.0
        from math import cos, sin
        ca, sa = cos(cls._ANGLE), sin(cls._ANGLE)
        terrain = [[0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                rx = (x * ca - y * sa) / cls._SCALE
                ry = (x * sa + y * ca) / cls._SCALE
                n = pnoise2(rx, ry, octaves=cls._OCTAVES,
                            persistence=cls._PERSISTENCE, lacunarity=cls._LACUNARITY, base=base)
                detail = pnoise2(rx * 3.2, ry * 3.2, octaves=2, persistence=0.5,
                                 lacunarity=2.0, base=base + 1000) * 0.08
                n = (n + detail - lo) / rng
                n += __import__('random').Random(base + x * 1000 + y).uniform(-0.06, 0.06)
                if n < cls._PLAIN_MAX:
                    terrain[y][x] = TerrainType.PLAIN.value
                elif n < cls._FOREST_MAX:
                    terrain[y][x] = TerrainType.FOREST.value
                else:
                    terrain[y][x] = TerrainType.MOUNTAIN.value
        return terrain

    # ── 河流：对边走到对边 ────────────────────────────────────────

    @classmethod
    def _place_river(cls, terrain, w, h, rng, chance=0.6):
        if rng.random() > chance:
            return terrain
        rw = rng.randint(1, cls._RIVER_MAX_WIDTH)
        side = rng.randint(0, 3)
        if side == 0:
            sx, sy, ex, ey = rng.randint(0, w - 1), 0, rng.randint(0, w - 1), h - 1
        elif side == 1:
            sx, sy, ex, ey = rng.randint(0, w - 1), h - 1, rng.randint(0, w - 1), 0
        elif side == 2:
            sx, sy, ex, ey = 0, rng.randint(0, h - 1), w - 1, rng.randint(0, h - 1)
        else:
            sx, sy, ex, ey = w - 1, rng.randint(0, h - 1), 0, rng.randint(0, h - 1)

        x, y = sx, sy
        points = [(x, y)]
        for _ in range(w + h + 20):
            if (x, y) == (ex, ey):
                break
            if abs(x - ex) > abs(y - ey):
                x += 1 if ex > x else -1
            else:
                y += 1 if ey > y else -1
            if rng.random() < 0.15:
                x += rng.choice([-1, 0, 1])
                y += rng.choice([-1, 0, 1])
            x, y = max(0, min(w - 1, x)), max(0, min(h - 1, y))
            points.append((x, y))

        for px, py in points:
            for dw in range(-rw, rw + 1):
                for dh in range(-rw, rw + 1):
                    nx, ny = px + dw, py + dh
                    if 0 <= nx < w and 0 <= ny < h and terrain[ny][nx] != TerrainType.MOUNTAIN.value:
                        terrain[ny][nx] = TerrainType.RIVER.value
        return terrain

    # ── 桥梁 ──────────────────────────────────────────────────────

    @classmethod
    def _place_bridges(cls, terrain, w, h, rng):
        if not cls._has_river(terrain, w, h):
            return terrain
        needed = max(1, sum(r.count(TerrainType.RIVER.value) for r in terrain) // 30)
        placed = 0
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if terrain[y][x] != TerrainType.RIVER.value:
                    continue
                for (x1, y1), (x2, y2) in [((x - 1, y), (x + 1, y)), ((x, y - 1), (x, y + 1))]:
                    if not (0 <= x1 < w and 0 <= y1 < h and 0 <= x2 < w and 0 <= y2 < h):
                        continue
                    t1, t2 = terrain[y1][x1], terrain[y2][x2]
                    if t1 not in (TerrainType.RIVER.value, TerrainType.MOUNTAIN.value) and \
                       t2 not in (TerrainType.RIVER.value, TerrainType.MOUNTAIN.value):
                        terrain[y][x] = TerrainType.BRIDGE.value
                        placed += 1
                        if placed >= needed:
                            return terrain
                        break
        if placed == 0:
            for y in range(1, h - 1):
                for x in range(1, w - 1):
                    if terrain[y][x] == TerrainType.RIVER.value:
                        terrain[y][x] = TerrainType.BRIDGE.value
                        return terrain
        return terrain

    # ── HQ ────────────────────────────────────────────────────────

    @classmethod
    def _place_hqs(cls, terrain, w, h, rng):
        min_dist = max(8, int(min(w, h) * cls._HQ_MIN_DIST_RATIO))
        passable = [Coordinate(x, y) for y in range(h) for x in range(w)
                    if terrain[y][x] not in (TerrainType.RIVER.value,)]
        if len(passable) < 2:
            return None, None
        rng.shuffle(passable)
        for i, a in enumerate(passable):
            for b in passable[i + 1:]:
                if a.chebyshev_distance(b) >= min_dist:
                    return a, b
        return None, None

    @classmethod
    def _clear_around_hq(cls, terrain, w, h, hq, radius=None):
        """旧方法——保留兼容。"""

    @classmethod
    def _break_walls(cls, terrain, w, h, rng):
        """禁止纵向/横向山墙超过 80%——随机破口。"""
        for x in range(w):
            mtn = sum(1 for y in range(h) if terrain[y][x] == TerrainType.MOUNTAIN.value)
            if mtn > h * 0.8:
                for _ in range(max(1, mtn - int(h * 0.6))):
                    y = rng.randint(0, h - 1)
                    if terrain[y][x] == TerrainType.MOUNTAIN.value:
                        terrain[y][x] = TerrainType.PLAIN.value
        for y in range(h):
            mtn = sum(1 for x in range(w) if terrain[y][x] == TerrainType.MOUNTAIN.value)
            if mtn > w * 0.8:
                for _ in range(max(1, mtn - int(w * 0.6))):
                    x = rng.randint(0, w - 1)
                    if terrain[y][x] == TerrainType.MOUNTAIN.value:
                        terrain[y][x] = TerrainType.PLAIN.value

    @classmethod
    def _clear_trapped(cls, terrain, w, h, hq_a, hq_b):
        """双 HQ 联合洪水填充——反复直到没有新可达格。"""
        dirs = [(1, 0), (-1, 0), (0, 1), (0, -1),
                (1, 1), (-1, -1), (1, -1), (-1, 1)]
        changed = True
        iterations = 0
        while changed and iterations < 20:
            changed = False
            iterations += 1
            visited = {(hq_a.x, hq_a.y), (hq_b.x, hq_b.y)}
            q = deque([(hq_a.x, hq_a.y), (hq_b.x, hq_b.y)])
            while q:
                cx, cy = q.popleft()
                for dx, dy in dirs:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                        if terrain[ny][nx] not in (TerrainType.RIVER.value,):
                            visited.add((nx, ny))
                            q.append((nx, ny))
            for y in range(h):
                for x in range(w):
                    if (x, y) not in visited and terrain[y][x] not in (
                        TerrainType.RIVER.value,
                        TerrainType.BRIDGE.value, TerrainType.HQ_CELL.value):
                        terrain[y][x] = TerrainType.PLAIN.value
                        changed = True

    # ── 连通 ──────────────────────────────────────────────────────

    @classmethod
    def _connected(cls, terrain, w, h, a, b):
        visited = {(a.x, a.y)}
        q = deque([(a.x, a.y)])
        while q:
            cx, cy = q.popleft()
            if (cx, cy) == (b.x, b.y):
                return True
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (-1, -1), (1, -1), (-1, 1)]:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                    if terrain[ny][nx] not in (TerrainType.RIVER.value,):
                        visited.add((nx, ny))
                        q.append((nx, ny))
        return False

    @classmethod
    def _units_ok(cls, terrain, w, h, f_positions, e_positions, hq_a, hq_b):
        """友军必须通 HQ_A，敌军必须通 HQ_B。8 向 BFS。"""
        dirs = [(1, 0), (-1, 0), (0, 1), (0, -1),
                (1, 1), (-1, -1), (1, -1), (-1, 1)]
        for _tag, positions, hq in [("F", f_positions, hq_a), ("E", e_positions, hq_b)]:
            for sx, sy in positions:
                if terrain[sy][sx] in (TerrainType.RIVER.value,):
                    return False
                visited = {(sx, sy)}
                q = deque([(sx, sy)])
                found = False
                while q and not found:
                    cx, cy = q.popleft()
                    if (cx, cy) == (hq.x, hq.y):
                        found = True
                        break
                    for dx, dy in dirs:
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                            if terrain[ny][nx] != TerrainType.RIVER.value:
                                visited.add((nx, ny))
                                q.append((nx, ny))
                if not found:
                    return False
        return True

    # ── 单位 ──────────────────────────────────────────────────────

    @classmethod
    def _gen_units(cls, faction_key, hq, terrain, w, h, rng, count):
        prefix = "friendly" if faction_key == "friendly" else "enemy"
        in_n = max(1, count * 4 // 10)
        ca_n = max(1, count * 2 // 10)
        ar_n = max(1, count * 2 // 10)
        sc_n = max(1, count - in_n - ca_n - ar_n)
        pool = (["Infantry"] * in_n + ["Cavalry"] * ca_n +
                ["Artillery"] * ar_n + ["Scout"] * sc_n)

        units, ii, ci, ai, si = [], 1, 1, 1, 1
        occupied = set()  # 已占用坐标
        for t in pool:
            cn = _cn(ii if t == "Infantry" else ci if t == "Cavalry" else
                     ai if t == "Artillery" else si)
            if t == "Infantry":
                name = f"第{cn}步兵连" if prefix == "friendly" else f"敌军步兵{cn}"
                ii += 1
            elif t == "Cavalry":
                name = f"第{cn}骑兵连" if prefix == "friendly" else f"敌军骑兵{cn}"
                ci += 1
            elif t == "Artillery":
                name = f"第{cn}炮兵连" if prefix == "friendly" else f"敌军炮兵{cn}"
                ai += 1
            else:
                name = f"侦察{cn}排" if prefix == "friendly" else f"敌军侦察{cn}"
                si += 1
            for _ in range(30):
                dx = rng.randint(-8, 8)
                dy = rng.randint(-8, 8)
                x = max(0, min(w - 1, hq.x + dx))
                y = max(0, min(h - 1, hq.y + dy))
                if terrain[y][x] != TerrainType.RIVER.value and (x, y) not in occupied:
                    occupied.add((x, y))
                    units.append({"unit_id": f"{prefix}_{t.lower()}_{len(units)+1:02d}",
                                  "name": name, "unit_type": t, "start_x": x, "start_y": y})
                    break
        units.append({"unit_id": f"{prefix}_hq", "name": "指挥部" if prefix == "friendly" else "敌军指挥部",
                      "unit_type": "HQ", "start_x": hq.x, "start_y": hq.y})
        return units

    @classmethod
    def _has_river(cls, terrain, w, h):
        return any(TerrainType.RIVER.value in r for r in terrain)

    @classmethod
    def _validate_size(cls, w, h):
        if not (MAP_MIN_SIZE <= w <= MAP_MAX_SIZE) or not (MAP_MIN_SIZE <= h <= MAP_MAX_SIZE):
            raise ValueError("尺寸越界")


def _cn(n):
    return "一二三四五六七八九十"[n - 1] if 1 <= n <= 10 else str(n)
