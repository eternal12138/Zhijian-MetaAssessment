[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$runtimeDir = Join-Path $PSScriptRoot ".dev"
$pidFiles = @(
    (Join-Path $runtimeDir "frontend.pid"),
    (Join-Path $runtimeDir "backend.pid"),
    (Join-Path $runtimeDir "asr-worker.pid"),
    (Join-Path $runtimeDir "extraction-worker.pid"),
    (Join-Path $runtimeDir "export-worker.pid"),
    (Join-Path $runtimeDir "model-training-worker.pid"),
    (Join-Path $runtimeDir "cloudflare-tunnel.pid")
)

Write-Host "Stopping project development services..." -ForegroundColor Yellow

foreach ($pidFile in $pidFiles) {
    if (-not (Test-Path -LiteralPath $pidFile)) {
        continue
    }

    $processId = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($processId -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
        $taskkill = Get-Command taskkill.exe -ErrorAction SilentlyContinue
        if ($taskkill) {
            $previousErrorActionPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = "Continue"
                & $taskkill.Source /PID $processId /T /F 2>$null | Out-Null
            }
            finally {
                $ErrorActionPreference = $previousErrorActionPreference
            }
        }
        else {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
        Write-Host "  Stopped PID $processId" -ForegroundColor DarkGray
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$frontendDriveFile = Join-Path $runtimeDir "frontend-drive.txt"
if (Test-Path -LiteralPath $frontendDriveFile) {
    $frontendDrive = (
        Get-Content -LiteralPath $frontendDriveFile -ErrorAction SilentlyContinue |
            Select-Object -First 1
    ).Trim()
    if ($frontendDrive -match "^[A-Z]:$" -and
        (Test-Path -LiteralPath "$frontendDrive\")) {
        & (Join-Path $env:SystemRoot "System32\subst.exe") `
            $frontendDrive /D 2>$null | Out-Null
    }
    Remove-Item -LiteralPath $frontendDriveFile -Force `
        -ErrorAction SilentlyContinue
}

Write-Host "Done." -ForegroundColor Green
