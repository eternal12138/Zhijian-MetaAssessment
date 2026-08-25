[CmdletBinding()]
param(
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmm"
    $OutputPath = Join-Path $projectRoot "metacognition-deploy-$stamp.zip"
}

$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
if ([System.IO.Path]::GetExtension($OutputPath) -ne ".zip") {
    throw "The deployment package path must end with .zip."
}

$outputDirectory = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}
if (Test-Path -LiteralPath $OutputPath) {
    Remove-Item -LiteralPath $OutputPath -Force
}

$temporaryArchive = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    ("metacognition-" + [Guid]::NewGuid().ToString("N") + ".zip")
$temporaryFileList = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    ("metacognition-" + [Guid]::NewGuid().ToString("N") + ".txt")

$includeFiles = @(
    ".env.production.example",
    ".gitignore",
    "compose.yaml",
    "CLOUDFLARE_TUNNEL.md",
    "DEPLOY_ALIYUN.md",
    "dev.cmd",
    "dev.ps1",
    "EXPERIMENT_DATA.md",
    "EXPERT_DATASET.md",
    "README.md",
    "stop.ps1",
    "VOLCENGINE_ASR.md"
)

function Get-DeployFiles {
    param([string]$RelativeDirectory)

    $absoluteDirectory = Join-Path $projectRoot $RelativeDirectory
    foreach ($file in Get-ChildItem -LiteralPath $absoluteDirectory -Force -File) {
        $relativePath = "$RelativeDirectory/$($file.Name)"
        $isEnvironmentFile = (
            $file.Name -like ".env*" -and
            $file.Name -notlike "*.example"
        )
        if (
            $isEnvironmentFile -or
            $file.Extension -eq ".pyc" -or
            $file.Extension -eq ".log" -or
            $file.Extension -eq ".pid"
        ) {
            continue
        }
        $relativePath
    }

    foreach ($directory in Get-ChildItem -LiteralPath $absoluteDirectory -Force -Directory) {
        $name = $directory.Name
        if (
            $name -eq "__pycache__" -or
            $name -eq ".pytest_cache" -or
            $name -eq "uploads" -or
            $name -eq "exports" -or
            $name -eq "dist" -or
            $name -eq "test-results" -or
            $name -eq "playwright-report" -or
            $name -eq "node_modules" -or
            $name -like "node_modules.*" -or
            $name -like ".venv*"
        ) {
            continue
        }
        Get-DeployFiles "$RelativeDirectory/$name"
    }
}

$packageFiles = @($includeFiles)
$packageFiles += @(Get-DeployFiles "backend")
$packageFiles += @(Get-DeployFiles "frontend")
$packageFiles += @(Get-DeployFiles "deploy")
$packageFiles = @($packageFiles | Sort-Object -Unique)
[System.IO.File]::WriteAllLines(
    $temporaryFileList,
    $packageFiles,
    [System.Text.UTF8Encoding]::new($false)
)

$tarArguments = @(
    "-a",
    "-c",
    "-f",
    $temporaryArchive,
    "-T",
    $temporaryFileList
)

Push-Location $projectRoot
try {
    & tar.exe @tarArguments
    if ($LASTEXITCODE -ne 0) {
        throw "tar.exe failed with exit code $LASTEXITCODE."
    }

    $entries = @(& tar.exe -tf $temporaryArchive)
    if ($LASTEXITCODE -ne 0 -or $entries.Count -eq 0) {
        throw "Deployment package validation failed: archive is empty or unreadable."
    }

    $forbidden = $entries | Where-Object {
        $_ -match '(^|/)(\.env|\.venv[^/]*|node_modules(?:\.[^/]*)?|dist|test-results|playwright-report|uploads|exports|__pycache__|\.pytest_cache)(/|$)' -or
        $_ -match '\.(pyc|log|pid)$'
    }
    if ($forbidden) {
        throw "Deployment package contains local-only files: $($forbidden -join ', ')"
    }

    Move-Item -LiteralPath $temporaryArchive -Destination $OutputPath
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $temporaryArchive) {
        Remove-Item -LiteralPath $temporaryArchive -Force
    }
    if (Test-Path -LiteralPath $temporaryFileList) {
        Remove-Item -LiteralPath $temporaryFileList -Force
    }
}

$archive = Get-Item -LiteralPath $OutputPath
Write-Host "Deployment package created: $($archive.FullName)"
Write-Host "Size: $([Math]::Round($archive.Length / 1MB, 2)) MB"
