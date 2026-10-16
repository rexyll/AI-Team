#!/usr/bin/env bash
# stringkit — POSIX 部署引导脚本
# 用法: 在解压后的目录内运行: bash install.sh
set -euo pipefail

echo "=== stringkit 部署开始 ==="
if ! command -v python >/dev/null 2>&1; then
    echo "未检测到 python，请先安装 Python 3.10+" >&2
    exit 1
fi

# 1) 可选虚拟环境
if [ "${CREATE_VENV:-0}" = "1" ]; then
    python -m venv .venv
    ./.venv/bin/python -m pip install --upgrade pip
fi

# 2) 依赖安装（如声明了 requirements.txt）
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
fi

# 3) 部署冒烟验证
python -m pytest stringkit/tests/test_stringops.py

echo "=== 部署完成，冒烟验证通过 ==="
