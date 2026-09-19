# 一键启动前后端(两个窗口分别跑后端和前端)。
# 用法: powershell -ExecutionPolicy Bypass -File scripts\run_all.ps1

$ErrorActionPreference = "Stop"

# Start-Process 开新窗口跑,各自 Ctrl+C 退出
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$PSScriptRoot\dev-backend.ps1`""
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$PSScriptRoot\dev-frontend.ps1`""

Write-Host "后端: http://127.0.0.1:8000 (API 文档 /docs)" -ForegroundColor Cyan
Write-Host "前端: http://127.0.0.1:5173" -ForegroundColor Cyan
