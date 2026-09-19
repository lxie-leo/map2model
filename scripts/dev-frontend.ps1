# 启动前端开发服务器(自动代理到本地 8000 后端)。
# 用法: powershell -ExecutionPolicy Bypass -File scripts\dev-frontend.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Set-Location "$root\frontend"
if (-not (Test-Path "node_modules")) {
    Write-Host "依赖不存在,先安装..." -ForegroundColor Yellow
    $env:COREPACK_NPM_REGISTRY = "https://registry.npmmirror.com"
    corepack pnpm install --registry=https://registry.npmmirror.com
}

corepack pnpm dev
