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
    throw "Refusing to replace an existing release. Choose a new OutputPath: $OutputPath"
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
    "README_EN.md",
    "LICENSE",
    "NOTICE",
    "COMMERCIAL_LICENSE.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "stop.ps1",
    "VOLCENGINE_ASR.md"
)

function Get-DeployFiles {
    param([string]$RelativeDirectory)

    $absoluteDirectory = Join-Path $projectRoot $RelativeDirectory
    foreach ($file in Get-ChildItem -LiteralPath $absoluteDirectory -Force -File) {
        if ($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Do not package linked files: $($file.FullName)"
        }
        $relativePath = "$RelativeDirectory/$($file.Name)"
        $isEnvironmentFile = (
            $file.Name -like ".env*" -and
            $file.Name -notlike "*.example"
        )
        if (
            $isEnvironmentFile -or
            $file.Extension -eq ".pyc" -or
            $file.Extension -eq ".log" -or
            $file.Extension -eq ".pid" -or
            $file.Extension -in @('.zip', '.db', '.sqlite', '.sqlite3', '.joblib', '.pkl', '.pem', '.key', '.part', '.tmp') -or
            $relativePath -eq 'frontend/public/release.json'
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
            $name -like ".venv*" -or
            $name -in @('.git', '.dev', '.cache', 'backups')
        ) {
            continue
        }
        if ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Do not package linked directories: $($directory.FullName)"
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
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$releaseId = [System.IO.Path]::GetFileNameWithoutExtension($OutputPath)
$createdAt = [DateTime]::UtcNow.ToString('o')
$fileManifest = [System.Collections.Generic.List[object]]::new()
$retiredFiles = @('backend/app/core/websocket.py', 'backend/app/services/protocol_agent.py')
function Add-ReleaseEntry {
    param($Archive, [string]$Name, [byte[]]$Bytes)
    $entry = $Archive.CreateEntry($Name, [System.IO.Compression.CompressionLevel]::Optimal)
    $stream = $entry.Open()
    try { $stream.Write($Bytes, 0, $Bytes.Length) } finally { $stream.Dispose() }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $hash = ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
    $fileManifest.Add([ordered]@{ path = $Name; sha256 = $hash; size = $Bytes.Length })
}
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
            $bytes = [System.IO.File]::ReadAllBytes($sourcePath)
            if ($entryName.EndsWith('.sh')) {
                $shellText = [System.Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF).Replace("`r`n", "`n")
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($shellText)
            }
            Add-ReleaseEntry $zip $entryName $bytes
        }
        $marker = [ordered]@{ release_id = $releaseId; created_at_utc = $createdAt; schema_phase = 36 }
        Add-ReleaseEntry $zip 'frontend/public/release.json' ([System.Text.Encoding]::UTF8.GetBytes(($marker | ConvertTo-Json)))
        $manifest = [ordered]@{
            format_version = 1
            release_id = $releaseId
            created_at_utc = $createdAt
            schema_phase = 36
            retired_files = $retiredFiles
            files = @($fileManifest.ToArray())
        } | ConvertTo-Json -Depth 8
        $manifestEntry = $zip.CreateEntry('RELEASE_MANIFEST.json')
        $manifestStream = $manifestEntry.Open()
        try {
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($manifest)
            $manifestStream.Write($bytes, 0, $bytes.Length)
        } finally { $manifestStream.Dispose() }
    }
    finally {
        $zip.Dispose()
    }

    $validationZip = [System.IO.Compression.ZipFile]::OpenRead($temporaryArchive)
    try {
        $entries = @($validationZip.Entries | ForEach-Object FullName)
        foreach ($record in $fileManifest) {
            $entry = $validationZip.GetEntry($record.path)
            if ($null -eq $entry) { throw "Missing archive entry: $($record.path)" }
            $stream = $entry.Open()
            $sha = [System.Security.Cryptography.SHA256]::Create()
            try { $actual = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
            finally { $stream.Dispose(); $sha.Dispose() }
            if ($actual -ne $record.sha256) { throw "Archive checksum mismatch: $($record.path)" }
        }
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
    $archiveHash = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
    [System.IO.File]::WriteAllText(
        "$OutputPath.sha256",
        "$archiveHash  $([System.IO.Path]::GetFileName($OutputPath))`n",
        [System.Text.UTF8Encoding]::new($false)
    )
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
