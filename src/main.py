"""
BlindCommand 游戏入口
====================
Phase 0 骨架窗口 — 验证环境、为 #4 提供 UI 开发起点。

运行：python -m src.main

版本：v0.1.0
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pygame

from src.core.constants import (
    BATTLE_LOG_BG_COLOR,
    BATTLE_LOG_WIDTH_RATIO,
    COMMAND_PANEL_BG_COLOR,
    COMMAND_PANEL_HEIGHT,
    MAP_AREA_WIDTH_RATIO,
    WINDOW_HEIGHT,
    WINDOW_TITLE,
    WINDOW_WIDTH,
)

# ============================================================================
# 颜色常量（骨架阶段硬编码，后续可迁移到 constants.py）
# ============================================================================

COLOR_BG          = (30, 30, 30)    # 整体背景
COLOR_PANEL_BG    = (26, 26, 26)    # 面板背景
COLOR_BORDER      = (60, 60, 60)    # 分隔线
COLOR_TEXT        = (200, 200, 200) # 文本色
COLOR_WHITE       = (255, 255, 255)

# ============================================================================
# 面板布局计算
# ============================================================================


def calculate_layout(window_w: int, window_h: int) -> dict:
    """根据窗口尺寸计算各面板的矩形区域。

    Returns:
        {
            "battle_log_rect": pygame.Rect,   # 左侧战报面板
            "map_rect":        pygame.Rect,   # 中间地图区域
            "command_rect":    pygame.Rect,   # 底部指令栏
        }
    """
    map_area_top = 0
    map_area_bottom = window_h - COMMAND_PANEL_HEIGHT

    battle_log_width = int(window_w * BATTLE_LOG_WIDTH_RATIO)
    map_width = window_w - battle_log_width

    return {
        "battle_log_rect": pygame.Rect(0, 0, battle_log_width, map_area_bottom),
        "map_rect": pygame.Rect(battle_log_width, 0, map_width, map_area_bottom),
        "command_rect": pygame.Rect(0, map_area_bottom, window_w, COMMAND_PANEL_HEIGHT),
    }


# ============================================================================
# 骨架渲染
# ============================================================================


def draw_panel_border(screen: pygame.Surface, rect: pygame.Rect, color: tuple) -> None:
    """绘制面板边框（1px 线）。"""
    pygame.draw.rect(screen, color, rect, 1)


def draw_placeholder_text(
    screen: pygame.Surface,
    rect: pygame.Rect,
    text: str,
    font: pygame.font.Font,
    color: tuple,
) -> None:
    """在矩形中央绘制占位文字。"""
    text_surf = font.render(text, True, color)
    text_rect = text_surf.get_rect(center=rect.center)
    screen.blit(text_surf, text_rect)


def render_skeleton(screen: pygame.Surface, font: pygame.font.Font) -> None:
    """渲染 Phase 0 骨架界面。

    左侧：战报面板占位
    中间：地图区域占位
    底部：指令栏占位
    """
    layout = calculate_layout(screen.get_width(), screen.get_height())

    # 背景
    screen.fill(COLOR_BG)

    # ── 左侧战报面板 ──────────────────────────────────────────────
    battle_rect = layout["battle_log_rect"]
    pygame.draw.rect(screen, (26, 26, 26), battle_rect)
    draw_panel_border(screen, battle_rect, COLOR_BORDER)
    draw_placeholder_text(screen, battle_rect, "战报面板\nBattle Log", font, COLOR_TEXT)

    # ── 中间地图区域 ──────────────────────────────────────────────
    map_rect = layout["map_rect"]
    pygame.draw.rect(screen, (40, 40, 40), map_rect)
    draw_panel_border(screen, map_rect, COLOR_BORDER)
    draw_placeholder_text(
        screen, map_rect, "地图区域\nMap Area\n(20 × 15)", font, COLOR_TEXT
    )

    # ── 底部指令栏 ────────────────────────────────────────────────
    cmd_rect = layout["command_rect"]
    pygame.draw.rect(screen, (42, 42, 42), cmd_rect)
    draw_panel_border(screen, cmd_rect, COLOR_BORDER)
    draw_placeholder_text(
        screen, cmd_rect, "指令栏  [MOVE] [ATTACK] [HOLD] [SCOUT] [RETREAT] [CAPTURE] [PATROL]", font, COLOR_TEXT
    )

    # ── 面板分隔线 ────────────────────────────────────────────────
    divider_x = battle_rect.right
    pygame.draw.line(
        screen, COLOR_BORDER, (divider_x, 0), (divider_x, battle_rect.bottom), 2
    )
    divider_y = battle_rect.bottom
    pygame.draw.line(
        screen, COLOR_BORDER, (0, divider_y), (screen.get_width(), divider_y), 2
    )


# ============================================================================
# 主函数
# ============================================================================


def main() -> None:
    """游戏入口。"""
    # 初始化 pygame
    pygame.init()
    pygame.display.set_caption(WINDOW_TITLE)

    # 创建窗口
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    clock = pygame.time.Clock()

    # 字体
    font = pygame.font.SysFont("Microsoft YaHei, SimHei, Arial", 18, bold=True)

    running = True
    frame_count = 0

    print(f"BlindCommand v0.1.0 — Phase 0 骨架窗口")
    print(f"窗口尺寸: {WINDOW_WIDTH}×{WINDOW_HEIGHT}")
    print(f"关闭窗口或按 ESC 退出")
    print(f"按 SPACE 打印事件总线状态（预留）")
    print()

    while running:
        # ── 事件处理 ──────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    print(f"[Frame {frame_count}] 窗口运行中 — 等待 #2 #3 #4 挂载模块")

        # ── 渲染 ──────────────────────────────────────────────────
        render_skeleton(screen, font)
        pygame.display.flip()

        # ── 帧率控制 ──────────────────────────────────────────────
        clock.tick(30)  # 30 FPS（游戏循环后续改为回合制时调整）
        frame_count += 1

    pygame.quit()
    print("BlindCommand 已退出。")


if __name__ == "__main__":
    main()
