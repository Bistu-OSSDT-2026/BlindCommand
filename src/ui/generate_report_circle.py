"""
生成汇报圈素材 — 透明底灰铅笔手绘椭圆

输出: src/ui/assets/report_circle.png (512×512)
用途: 位置汇报时出现在地图上，短暂提示玩家"单位在这附近"
参数: RADIUS / DURATION / ALPHA 在 constants.py 中可调

依赖: pygame
运行: python src/ui/generate_report_circle.py
"""

import math
import random
import pygame

# ── 配置 ──────────────────────────────────────────────────
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "assets", "report_circle.png")
SIZE = 512                        # 输出尺寸
PENCIL_COLOR = (90, 85, 75)       # 灰铅笔色
EDGE_ALPHA = 60                   # 外圈透明度
FILL_ALPHA = 15                   # 内圈透明度
LINE_WIDTH = 3                    # 铅笔线宽
JITTER = 4                        # 手绘抖动幅度 (px)

# ── 初始化 ────────────────────────────────────────────────
pygame.init()
surface = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
rng = random.Random(42)           # 固定种子，结果可重现
cx = SIZE // 2
cy = SIZE // 2
base_radius = SIZE // 3           # 基础半径 (~170px)

# ── 画铅笔椭圆轮廓 ────────────────────────────────────────
num_points = 72                   # 轮廓采样点数

for _ in range(3):                # 画 3 圈，模拟铅笔反复描
    points = []
    for i in range(num_points):
        angle = 2 * math.pi * i / num_points
        # 不规则半径：手绘不会完美圆
        r = base_radius + rng.randint(-JITTER, JITTER)
        # 轻微椭圆化
        rx = r * 1.0
        ry = r * 0.95
        x = int(cx + rx * math.cos(angle) + rng.randint(-2, 2))
        y = int(cy + ry * math.sin(angle) + rng.randint(-2, 2))
        points.append((x, y))

    # 画不连续线段（模拟铅笔提起）
    i = 0
    while i < len(points) - 1:
        seg_len = rng.randint(4, 12)
        end = min(i + seg_len, len(points) - 1)
        for j in range(i, end):
            alpha_variation = rng.randint(-15, 5)
            alpha = max(10, EDGE_ALPHA + alpha_variation)
            pygame.draw.line(
                surface,
                (*PENCIL_COLOR, alpha),
                points[j],
                points[j + 1],
                LINE_WIDTH,
            )
        i = end + rng.randint(0, 2)  # 随机跳过 0-2 点（铅笔提起）

# ── 画内圈淡色填充 ─────────────────────────────────────────
# 在中心画一棵淡色填充，模拟铅笔侧锋涂抹
fill_radius = base_radius - 15
for _ in range(30):               # 多条短线段模拟涂抹
    angle = rng.random() * 2 * math.pi
    dist = rng.randint(0, fill_radius)
    x = int(cx + dist * math.cos(angle))
    y = int(cy + dist * math.sin(angle))
    pygame.draw.circle(
        surface,
        (*PENCIL_COLOR, rng.randint(FILL_ALPHA - 5, FILL_ALPHA + 5)),
        (x, y),
        rng.randint(3, 8),
    )

# ── 保存 ──────────────────────────────────────────────────
import os
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
pygame.image.save(surface, OUTPUT_PATH)
print(f"✅ 汇报圈已生成: {OUTPUT_PATH} ({SIZE}×{SIZE})")
pygame.quit()
