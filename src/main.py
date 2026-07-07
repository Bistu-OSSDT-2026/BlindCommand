"""
BlindCommand 游戏入口
====================
启动 pygame 窗口，组装 UI 子面板，进入主循环。

运行：python -m src.main

版本：v0.2.0 — Sprint 1 UI 原型
"""

import logging
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ui.main_window import MainWindow

# ── 日志配置 ────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    """游戏入口。创建 MainWindow 并启动主循环。"""
    logger = logging.getLogger("main")
    logger.info("BlindCommand v0.2.0 — Sprint 1 UI 原型")
    logger.info("窗口尺寸: 1280×800, 30 FPS")
    logger.info("关闭窗口或按 ESC 退出, SPACE 打印调试信息")

    window = MainWindow()
    window.run()


if __name__ == "__main__":
    main()
