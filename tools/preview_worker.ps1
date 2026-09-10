param()

# Keep one hidden PowerPoint COM application alive and process JSONL jobs from
# stdin.  Starting PowerPoint is the dominant cost of live preview; reusing the
# application removes that cost from every field change after the first job.
$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$powerPoint = $null
$presentations = $null

function Release-Com([object]$value) {
    if ($null -ne $value) {
        try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($value) | Out-Null } catch { }
    }
}

try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    try { $powerPoint.Visible = $false } catch { }
    $presentations = $powerPoint.GetType().InvokeMember(
        'Presentations', [Reflection.BindingFlags]::GetProperty, $null, $powerPoint, $null)
    if ($null -eq $presentations) { throw 'PowerPoint Presentations collection is unavailable' }

    while (($line = [Console]::In.ReadLine()) -ne $null) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $presentation = $null
        try {
            $job = $line | ConvertFrom-Json
            $presentation = $presentations.GetType().InvokeMember(
                'Open', [Reflection.BindingFlags]::InvokeMethod, $null, $presentations,
                @([string]$job.TemplatePath, -1, -1, 0))
            $slideIndex = [int]$job.SlideIndex
            if ($slideIndex -lt 1 -or $slideIndex -gt $presentation.Slides.Count) {
                throw "Slide index out of range: $slideIndex"
            }
            $outputPath = [string]$job.OutputPath
            $outputDirectory = [System.IO.Path]::GetDirectoryName($outputPath)
            [System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
            $presentation.Slides.Item($slideIndex).Export(
                $outputPath, 'PNG', [int]$job.Width, [int]$job.Height)
            if (-not [System.IO.File]::Exists($outputPath)) {
                throw "PowerPoint did not create preview: $outputPath"
            }
            $presentation.Close()
            Release-Com $presentation
            $presentation = $null
            [Console]::WriteLine((@{ ok = $true } | ConvertTo-Json -Compress))
        } catch {
            if ($null -ne $presentation) {
                try { $presentation.Close() } catch { }
                Release-Com $presentation
            }
            [Console]::WriteLine((@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress))
        }
        [Console]::Out.Flush()
    }
} finally {
    Release-Com $presentations
    if ($null -ne $powerPoint) {
        try { if ($powerPoint.Presentations.Count -eq 0) { $powerPoint.Quit() } } catch { }
        Release-Com $powerPoint
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
