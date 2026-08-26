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
    "DEPLOY_ALIYUN.md",
    "dev.cmd",
    "dev.ps1",
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
            ($RelativeDirectory -eq "backend" -and $name -eq "models") -or
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
$packageFiles = @(
    $packageFiles |
        Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
        Sort-Object -Unique
)
Add-Type -AssemblyName System.IO.Compression.FileSystem
try {
    $zip = [System.IO.Compression.ZipFile]::Open(
        $temporaryArchive,
        [System.IO.Compression.ZipArchiveMode]::Create
    )
    try {
        foreach ($relativePath in $packageFiles) {
            $sourcePath = Join-Path $projectRoot $relativePath
            if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
                throw "Deployment package source file is missing: $relativePath"
            }
            $entryName = $relativePath.Replace("\", "/")
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip,
                $sourcePath,
                $entryName,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    }
    finally {
        $zip.Dispose()
    }

    $validationZip = [System.IO.Compression.ZipFile]::OpenRead($temporaryArchive)
    try {
        $entries = @($validationZip.Entries | ForEach-Object FullName)
    }
    finally {
        $validationZip.Dispose()
    }
    if ($entries.Count -eq 0) {
        throw "Deployment package validation failed: archive is empty or unreadable."
    }

    $forbidden = $entries | Where-Object {
        $_ -match '(^|/)(\.env|\.venv[^/]*|node_modules(?:\.[^/]*)?|dist|test-results|playwright-report|uploads|exports|__pycache__|\.pytest_cache)(/|$)' -or
        $_ -match '\.(pyc|log|pid)$'
    }
    if ($forbidden) {
        throw "Deployment package contains local-only files: $($forbidden -join ', ')"
    }

    Copy-Item -LiteralPath $temporaryArchive -Destination $OutputPath
}
finally {
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
