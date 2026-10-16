# stringkit — Windows 部署引导脚本
# 用法: 在解压后的目录内以管理员或普通用户身份运行:
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"

Write-Host "=== stringkit 部署开始 ==="
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "未检测到 python，请先安装 Python 3.10+ 并加入 PATH。"
}

# 1) 可选虚拟环境
if ($env:CREATE_VENV -eq "1") {
    python -m venv .venv
    & .venv\Scripts\python.exe -m pip install --upgrade pip
}

# 2) 依赖安装（如声明了 requirements.txt）
if (Test-Path "requirements.txt") {
    pip install -r requirements.txt
}

# 3) 部署冒烟验证
python -m pytest stringkit/tests/test_stringops.py
if ($LASTEXITCODE -ne 0) { throw "部署冒烟验证失败" }

Write-Host "=== 部署完成，冒烟验证通过 ==="
