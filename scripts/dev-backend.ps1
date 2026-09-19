# 启动后端开发服务器(带热重载)。
# 用法: powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# Windows 控制台默认 GBK,强制 UTF-8 避免中文日志乱码
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Set-Location "$root\backend"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "虚拟环境不存在,先创建并安装依赖..." -ForegroundColor Yellow
    python -m venv .venv
    & .\.venv\Scripts\pip.exe install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
}

& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
