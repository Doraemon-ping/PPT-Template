param([string]$Root = '')
$ErrorActionPreference = 'Stop'
# HPDC DFM 报告自动生成器 —— Windows x64 独立版构建脚本
# 用法：powershell -ExecutionPolicy Bypass -File packaging\build_win64.ps1 [-Root <项目根目录>]
if (-not $Root) {
    if ($PSScriptRoot) { $Root = Split-Path -Parent $PSScriptRoot }
    elseif ($MyInvocation.MyCommand.Path) { $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path) }
    else { $Root = (Get-Location).Path }
}
$py = 'C:\Users\26257\AppData\Local\Python\pythoncore-3.14-64\python.exe'

Write-Host "[1/3] PyInstaller 构建 (onedir)..."
& $py -m PyInstaller (Join-Path $PSScriptRoot 'dfm_standalone.spec') --noconfirm --clean `
    --distpath (Join-Path $PSScriptRoot 'build_dist') `
    --workpath (Join-Path $PSScriptRoot 'build_work')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$built = Join-Path $PSScriptRoot 'build_dist\HPDC_DFM_Generator'
if (-not (Test-Path (Join-Path $built 'HPDC_DFM_Generator.exe'))) { throw "exe not found under $built" }

Write-Host "[2/3] 组装发布目录..."
$releaseRoot = Join-Path $root 'release'
$name = 'DFM报告生成器_win64'
$dest = Join-Path $releaseRoot $name
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
Copy-Item $built $dest -Recurse

# 内置演示模板（registry 的 demo/pilot/table-demo 等；exact 大模板不打包）
$tmplSrc = Join-Path $root 'templates'
$tmplDst = Join-Path $dest 'templates'
New-Item -ItemType Directory -Force -Path $tmplDst | Out-Null
Get-ChildItem -Path $tmplSrc -Filter '*.pptx' | Where-Object { $_.Name -notmatch 'exact' } |
    Copy-Item -Destination $tmplDst

# 运行期数据目录（空，首次启动自动写入）
New-Item -ItemType Directory -Force -Path (Join-Path $dest 'data') | Out-Null

# ===== 用户数据（跟随发布包分发） =====
# 绑定方案（模板工作台保存的 .json）
Copy-Item (Join-Path $root 'data\schemes') (Join-Path $dest 'data\schemes') -Recurse -ErrorAction SilentlyContinue
# 已上传模板（data/templates/<id>/master.pptx + registry.json）
Copy-Item (Join-Path $root 'data\templates') (Join-Path $dest 'data\templates') -Recurse -ErrorAction SilentlyContinue
# 表单存档
Copy-Item (Join-Path $root 'data\project.json') (Join-Path $dest 'data\project.json') -ErrorAction SilentlyContinue
# 表单平台数据库（/forms「载入项目」的数据源：platform.sqlite3 + 各应用数据）
Copy-Item (Join-Path $root 'data\form_platform') (Join-Path $dest 'data\form_platform') -Recurse -ErrorAction SilentlyContinue
# 官方 84 页模板（registry 内置 official 的路径）；存在才随包分发
if (Test-Path (Join-Path $root '1-基础数据')) {
    Copy-Item (Join-Path $root '1-基础数据') (Join-Path $dest '1-基础数据') -Recurse
}
# 说明：预览缓存（template_previews/、dfm-live-preview-*）、日志与测试残留不入包

# 使用说明
Copy-Item (Join-Path $PSScriptRoot '使用说明.txt') (Join-Path $dest '使用说明.txt') -ErrorAction SilentlyContinue

# build_dist 是 PyInstaller 中间产物，不含运行期模板/数据，不能直接作为交付包。
# 交付前确认最终发布目录含有工作台预览必需的脚本和内置模板。
$required = @(
    (Join-Path $dest 'HPDC_DFM_Generator.exe'),
    (Join-Path $dest '_internal\tools\preview_worker.ps1'),
    (Join-Path $dest '_internal\tools\export_slide_preview.ps1'),
    (Join-Path $dest '_internal\tools\check_preview_environment.ps1'),
    (Join-Path $dest 'templates\DFM_Template_Placeholder_Demo.pptx'),
    (Join-Path $dest '使用说明.txt')
)
$missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($missing.Count -gt 0) {
    throw "发布包不完整，缺少：$($missing -join '；')"
}

$zip = Join-Path $releaseRoot ($name + '.zip')
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path $dest -DestinationPath $zip -Force
if (-not (Test-Path -LiteralPath (Join-Path $dest 'HPDC_DFM_Generator.exe'))) {
    throw "压缩后发布目录意外丢失：$dest"
}

Write-Host "[3/3] 完成发布目录: $dest"
Write-Host "      可分发压缩包: $zip"
Write-Host "      注意：原页/实时 PNG 预览仍需目标 Windows 安装桌面版 Microsoft PowerPoint。"
