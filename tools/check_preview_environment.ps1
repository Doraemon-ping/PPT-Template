param(
    [string]$Root = ''
)

$ErrorActionPreference = 'Stop'
if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path $Root).Path

$shell = Get-Command pwsh.exe -ErrorAction SilentlyContinue
if (-not $shell) { $shell = Get-Command powershell.exe -ErrorAction SilentlyContinue }
$worker = Join-Path $Root 'tools\preview_worker.ps1'
$exporter = Join-Path $Root 'tools\export_slide_preview.ps1'

$result = [ordered]@{
    computer = $env:COMPUTERNAME
    user = "$env:USERDOMAIN\$env:USERNAME"
    powershell = if ($shell) { $shell.Source } else { $null }
    worker_script = [ordered]@{ path = $worker; exists = (Test-Path -LiteralPath $worker) }
    exporter_script = [ordered]@{ path = $exporter; exists = (Test-Path -LiteralPath $exporter) }
    powerpoint = [ordered]@{ available = $false; version = $null; error = $null }
}

$powerPoint = $null
try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $result.powerpoint.available = $true
    try { $result.powerpoint.version = [string]$powerPoint.Version } catch { }
} catch {
    $result.powerpoint.error = $_.Exception.Message
} finally {
    if ($null -ne $powerPoint) {
        try { $powerPoint.Quit() } catch { }
        try { [Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint) | Out-Null } catch { }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$result.ok = [bool]($result.powershell -and $result.worker_script.exists -and $result.exporter_script.exists -and $result.powerpoint.available)
$result | ConvertTo-Json -Depth 5
if (-not $result.ok) { exit 1 }
