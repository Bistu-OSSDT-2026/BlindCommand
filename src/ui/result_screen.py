"""
结算画面 — 胜利/失败全屏覆盖
===============================
"""

import pygame

FONT_PATH = "C:/Windows/Fonts/simhei.ttf"
COLOR_BG = (26, 26, 26, 240)
COLOR_WIN = (200, 180, 60)
COLOR_LOSE = (180, 60, 60)
COLOR_TEXT = (220, 220, 200)


def show_result(victory: bool, kills: int, alive: int, elapsed: float) -> bool:
    """显示结算画面。返回 True = 重新开始，False = 退出。"""
    pygame.init()
    screen = pygame.display.set_mode((800, 500))
    pygame.display.set_caption("战斗结束")
    clock = pygame.time.Clock()
    font_title = pygame.font.Font(FONT_PATH, 48)
    font_info = pygame.font.Font(FONT_PATH, 22)
    font_btn = pygame.font.Font(FONT_PATH, 20)

    result_text = "🏆 胜利！" if victory else "💀 败北"
    result_color = COLOR_WIN if victory else COLOR_LOSE
    mins, secs = divmod(int(elapsed), 60)

    btn = pygame.Rect(300, 380, 200, 50)

    running = True
    restart = False
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if btn.collidepoint(event.pos):
                    restart = True
                    running = False

        screen.fill((26, 26, 26))

        # 结果
        t = font_title.render(result_text, True, result_color)
        screen.blit(t, ((800 - t.get_width()) // 2, 60))

        # 统计
        lines = [
            f"消灭敌军: {kills} 支",
            f"己方存活: {alive} 支",
            f"战斗耗时: {mins}分{secs}秒",
        ]
        for i, line in enumerate(lines):
            s = font_info.render(line, True, COLOR_TEXT)
            screen.blit(s, ((800 - s.get_width()) // 2, 160 + i * 38))

        # 按钮
        pygame.draw.rect(screen, (60, 60, 60), btn, border_radius=8)
        b = font_btn.render("重新开始", True, COLOR_TEXT)
        screen.blit(b, (btn.centerx - b.get_width() // 2, btn.centery - b.get_height() // 2))

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    return restart
