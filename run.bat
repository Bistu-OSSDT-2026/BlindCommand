@echo off
chcp 65001 >nul
title BlindCommand v1.0.0

echo ========================================
echo   BlindCommand — 盲棋指挥  v1.0.0
echo ========================================
echo.

:: ── 检查 Python ──────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python。请安装 Python 3.11 并添加到 PATH。
    pause
    exit /b 1
)

:: ── 虚拟环境（可选） ─────────────────────
if exist .venv\Scripts\activate.bat (
    echo [信息] 激活虚拟环境 .venv
    call .venv\Scripts\activate.bat
)

:: ── 安装依赖 ─────────────────────────────
echo [信息] 检查依赖...
pip install -r requirements.txt -q 2>nul
if %errorlevel% neq 0 (
    echo [警告] 依赖安装失败，尝试继续启动...
)

:: ── 启动游戏 ─────────────────────────────
echo [信息] 启动 BlindCommand...
echo.
python -m src.main

:: ── 退出 ─────────────────────────────────
if %errorlevel% neq 0 (
    echo.
    echo [错误] 游戏异常退出 (code: %errorlevel%)
)
pause
