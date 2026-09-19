# 环境自检:检查 Python、Node、pnpm 和关键依赖是否就绪。
# 用法: powershell -ExecutionPolicy Bypass -File scripts\check_env.ps1

$ErrorActionPreference = "Continue"
$ok = $true

function Check($name, $cmd) {
    $out = & $cmd 2>$null
    if ($LASTEXITCODE -eq 0 -and $out) {
        Write-Host "[OK] $name : $out" -ForegroundColor Green
    } else {
        Write-Host "[缺失] $name" -ForegroundColor Red
        $script:ok = $false
    }
}

Write-Host "==== map2model 环境自检 ====" -ForegroundColor Cyan

Check "Python (>=3.11)" { python --version }
Check "Node.js (>=20)" { node --version }
Check "pnpm" { corepack pnpm --version }

# 后端关键依赖(在虚拟环境里)
if (Test-Path "..\backend\.venv\Scripts\python.exe") {
    Push-Location ..\backend
    & .\.venv\Scripts\python.exe -c "import fastapi, numpy, trimesh, shapely; print('后端依赖 OK')" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] 后端 Python 依赖" -ForegroundColor Green
    } else {
        Write-Host "[缺失] 后端 Python 依赖,先执行: pip install -e .[dev]" -ForegroundColor Red
        $script:ok = $false
    }
    Pop-Location
} else {
    Write-Host "[缺失] backend\.venv,先创建虚拟环境并安装依赖" -ForegroundColor Red
    $ok = $false
}

# 前端依赖
if (Test-Path "..\frontend\node_modules") {
    Write-Host "[OK] 前端 node_modules" -ForegroundColor Green
} else {
    Write-Host "[缺失] 前端依赖,先在 frontend 目录执行: corepack pnpm install" -ForegroundColor Red
    $ok = $false
}

# 可选:Blender(影响 fbx/dae 两种格式)
$blender = Get-ChildItem "C:\Program Files\Blender Foundation" -Filter "blender.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($blender) {
    Write-Host "[OK] Blender: $($blender.FullName)" -ForegroundColor Green
} else {
    Write-Host "[可选] 未检测到 Blender(fbx/dae 导出不可用,其余格式不受影响)" -ForegroundColor Yellow
}

if ($ok) {
    Write-Host "环境就绪!" -ForegroundColor Green
} else {
    Write-Host "有缺失项,按提示补齐后再运行。" -ForegroundColor Yellow
    exit 1
}
