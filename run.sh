#!/usr/bin/env bash
set -e

echo "========================================"
echo "  BlindCommand — 盲棋指挥  v1.0.0"
echo "========================================"
echo ""

# ── 检查 Python ──────────────────────────
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "[错误] 未找到 Python。请安装 Python 3.11+。"
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)

# ── 虚拟环境（可选） ─────────────────────
if [ -f ".venv/bin/activate" ]; then
    echo "[信息] 激活虚拟环境 .venv"
    source .venv/bin/activate
fi

# ── 安装依赖 ─────────────────────────────
echo "[信息] 检查依赖..."
pip install -r requirements.txt -q 2>/dev/null || echo "[警告] 依赖安装失败，尝试继续启动..."

# ── 启动游戏 ─────────────────────────────
echo "[信息] 启动 BlindCommand..."
echo ""
$PYTHON -m src.main

# ── 退出 ─────────────────────────────────
if [ $? -ne 0 ]; then
    echo ""
    echo "[错误] 游戏异常退出 (code: $?)"
fi
