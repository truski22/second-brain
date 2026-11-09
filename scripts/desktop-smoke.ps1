$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$exe = (Resolve-Path frontend\src-tauri\target\debug\second-brain-desktop.exe).Path
$data = Join-Path $env:TEMP ("second-brain-desktop-smoke-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory $data | Out-Null
$env:SECOND_BRAIN_DATA_DIR = $data
$process = Start-Process -FilePath $exe -PassThru
try {
    $ready = $false
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 500
        $process.Refresh()
        if ($process.HasExited) { throw "Desktop exited with code $($process.ExitCode)" }
        if ($process.MainWindowTitle -eq "Segundo Cerebro") { $ready = $true; break }
    }
    if (-not $ready) { throw "Named native window did not appear. Inspect $data" }
    $children = @(Get-CimInstance Win32_Process | Where-Object {
        $_.ParentProcessId -eq $process.Id -and $_.Name -eq "second-brain-backend.exe"
    })
    Write-Output "Native window ready; backend children: $($children.Count)"
    if ($children.Count -ne 1) { throw "Expected exactly one owned backend" }
    $null = $process.CloseMainWindow()
    if (-not $process.WaitForExit(15000)) { throw "Desktop did not exit after window close" }
    Start-Sleep -Seconds 2
    foreach ($child in $children) {
        if (Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue) {
            throw "Owned backend remained alive after window close: $($child.ProcessId)"
        }
    }
    Write-Output "Desktop and owned backend closed cleanly. Synthetic data: $data"
} finally {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id }
}
