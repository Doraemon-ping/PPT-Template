param(
    [Parameter(Mandatory = $true)][string]$TemplatePath,
    [Parameter(Mandatory = $true)][int]$SlideIndex,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [int]$Width = 1600,
    [int]$Height = 900
)

$powerPoint = $null
$presentation = $null
$ErrorActionPreference = 'Stop'
try {
    $outputDirectory = [System.IO.Path]::GetDirectoryName($OutputPath)
    [System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
    $powerPoint = New-Object -ComObject PowerPoint.Application
    # A freshly started COM server may expose Application before Presentations is ready.
    $previewPresentations = $null
    for ($previewAttempt = 0; $previewAttempt -lt 25; $previewAttempt++) {
        $previewPresentations = $powerPoint.GetType().InvokeMember('Presentations', [Reflection.BindingFlags]::GetProperty, $null, $powerPoint, $null)
        if ($null -ne $previewPresentations) { break }
        Start-Sleep -Milliseconds 200
    }
    if ($null -eq $previewPresentations) { throw 'PowerPoint Presentations collection is unavailable' }
    $presentation = $previewPresentations.GetType().InvokeMember('Open', [Reflection.BindingFlags]::InvokeMethod, $null, $previewPresentations, @($TemplatePath, -1, -1, 0))
    if ($SlideIndex -lt 1 -or $SlideIndex -gt $presentation.Slides.Count) {
        throw "Slide index out of range: $SlideIndex"
    }
    $presentation.Slides.Item($SlideIndex).Export($OutputPath, 'PNG', $Width, $Height)
    if (-not [System.IO.File]::Exists($OutputPath)) {
        throw "PowerPoint did not create preview: $OutputPath"
    }
}
finally {
    if ($presentation -ne $null) {
        try { $presentation.Close() } catch { }
        try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) | Out-Null } catch { }
    }
    if ($powerPoint -ne $null) {
        # Do not close presentations that the user already has open.
        try { if ($powerPoint.Presentations.Count -eq 0) { $powerPoint.Quit() } } catch { }
        try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint) | Out-Null } catch { }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
