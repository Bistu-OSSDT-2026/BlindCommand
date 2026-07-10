"""
BlindCommand UI 音效系统 — Sprint 3
=====================================
使用 pygame.mixer 生成简单的合成音效作为 UI 反馈。
所有音效在初始化时预生成，无需外部音频文件。

音效列表:
    - ui_click: 按钮点击 (短促 pip)
    - command_sent: 指令发出 (上升音)
    - enemy_spotted: 发现敌军 (警告音)
    - unit_killed: 单位阵亡 (低沉咚)
    - victory: 胜利 (三连音)
    - defeat: 失败 (下降音)

约束: 不依赖 src/battle/ 或 src/core/ 内部实现。

版本: v0.1.0 — Sprint 3
"""

from __future__ import annotations

import array
import logging
import math
from typing import Optional

import pygame

logger = logging.getLogger(__name__)

# ── 音效参数 ────────────────────────────────────────────────────────────

SAMPLE_RATE = 22050  # Hz


def _generate_sine_wave(
    frequency: float,
    duration_ms: int,
    volume: float = 0.3,
    fade_out_ms: int = 20,
) -> pygame.mixer.Sound:
    """生成纯正弦波音效。

    Args:
        frequency: 频率（Hz）
        duration_ms: 持续时间（毫秒）
        volume: 音量（0.0~1.0）
        fade_out_ms: 末尾渐隐时间（毫秒）

    Returns:
        pygame.mixer.Sound 对象
    """
    num_samples = int(SAMPLE_RATE * duration_ms / 1000)
    fade_samples = int(SAMPLE_RATE * fade_out_ms / 1000)

    samples = array.array("h", [0] * num_samples)  # 16-bit signed
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        value = int(32767 * volume * math.sin(2 * math.pi * frequency * t))

        # 末尾渐隐
        if fade_samples > 0 and i >= num_samples - fade_samples:
            fade_factor = (num_samples - i) / fade_samples
            value = int(value * fade_factor)

        samples[i] = max(-32768, min(32767, value))

    return pygame.mixer.Sound(buffer=samples.tobytes())


def _generate_chirp(
    freq_start: float,
    freq_end: float,
    duration_ms: int,
    volume: float = 0.3,
) -> pygame.mixer.Sound:
    """生成频率扫描音效（上升/下降）。

    Args:
        freq_start: 起始频率
        freq_end: 结束频率
        duration_ms: 持续时间
        volume: 音量

    Returns:
        pygame.mixer.Sound 对象
    """
    num_samples = int(SAMPLE_RATE * duration_ms / 1000)
    samples = array.array("h", [0] * num_samples)
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        progress = i / num_samples
        freq = freq_start + (freq_end - freq_start) * progress
        value = int(32767 * volume * math.sin(2 * math.pi * freq * t))
        samples[i] = max(-32768, min(32767, value))
    return pygame.mixer.Sound(buffer=samples.tobytes())


# ── SoundManager ────────────────────────────────────────────────────────


class SoundManager:
    """UI 音效管理器。

    在 __init__ 中预生成所有音效。各模块通过 play_*() 方法触发。
    若 pygame.mixer 不可用（无音频设备），所有方法静默降级。
    """

    def __init__(self) -> None:
        """初始化音效系统。预生成所有合成音效。"""
        self._enabled: bool = True

        try:
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1)
        except pygame.error:
            logger.info("音频设备不可用，音效系统已禁用")
            self._enabled = False

        self._sounds: dict[str, Optional[pygame.mixer.Sound]] = {}
        if self._enabled:
            self._generate_all_sounds()

    def _generate_all_sounds(self) -> None:
        """预生成所有 UI 音效。"""
        try:
            self._sounds["ui_click"] = _generate_sine_wave(800, 60, 0.25)
            self._sounds["command_sent"] = _generate_chirp(600, 900, 150, 0.3)
            self._sounds["enemy_spotted"] = _generate_chirp(400, 800, 200, 0.35)
            self._sounds["unit_killed"] = _generate_sine_wave(150, 300, 0.4, fade_out_ms=100)
            self._sounds["victory"] = _generate_chirp(400, 1200, 500, 0.35)
            self._sounds["defeat"] = _generate_chirp(600, 150, 500, 0.35)
            self._sounds["turn_start"] = _generate_sine_wave(500, 80, 0.2)
            logger.info("音效系统就绪 (%d 个音效)", len(self._sounds))
        except Exception:
            logger.exception("音效生成失败，已禁用")
            self._enabled = False

    # ── 公开 API ──────────────────────────────────────────────────────

    def play_ui_click(self) -> None:
        """播放按钮点击音效。"""
        self._play("ui_click")

    def play_command_sent(self) -> None:
        """播放指令发出音效。"""
        self._play("command_sent")

    def play_enemy_spotted(self) -> None:
        """播放发现敌军音效。"""
        self._play("enemy_spotted")

    def play_unit_killed(self) -> None:
        """播放单位阵亡音效。"""
        self._play("unit_killed")

    def play_victory(self) -> None:
        """播放胜利音效。"""
        self._play("victory")

    def play_defeat(self) -> None:
        """播放失败音效。"""
        self._play("defeat")

    def play_turn_start(self) -> None:
        """播放回合开始音效。"""
        self._play("turn_start")

    # ── 内部 ─────────────────────────────────────────────────────────

    def _play(self, name: str) -> None:
        """播放指定音效（静默降级）。

        Args:
            name: 音效名称
        """
        if not self._enabled:
            return
        sound = self._sounds.get(name)
        if sound is not None:
            sound.play()

    @property
    def enabled(self) -> bool:
        """音效系统是否可用。"""
        return self._enabled


# ── 全局单例 ──────────────────────────────────────────────────────────

# 各模块直接 import 此实例:
#   from src.ui.sounds import sound_manager
sound_manager = SoundManager()
