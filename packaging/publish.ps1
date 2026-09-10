param(
    [string]$Root = '',          # 项目根目录（默认取脚本上一级）
    [switch]$SkipBuild,          # 跳过 PyInstaller 重建（复用 packaging\build_dist）
    [switch]$SkipVerify,         # 跳过打包后的自动冒烟验证
    [switch]$SkipZip,            # 跳过生成 zip 分发包
    [string]$Version = ''        # 版本号，如 1.0.1；写入包内 版本信息.txt
)
$ErrorActionPreference = 'Stop'
# ============================================================
#  HPDC DFM 报告自动生成器 —— 一键打包发布脚本
#  用法（在项目根目录）：
#     powershell -ExecutionPolicy Bypass -File packaging\publish.ps1 -Version 1.0.1
#     powershell -ExecutionPolicy Bypass -File packaging\publish.ps1 -SkipBuild -SkipZip
#  说明：脚本文件必须保存为 UTF-8 with BOM，否则中文在 Windows PowerShell 5.1 下会乱码。
# ============================================================

# ---------- 路径与工具 ----------
if (-not $Root) {
    if ($PSScriptRoot) { $Root = Split-Path -Parent $PSScriptRoot }
    elseif ($MyInvocation.MyCommand.Path) { $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
    else { $Root = (Get-Location).Path }
}
$packaging = Join-Path $Root 'packaging'
$distPath  = Join-Path $packaging 'build_dist'
$workPath  = Join-Path $packaging 'build_work'
$specFile  = Join-Path $packaging 'dfm_standalone.spec'
$relName   = 'DFM报告生成器_win64'
$buildName = 'HPDC_DFM_Generator'   # PyInstaller spec 的 APP_NAME（build_dist 下产物目录名）
$dest      = Join-Path (Join-Path $Root 'release') $relName
$zipPath   = Join-Path (Join-Path $Root 'release') ($relName + '.zip')

function Write-Step([int]$n, [int]$total, [string]$msg) {
    Write-Host ""
    Write-Host ("[{0}/{1}] {2}" -f $n, $total, $msg) -ForegroundColor Cyan
}

# 查找装有 PyInstaller 的 Python：环境变量 DFM_PYTHON > 本机已知路径 > PATH 上的 python
function Resolve-Python {
    $candidates = @()
    if ($env:DFM_PYTHON) { $candidates += $env:DFM_PYTHON }
    $candidates += 'C:\Users\26257\AppData\Local\Python\pythoncore-3.14-64\python.exe'
    $candidates += 'python'
    foreach ($c in $candidates) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        $path = if ($cmd) { $cmd.Source } else { $c }
        if (Test-Path -LiteralPath $path) {
            & $path -m PyInstaller --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $path }
        }
    }
    throw "未找到装有 PyInstaller 的 Python。请设置环境变量 DFM_PYTHON 指向该 python.exe。"
}

# 稳健删除（目录/文件），处理资源管理器/杀毒瞬时占用
function Remove-Path([string]$path, [int]$tries = 8) {
    for ($i = 1; $i -le $tries; $i++) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (-not (Test-Path -LiteralPath $path)) { return }
        if (Test-Path -LiteralPath $path -PathType Container) {
            cmd /c "rmdir /s /q `"$path`"" 2>$null | Out-Null
        } else {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        }
        if (-not (Test-Path -LiteralPath $path)) { return }
        Start-Sleep -Milliseconds 1500
    }
    throw "无法删除（可能被资源管理器/其他程序占用）: $path"
}

# 挑选空闲端口用于冒烟测试
function Get-FreePort([int]$preferred = 8790) {
    for ($port = $preferred; $port -lt $preferred + 100; $port++) {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
        try { $listener.Start(); return $port }
        catch { }
        finally { $listener.Stop() }
    }
    return $preferred
}

# ============================================================
$totalSteps = 5
if ($SkipBuild)  { $totalSteps-- }
if ($SkipVerify) { $totalSteps-- }
if ($SkipZip)    { $totalSteps-- }
$step = 0

Write-Host "========== DFM 打包发布 ==========" -ForegroundColor Green
Write-Host "项目根目录: $Root"
Write-Host "版本号:     $(if ($Version) { $Version } else { '（未指定）' })"

# ---------- [1] PyInstaller 构建 ----------
if (-not $SkipBuild) {
    $step++; Write-Step $step $totalSteps 'PyInstaller 构建 (onedir)'
    $py = Resolve-Python
    Write-Host "使用 Python: $py"
    Remove-Path $distPath
    Remove-Path $workPath
    & $py -m PyInstaller $specFile --noconfirm --clean `
        --distpath $distPath `
        --workpath $workPath
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败 (exit $LASTEXITCODE)" }
}

$builtExe = Join-Path $distPath "$buildName\HPDC_DFM_Generator.exe"
if (-not (Test-Path -LiteralPath $builtExe)) {
    throw "未找到构建产物: $builtExe（请勿使用 -SkipBuild，或先完整构建一次）"
}

# ---------- [2] 组装发布目录 ----------
$step++; Write-Step $step $totalSteps '组装发布目录（程序 + 数据 + 模板）'
Remove-Path $dest
New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
Copy-Item -LiteralPath (Join-Path $distPath $buildName) -Destination $dest -Recurse

# 内置演示模板（demo/pilot/table-demo 等；36MB 的 exact 派生大模板不入包）
$tmplSrc = Join-Path $Root 'templates'
if (Test-Path $tmplSrc) {
    $tmplDst = Join-Path $dest 'templates'
    New-Item -ItemType Directory -Force -Path $tmplDst | Out-Null
    Get-ChildItem -Path $tmplSrc -Filter '*.pptx' | Where-Object { $_.Name -notmatch 'exact' } |
        Copy-Item -Destination $tmplDst
}

# 用户数据（跟随发布包分发）
$dataDst = Join-Path $dest 'data'
New-Item -ItemType Directory -Force -Path $dataDst | Out-Null
Copy-Item (Join-Path $Root 'data\schemes')        (Join-Path $dataDst 'schemes')        -Recurse -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root 'data\templates')       (Join-Path $dataDst 'templates')       -Recurse -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root 'data\project.json')    (Join-Path $dataDst 'project.json')    -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root 'data\form_platform')   (Join-Path $dataDst 'form_platform')   -Recurse -ErrorAction SilentlyContinue

# 官方 84 页模板（registry 内置 official 的路径），存在才随包分发
if (Test-Path (Join-Path $Root '1-基础数据')) {
    Copy-Item (Join-Path $Root '1-基础数据') (Join-Path $dest '1-基础数据') -Recurse
}

# 使用说明 + 版本信息
Copy-Item (Join-Path $packaging '使用说明.txt') (Join-Path $dest '使用说明.txt') -ErrorAction SilentlyContinue
$gitHash = ''
try { $gitHash = (git -C $Root rev-parse --short HEAD 2>$null) } catch { }
$versionText = @"
版本:        $(if ($Version) { $Version } else { '未指定' })
构建时间:    $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Git 提交:    $gitHash
程序入口:    HPDC_DFM_Generator.exe
数据目录:    data\（方案 / 上传模板 / 平台项目 / 表单存档）
官方模板:    1-基础数据\（84 页 DFM 交流模板）
"@
[System.IO.File]::WriteAllText((Join-Path $dest '版本信息.txt'), $versionText, (New-Object System.Text.UTF8Encoding($true)))
Write-Host "发布目录: $dest"

# ---------- [3] 冒烟验证 ----------
$verifyOk = $true
if (-not $SkipVerify) {
    $step++; Write-Step $step $totalSteps '自动冒烟验证（启动 exe 检查关键接口）'
    $exe  = Join-Path $dest 'HPDC_DFM_Generator.exe'
    $port = Get-FreePort
    $env:DFM_PORT = "$port"
    $env:DFM_NO_BROWSER = '1'
    $outLog = Join-Path $workPath 'publish_smoke.out.log'
    $errLog = Join-Path $workPath 'publish_smoke.err.log'
    New-Item -ItemType Directory -Force -Path $workPath | Out-Null
    $proc = Start-Process -FilePath $exe -WorkingDirectory $dest -PassThru `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) { break }
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
    }
    try {
        if (-not $ready) { throw '服务未在 30 秒内就绪' }
        $t  = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/templates" -TimeoutSec 15
        $s  = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/schemes"   -TimeoutSec 15
        $fp = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/form-apps/dfm/projects" -TimeoutSec 15
        $listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        Write-Host "模板 $($t.templates.Count) 项 / 方案 $($s.schemes.Count) 个 / 平台项目 $($fp.projects.Count) 个 / 监听 $($listening.LocalAddress)"
        if ($t.templates.Count -eq 0) { throw '模板列表为空' }
    } catch {
        $verifyOk = $false
        Write-Host "验证失败: $($_.Exception.Message)" -ForegroundColor Red
        if (Test-Path $errLog) { Get-Content $errLog -Tail 15 }
    } finally {
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
        Remove-Item Env:\DFM_PORT -ErrorAction SilentlyContinue
        Remove-Item Env:\DFM_NO_BROWSER -ErrorAction SilentlyContinue
        Remove-Item (Join-Path $dest 'data\server.log') -ErrorAction SilentlyContinue
        Remove-Item $outLog, $errLog -ErrorAction SilentlyContinue
    }
    if (-not $verifyOk) { throw '冒烟验证未通过，已中止（可用 -SkipVerify 跳过）' }
}

# ---------- [4] 生成 zip ----------
if (-not $SkipZip) {
    $step++; Write-Step $step $totalSteps '生成 zip 分发包'
    Remove-Path $zipPath
    Compress-Archive -Path $dest -DestinationPath $zipPath -CompressionLevel Optimal
    Write-Host "zip: $zipPath"
}

# ---------- [5] 汇总 ----------
$step++; Write-Step $step $totalSteps '完成'
$sizeMB = [math]::Round(((Get-ChildItem $dest -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "发布目录: $dest  ($sizeMB MB)" -ForegroundColor Green
if (Test-Path $zipPath) {
    $zipMB = [math]::Round(((Get-Item $zipPath).Length / 1MB), 1)
    Write-Host "分发包:   $zipPath  ($zipMB MB)" -ForegroundColor Green
}
Write-Host "本机使用:   双击 $dest\HPDC_DFM_Generator.exe" -ForegroundColor Green
Write-Host "========== 打包发布完成 ==========" -ForegroundColor Green
