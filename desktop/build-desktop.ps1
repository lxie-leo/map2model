# 桌面版一键打包:3.12 环境 + 前端 build + PyInstaller,产物在 desktop\dist\map2model\。
# 用法: powershell -ExecutionPolicy Bypass -File desktop\build-desktop.ps1 [-Smoke] [-SmokeTask] [-Zip]
#   -Smoke     打包完跑一遍快自检(起服务、断言 17 种导出格式都在,不开窗口)
#   -SmokeTask 跑深度自检(走真网络建真任务,15 种非 Blender 格式全真导一遍;需要联网)
#   -Zip       把产物压成 desktop\dist\map2model-desktop-windows-x64.zip

param(
    [switch]$Smoke,
    [switch]$SmokeTask,
    [switch]$Zip
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# Windows 控制台默认 GBK,强制 UTF-8 避免中文输出乱码
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# 本机 npm 是坏的,全程只认 pnpm(corepack 出的);Python 版本用 uv 钉死 3.12,
# 因为 mapbox-earcut 没有 3.14 的轮子
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "缺 uv(管 Python 版本用),先装:winget install astral-sh.uv" -ForegroundColor Red
    exit 1
}
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Host "缺 pnpm,先装:corepack enable" -ForegroundColor Red
    exit 1
}

# ---- 1. Python 3.12 环境(已存在就跳过安装步骤) ----
uv python install 3.12
if (-not (Test-Path "$root\.venv-desktop\Scripts\python.exe")) {
    Write-Host "创建桌面版构建虚拟环境(.venv-desktop)..." -ForegroundColor Yellow
    uv venv "$root\.venv-desktop" --python 3.12
}
uv pip install --python "$root\.venv-desktop\Scripts\python.exe" `
    -e "$root\backend[desktop,gis,usd]" `
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# ---- 2. 前端 build(没产物或源码比产物新才重打,日常迭代省一两分钟) ----
Set-Location "$root\frontend"
$distIndex = "dist\index.html"
$needBuild = -not (Test-Path $distIndex)
if (-not $needBuild) {
    $srcNewest = Get-ChildItem -Path src, index.html, vite.config.ts -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $needBuild = $srcNewest.LastWriteTime -gt (Get-Item $distIndex).LastWriteTime
}
if ($needBuild) {
    pnpm install --frozen-lockfile
    pnpm build
} else {
    Write-Host "前端 dist 是新的,跳过 build" -ForegroundColor DarkGray
}

# ---- 3. PyInstaller ----
# 旧产物还在运行的话会锁住 dist 里的文件,清理时一半删得掉一半删不掉,
# 出来的就是新旧混杂的脏产物 —— 直接拒绝打包,先关掉正在跑的 map2model
if (Get-Process map2model -ErrorAction SilentlyContinue) {
    Write-Host "map2model.exe 还在运行,锁着产物目录。先关掉它再打包。" -ForegroundColor Red
    exit 1
}
Set-Location "$root"
& "$root\.venv-desktop\Scripts\pyinstaller.exe" `
    desktop\map2model.spec --noconfirm `
    --distpath desktop\dist --workpath desktop\build

$exe = "$root\desktop\dist\map2model\map2model.exe"
if (-not (Test-Path $exe)) {
    Write-Host "打包失败:没找到 $exe" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "打包完成: $exe" -ForegroundColor Green
$size = [math]::Round((Get-ChildItem "$root\desktop\dist\map2model" -Recurse |
        Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "产物体积: ${size} MB"

# ---- 4. 自检(可选):真起一次打包产物,断言导出格式全可用 ----
$modes = @()
if ($Smoke) { $modes += "--smoke" }
if ($SmokeTask) { $modes += "--smoke-task" }
foreach ($mode in $modes) {
    Write-Host ""
    Write-Host "跑打包产物自检($mode)..." -ForegroundColor Yellow
    # exe 是无控制台的(windowed),PowerShell 调它不会等、$LASTEXITCODE 也是旧值,
    # 必须用 Start-Process -Wait 拿真实退出码
    $proc = Start-Process -FilePath $exe -ArgumentList $mode -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Write-Host "自检没过(退出码 $($proc.ExitCode)),产物别发出去" -ForegroundColor Red
        exit 1
    }
    Write-Host "自检通过" -ForegroundColor Green
}

# ---- 5. 压 zip(可选) ----
if ($Zip) {
    $zipPath = "$root\desktop\dist\map2model-desktop-windows-x64.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath }
    Compress-Archive -Path "$root\desktop\dist\map2model\*" -DestinationPath $zipPath
    $zipSize = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Host "压缩包: $zipPath (${zipSize} MB)" -ForegroundColor Green
}
