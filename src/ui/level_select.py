"""
关卡选择界面 — 全屏菜单
==========================
简单 5v5 20×15 / 中等 10v10 34×25 / 困难 15v15 34×25
"""

import pygame

FONT_PATH = "C:/Windows/Fonts/simhei.ttf"
COLOR_BG = (26, 26, 26)
COLOR_TITLE = (220, 200, 160)
COLOR_BTN = (60, 60, 60)
COLOR_BTN_HOVER = (100, 100, 60)
COLOR_TEXT = (220, 220, 200)

LEVELS = [
    {"name": "简单", "desc": "5v5 · 20×15", "units": 5, "width": 20, "height": 15},
    {"name": "中等", "desc": "10v10 · 34×25", "units": 10, "width": 34, "height": 25},
    {"name": "困难", "desc": "15v15 · 34×25", "units": 15, "width": 34, "height": 25},
]


def show_level_select() -> dict | None:
    """显示关卡选择界面，返回选中的关卡配置或 None（退出）。"""
    pygame.init()
    screen = pygame.display.set_mode((800, 500))
    pygame.display.set_caption("BlindCommand — 选择关卡")
    clock = pygame.time.Clock()
    font_title = pygame.font.Font(FONT_PATH, 36)
    font_btn = pygame.font.Font(FONT_PATH, 22)
    font_desc = pygame.font.Font(FONT_PATH, 16)

    btn_w, btn_h = 200, 60
    btn_y_start = 180
    btn_gap = 90

    btns = []
    for i, lv in enumerate(LEVELS):
        rx = (800 - btn_w) // 2
        ry = btn_y_start + i * btn_gap
        btns.append(pygame.Rect(rx, ry, btn_w, btn_h))

    running = True
    selected = None

    while running:
        mouse_pos = pygame.mouse.get_pos()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for i, r in enumerate(btns):
                    if r.collidepoint(mouse_pos):
                        selected = LEVELS[i]
                        running = False

        screen.fill(COLOR_BG)

        # 标题
        title = font_title.render("BlindCommand — 盲棋指挥", True, COLOR_TITLE)
        screen.blit(title, ((800 - title.get_width()) // 2, 60))

        # 按钮
        for i, (lv, r) in enumerate(zip(LEVELS, btns)):
            hover = r.collidepoint(mouse_pos)
            color = COLOR_BTN_HOVER if hover else COLOR_BTN
            pygame.draw.rect(screen, color, r, border_radius=8)
            txt = font_btn.render(lv["name"], True, COLOR_TEXT)
            screen.blit(txt, (r.centerx - txt.get_width() // 2, r.centery - txt.get_height() // 2 - 6))
            dsc = font_desc.render(lv["desc"], True, (160, 160, 140))
            screen.blit(dsc, (r.centerx - dsc.get_width() // 2, r.bottom + 4))

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    return selected
