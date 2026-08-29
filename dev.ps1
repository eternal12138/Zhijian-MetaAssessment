[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [string]$BackendHost = "127.0.0.1",
    [string]$FrontendHost = "127.0.0.1",
    [string]$TunnelHostname = "meta.21050411.xyz",
    [string]$TunnelTokenFile = "",
    [switch]$EnableTunnel,
    [switch]$Restart,
    [switch]$SkipInstall,
    [switch]$SkipLlmCheck,
    [switch]$OpenBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Some Windows launchers inject both "Path" and "PATH". Windows itself accepts
# that, but Windows PowerShell 5.1 Start-Process treats them as duplicate keys.
$processEnvironment = [Environment]::GetEnvironmentVariables()
$pathParts = New-Object System.Collections.Generic.List[string]
$seenPathParts = New-Object 'System.Collections.Generic.HashSet[string]' (
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($pathKey in @("Path", "PATH")) {
    foreach ($environmentKey in $processEnvironment.Keys) {
        if ([string]$environmentKey -cne $pathKey) {
            continue
        }
        foreach ($pathPart in ([string]$processEnvironment[$environmentKey] -split ";")) {
            $trimmedPathPart = $pathPart.Trim()
            if ($trimmedPathPart -and $seenPathParts.Add($trimmedPathPart)) {
                $pathParts.Add($trimmedPathPart)
            }
        }
    }
}
if ($pathParts.Count -gt 0) {
    [Environment]::SetEnvironmentVariable(
        "PATH",
        $null,
        [EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        "Path",
        $null,
        [EnvironmentVariableTarget]::Process
    )
    [Environment]::SetEnvironmentVariable(
        "Path",
        ($pathParts -join ";"),
        [EnvironmentVariableTarget]::Process
    )
}

$env:PYTHONUTF8 = "1"

$projectRoot = $PSScriptRoot
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$runtimeDir = Join-Path $projectRoot ".dev"
$logDir = Join-Path $runtimeDir "logs"
$backendPidFile = Join-Path $runtimeDir "backend.pid"
$frontendPidFile = Join-Path $runtimeDir "frontend.pid"
$asrWorkerPidFile = Join-Path $runtimeDir "asr-worker.pid"
$reportWorkerPidFile = Join-Path $runtimeDir "report-worker.pid"
$extractionWorkerPidFile = Join-Path $runtimeDir "extraction-worker.pid"
$exportWorkerPidFile = Join-Path $runtimeDir "export-worker.pid"
$modelTrainingWorkerPidFile = Join-Path $runtimeDir "model-training-worker.pid"
$tunnelPidFile = Join-Path $runtimeDir "cloudflare-tunnel.pid"
$frontendDriveFile = Join-Path $runtimeDir "frontend-drive.txt"
$backendLog = Join-Path $logDir "backend.log"
$backendErrorLog = Join-Path $logDir "backend.error.log"
$frontendLog = Join-Path $logDir "frontend.log"
$frontendErrorLog = Join-Path $logDir "frontend.error.log"
$asrWorkerLog = Join-Path $logDir "asr-worker.log"
$asrWorkerErrorLog = Join-Path $logDir "asr-worker.error.log"
$extractionWorkerLog = Join-Path $logDir "extraction-worker.log"
$extractionWorkerErrorLog = Join-Path $logDir "extraction-worker.error.log"
$exportWorkerLog = Join-Path $logDir "export-worker.log"
$exportWorkerErrorLog = Join-Path $logDir "export-worker.error.log"
$modelTrainingWorkerLog = Join-Path $logDir "model-training-worker.log"
$modelTrainingWorkerErrorLog = Join-Path $logDir "model-training-worker.error.log"
$tunnelLog = Join-Path $logDir "cloudflare-tunnel.log"
$tunnelErrorLog = Join-Path $logDir "cloudflare-tunnel.error.log"

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Get-DotEnvValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$DefaultValue = ""
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $DefaultValue
    }

    $line = Get-Content -LiteralPath $Path -Encoding UTF8 |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
        Select-Object -Last 1

    if (-not $line) {
        return $DefaultValue
    }

    $value = ($line -split "=", 2)[1].Trim()
    return $value.Trim('"').Trim("'")
}

function Test-TcpPort {
    param(
        [string]$ComputerName,
        [int]$Port,
        [int]$TimeoutMilliseconds = 1200
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connection = $client.BeginConnect($ComputerName, $Port, $null, $null)
        if (-not $connection.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) {
            return $false
        }
        $client.EndConnect($connection)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Wait-Http {
    param(
        [string]$Uri,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function Get-PortProcessId {
    param([int]$Port)

    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($connection) {
        return [int]$connection.OwningProcess
    }
    return $null
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    $taskkill = Get-Command taskkill.exe -ErrorAction SilentlyContinue
    if ($taskkill) {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $taskkill.Source /PID $ProcessId /T /F 2>$null | Out-Null
            $taskkillExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($taskkillExitCode -ne 0) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    else {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Stop-RecordedProcess {
    param([string]$PidFile)

    if (-not (Test-Path -LiteralPath $PidFile)) {
        return
    }

    $processId = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($processId -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
        Stop-ProcessTree -ProcessId $processId
        Start-Sleep -Milliseconds 500
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

function Stop-ProjectPortProcess {
    param(
        [int]$Port,
        [string]$ExpectedProjectRoot
    )

    $processId = Get-PortProcessId -Port $Port
    if (-not $processId) {
        return
    }

    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" `
        -ErrorAction SilentlyContinue
    $commandLine = if ($processInfo) { [string]$processInfo.CommandLine } else { "" }
    if ($commandLine.IndexOf(
        $ExpectedProjectRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -lt 0) {
        throw "Port $Port is owned by PID $processId, which was not started from this project."
    }

    Stop-ProcessTree -ProcessId $processId
    Start-Sleep -Milliseconds 500
}

function Test-PythonRuntime {
    param(
        [string]$Command,
        [string[]]$Prefix = @()
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 may convert stderr from a broken Python
        # launcher into a terminating NativeCommandError under "Stop".
        $ErrorActionPreference = "Continue"
        & $Command @Prefix -c `
            "import sys, encodings; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" `
            2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Find-Python {
    $candidates = @()
    $portablePython = Join-Path $projectRoot ".dev\python313\python.exe"
    if (Test-Path -LiteralPath $portablePython) {
        $candidates += [pscustomobject]@{
            Command = $portablePython
            Prefix = @()
        }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += [pscustomobject]@{ Command = "py"; Prefix = @("-3.13") }
        $candidates += [pscustomobject]@{ Command = "py"; Prefix = @("-3") }
    }
    foreach ($name in @("python", "python3")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            $candidates += [pscustomobject]@{ Command = $command.Source; Prefix = @() }
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonRuntime `
            -Command $candidate.Command `
            -Prefix $candidate.Prefix) {
            return $candidate
        }
    }
    return $null
}

Write-Host "=== ZHIJIAN AI: development startup ===" -ForegroundColor Green
Write-Host "Project root: $projectRoot" -ForegroundColor DarkGray

if (-not (Test-Path -LiteralPath $backendDir) -or
    -not (Test-Path -LiteralPath $frontendDir)) {
    throw "dev.ps1 must be located in the project root containing backend and frontend."
}

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

if ($Restart) {
    Write-Step "Stop previously recorded project processes"
    Stop-RecordedProcess -PidFile $backendPidFile
    Stop-RecordedProcess -PidFile $frontendPidFile
    Stop-RecordedProcess -PidFile $asrWorkerPidFile
    Stop-RecordedProcess -PidFile $reportWorkerPidFile
    Stop-RecordedProcess -PidFile $extractionWorkerPidFile
    Stop-RecordedProcess -PidFile $exportWorkerPidFile
    Stop-RecordedProcess -PidFile $modelTrainingWorkerPidFile
    Stop-RecordedProcess -PidFile $tunnelPidFile
    Stop-ProjectPortProcess -Port $BackendPort -ExpectedProjectRoot $projectRoot
    Stop-ProjectPortProcess -Port $FrontendPort -ExpectedProjectRoot $projectRoot
}

$backendPortOwner = Get-PortProcessId -Port $BackendPort
if ($backendPortOwner) {
    try {
        $health = Invoke-RestMethod `
            -Uri "http://127.0.0.1:$BackendPort/api/health" `
            -TimeoutSec 2
        if ($health.status -eq "ok") {
            Write-Host "Backend is already running on port $BackendPort (PID $backendPortOwner)." -ForegroundColor Yellow
            Set-Content -LiteralPath $backendPidFile -Value $backendPortOwner -Encoding ASCII
        }
        else {
            throw "Port $BackendPort is already in use by PID $backendPortOwner."
        }
    }
    catch {
        throw "Backend port $BackendPort is in use by PID $backendPortOwner. Stop it or choose another port."
    }
}

$frontendPortOwner = Get-PortProcessId -Port $FrontendPort
if ($frontendPortOwner) {
    try {
        $frontendResponse = Invoke-WebRequest `
            -Uri "http://127.0.0.1:$FrontendPort" `
            -UseBasicParsing `
            -TimeoutSec 2
        if ($frontendResponse.StatusCode -eq 200) {
            Write-Host "Frontend is already running on port $FrontendPort (PID $frontendPortOwner)." -ForegroundColor Yellow
            Set-Content -LiteralPath $frontendPidFile -Value $frontendPortOwner -Encoding ASCII
        }
        else {
            throw "Port $FrontendPort is already in use by PID $frontendPortOwner."
        }
    }
    catch {
        throw "Frontend port $FrontendPort is in use by PID $frontendPortOwner. Run .\stop.ps1 or choose another port."
    }
}

Write-Step "Check backend environment configuration"
$backendEnv = Join-Path $backendDir ".env"
$backendEnvExample = Join-Path $backendDir ".env.example"
if (-not (Test-Path -LiteralPath $backendEnv)) {
    Copy-Item -LiteralPath $backendEnvExample -Destination $backendEnv
    Write-Host "Created backend/.env from .env.example. Review database and model settings." -ForegroundColor Yellow
}

Write-Step "Check Python 3.11+ and the virtual environment"
$venvDir = Join-Path $backendDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvValid = $false
if (Test-Path -LiteralPath $venvPython) {
    $venvValid = Test-PythonRuntime -Command $venvPython
}

if (-not $venvValid) {
    if (Test-Path -LiteralPath $venvDir) {
        $backupName = ".venv-broken-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")
        Rename-Item -LiteralPath $venvDir -NewName $backupName
        Write-Host "The invalid virtual environment was preserved as backend/$backupName." -ForegroundColor Yellow
    }

    $python = Find-Python
    if (-not $python) {
        throw @"
Python 3.11+ was not found, so the backend virtual environment cannot be rebuilt.
Install 64-bit Python from https://www.python.org/downloads/windows/ and enable
'Add python.exe to PATH', then double-click dev.cmd again.
"@
    }

    & $python.Command @($python.Prefix) -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the Python virtual environment."
    }
}

& $venvPython --version
if (-not $SkipInstall) {
    Write-Step "Synchronize backend dependencies"
    & $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt") `
        --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install backend dependencies."
    }
}

Write-Step "Check MySQL"
$dbHost = Get-DotEnvValue -Path $backendEnv -Name "DB_HOST" -DefaultValue "localhost"
$dbPort = [int](Get-DotEnvValue -Path $backendEnv -Name "DB_PORT" -DefaultValue "3306")

if (-not (Test-TcpPort -ComputerName $dbHost -Port $dbPort)) {
    if ($dbHost -in @("localhost", "127.0.0.1")) {
        $mysqlService = Get-Service -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "mysql|maria" } |
            Select-Object -First 1
        if ($mysqlService -and $mysqlService.Status -ne "Running") {
            try {
                Start-Service -Name $mysqlService.Name
                $mysqlService.WaitForStatus("Running", (New-TimeSpan -Seconds 15))
            }
            catch {
                Write-Host "Could not start MySQL service $($mysqlService.Name): $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
    }
}

if (-not (Test-TcpPort -ComputerName $dbHost -Port $dbPort)) {
    throw "Cannot connect to MySQL at ${dbHost}:$dbPort. Start MySQL and check backend/.env."
}

$databaseCheck = @"
import pymysql
from app.config import get_settings
s = get_settings()
connection = pymysql.connect(
    host=s.DB_HOST,
    port=s.DB_PORT,
    user=s.DB_USER,
    password=s.DB_PASSWORD,
    database=s.DB_NAME,
    connect_timeout=5,
)
connection.close()
"@
Push-Location $backendDir
try {
    & $venvPython -c $databaseCheck
    if ($LASTEXITCODE -ne 0) {
        throw "Database authentication or database-name validation failed."
    }
}
finally {
    Pop-Location
}
Write-Host "MySQL database connection is ready." -ForegroundColor Green

Write-Step "Apply idempotent project database migrations"
Push-Location $backendDir
try {
    # Share the production migration registry so new schema phases cannot be skipped.
    & $venvPython (Join-Path $backendDir "scripts\migrate_all.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Database migrations failed with exit code $LASTEXITCODE. Services were not started."
    }
    & $venvPython (Join-Path $backendDir "scripts\bootstrap_development.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to prepare local demonstration accounts."
    }
    & $venvPython (Join-Path $backendDir "scripts\seed_protocol.py") `
        --skip-if-active
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to publish the standardized assessment protocol."
    }
}
finally {
    Pop-Location
}

if (-not $SkipLlmCheck) {
    Write-Step "Check the local LLM service"
    $llmBaseUrl = Get-DotEnvValue -Path $backendEnv -Name "LLM_BASE_URL"
    try {
        $llmUri = [Uri]$llmBaseUrl
        if ($llmUri.Host -in @("localhost", "127.0.0.1")) {
            $llmPort = if ($llmUri.IsDefaultPort) {
                if ($llmUri.Scheme -eq "https") { 443 } else { 80 }
            }
            else {
                $llmUri.Port
            }

            if (-not (Test-TcpPort -ComputerName $llmUri.Host -Port $llmPort)) {
                $ollama = Get-Command ollama -ErrorAction SilentlyContinue
                if ($ollama) {
                    Start-Process -FilePath $ollama.Source -ArgumentList "serve" `
                        -WindowStyle Hidden | Out-Null
                    $deadline = (Get-Date).AddSeconds(15)
                    while ((Get-Date) -lt $deadline -and
                        -not (Test-TcpPort -ComputerName $llmUri.Host -Port $llmPort)) {
                        Start-Sleep -Milliseconds 500
                    }
                }
            }

            if (Test-TcpPort -ComputerName $llmUri.Host -Port $llmPort) {
                Write-Host "Local model service is ready: $llmBaseUrl" -ForegroundColor Green
            }
            else {
                Write-Warning "Local model service is unavailable at $llmBaseUrl. Standardized assessment will work, but post-assessment AI analysis will use rule fallback."
            }
        }
        else {
            Write-Host "Using remote model service: $($llmUri.Host)" -ForegroundColor DarkGray
        }
    }
    catch {
        Write-Warning "LLM_BASE_URL is invalid. Check backend/.env."
    }
}

Write-Step "Check Node.js, pnpm, and frontend dependencies"
$frontendRuntimeDir = $frontendDir
if ($frontendDir -match "[^\x00-\x7F]") {
    $frontendDrive = $null
    if (Test-Path -LiteralPath $frontendDriveFile) {
        $recordedDrive = (
            Get-Content -LiteralPath $frontendDriveFile |
                Select-Object -First 1
        ).Trim()
        if ($recordedDrive -match "^[A-Z]:$" -and
            (Test-Path -LiteralPath "$recordedDrive\frontend")) {
            $frontendDrive = $recordedDrive
        }
    }

    if (-not $frontendDrive) {
        $usedDriveNames = @(
            Get-PSDrive -PSProvider FileSystem |
                ForEach-Object { $_.Name.ToUpperInvariant() }
        )
        foreach ($letter in @("Z", "Y", "X", "W", "V", "U")) {
            if ($letter -notin $usedDriveNames) {
                $candidateDrive = "${letter}:"
                & (Join-Path $env:SystemRoot "System32\subst.exe") `
                    $candidateDrive $projectRoot
                if ($LASTEXITCODE -eq 0 -and
                    (Test-Path -LiteralPath "$candidateDrive\frontend")) {
                    $frontendDrive = $candidateDrive
                    Set-Content -LiteralPath $frontendDriveFile `
                        -Value $frontendDrive -Encoding ASCII
                    break
                }
            }
        }
    }

    if (-not $frontendDrive) {
        throw "Could not create an ASCII-only virtual drive for the frontend."
    }
    $frontendRuntimeDir = "$frontendDrive\frontend"
    Write-Host "Frontend path compatibility drive: $frontendRuntimeDir" `
        -ForegroundColor DarkGray
}

$pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
if (-not $pnpm) {
    $pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
}
if (-not $pnpm) {
    throw "pnpm was not found. Install Node.js, then run: corepack enable"
}

& $pnpm.Source --version
if (-not $SkipInstall) {
    Push-Location $frontendRuntimeDir
    try {
        & $pnpm.Source install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install frontend dependencies."
        }
    }
    finally {
        Pop-Location
    }
}

if (-not $backendPortOwner) {
    Write-Step "Start the FastAPI backend"
    Remove-Item -LiteralPath $backendLog, $backendErrorLog -Force -ErrorAction SilentlyContinue
    Start-Process -FilePath $venvPython `
        -ArgumentList @(
            "-m", "uvicorn", "app.main:app",
            "--host", $BackendHost,
            "--port", "$BackendPort",
            "--reload"
        ) `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError $backendErrorLog | Out-Null

    if (-not (Wait-Http -Uri "http://127.0.0.1:$BackendPort/api/health" -TimeoutSeconds 30)) {
        if (Test-Path -LiteralPath $backendErrorLog) {
            Get-Content -LiteralPath $backendErrorLog -Tail 30
        }
        throw "Backend startup failed. See $backendErrorLog"
    }
    $backendProcessId = Get-PortProcessId -Port $BackendPort
    Set-Content -LiteralPath $backendPidFile -Value $backendProcessId -Encoding ASCII
}

$asrProvider = Get-DotEnvValue -Path $backendEnv -Name "ASR_PROVIDER" -DefaultValue "disabled"
if ($asrProvider.ToLowerInvariant() -ne "disabled") {
    Write-Step "Start the authoritative ASR worker"
    Stop-RecordedProcess -PidFile $asrWorkerPidFile
    Remove-Item -LiteralPath $asrWorkerLog, $asrWorkerErrorLog -Force -ErrorAction SilentlyContinue
    $asrWorkerProcess = Start-Process -FilePath $venvPython `
        -ArgumentList @("scripts\asr_worker.py") `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $asrWorkerLog `
        -RedirectStandardError $asrWorkerErrorLog `
        -PassThru
    Set-Content -LiteralPath $asrWorkerPidFile -Value $asrWorkerProcess.Id -Encoding ASCII
    Start-Sleep -Milliseconds 500
    if ($asrWorkerProcess.HasExited) {
        if (Test-Path -LiteralPath $asrWorkerErrorLog) {
            Get-Content -LiteralPath $asrWorkerErrorLog -Tail 30
        }
        throw "ASR worker startup failed. See $asrWorkerErrorLog"
    }
    if ($asrProvider.ToLowerInvariant() -eq "volcengine") {
        $volcApiKey = Get-DotEnvValue -Path $backendEnv -Name "VOLCENGINE_ASR_API_KEY"
        $volcAppId = Get-DotEnvValue -Path $backendEnv -Name "VOLCENGINE_ASR_APP_ID"
        $volcAccessKey = Get-DotEnvValue -Path $backendEnv -Name "VOLCENGINE_ASR_ACCESS_KEY"
        $asrPublicBaseUrl = Get-DotEnvValue -Path $backendEnv -Name "ASR_PUBLIC_BASE_URL"
        $asrSigningSecret = Get-DotEnvValue -Path $backendEnv -Name "ASR_AUDIO_SIGNING_SECRET"

        if (-not $volcApiKey -and (-not $volcAppId -or -not $volcAccessKey)) {
            Write-Warning "Volcengine credentials are incomplete. Configure VOLCENGINE_ASR_API_KEY, or both VOLCENGINE_ASR_APP_ID and VOLCENGINE_ASR_ACCESS_KEY."
        }
        if (-not $asrPublicBaseUrl -or -not $asrSigningSecret) {
            Write-Warning "Volcengine requires ASR_PUBLIC_BASE_URL and ASR_AUDIO_SIGNING_SECRET. Jobs will wait for configuration."
        }
        if (-not $EnableTunnel -and $asrPublicBaseUrl -match "localhost|127\.0\.0\.1") {
            Write-Warning "Volcengine cannot download audio from a local-only URL. Enable the tunnel or use the production HTTPS domain."
        }
    }
    else {
        $asrBaseUrl = Get-DotEnvValue -Path $backendEnv -Name "ASR_BASE_URL"
        if (-not $asrBaseUrl) {
            Write-Warning "ASR_BASE_URL is empty. Jobs will enter waiting_configuration until it is configured and retried."
        }
    }
}
else {
    Write-Warning "ASR_PROVIDER=disabled. Audio will be retained, but authoritative transcription and report generation will wait for ASR configuration."
}

$extractionEnabled = Get-DotEnvValue -Path $backendEnv -Name "METACOGNITIVE_EXTRACTION_ENABLED" -DefaultValue "true"
if ($extractionEnabled.ToLowerInvariant() -ne "false") {
    Write-Step "Start the metacognitive candidate extraction worker"
    Stop-RecordedProcess -PidFile $extractionWorkerPidFile
    Remove-Item -LiteralPath $extractionWorkerLog, $extractionWorkerErrorLog -Force -ErrorAction SilentlyContinue
    $extractionWorkerProcess = Start-Process -FilePath $venvPython `
        -ArgumentList @("scripts\extraction_worker.py") `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $extractionWorkerLog `
        -RedirectStandardError $extractionWorkerErrorLog `
        -PassThru
    Set-Content -LiteralPath $extractionWorkerPidFile -Value $extractionWorkerProcess.Id -Encoding ASCII
    Start-Sleep -Milliseconds 500
    if ($extractionWorkerProcess.HasExited) {
        if (Test-Path -LiteralPath $extractionWorkerErrorLog) {
            Get-Content -LiteralPath $extractionWorkerErrorLog -Tail 30
        }
        throw "Candidate extraction worker startup failed. See $extractionWorkerErrorLog"
    }
}

Write-Step "Start the AI report worker"
$reportWorkerPidFile = Join-Path $runtimeDir "report-worker.pid"
$reportWorkerLog = Join-Path $logDir "report-worker.log"
$reportWorkerErrorLog = Join-Path $logDir "report-worker.error.log"
Stop-RecordedProcess -PidFile $reportWorkerPidFile
$reportWorkerProcess = Start-Process -FilePath $venvPython `
    -ArgumentList @("scripts\report_worker.py") `
    -WorkingDirectory $backendDir -WindowStyle Hidden `
    -RedirectStandardOutput $reportWorkerLog -RedirectStandardError $reportWorkerErrorLog -PassThru
Set-Content -LiteralPath $reportWorkerPidFile -Value $reportWorkerProcess.Id -Encoding ASCII

Write-Step "Start the research export worker"
Stop-RecordedProcess -PidFile $exportWorkerPidFile
Remove-Item -LiteralPath $exportWorkerLog, $exportWorkerErrorLog -Force -ErrorAction SilentlyContinue
$exportWorkerProcess = Start-Process -FilePath $venvPython `
    -ArgumentList @("scripts\export_worker.py") `
    -WorkingDirectory $backendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $exportWorkerLog `
    -RedirectStandardError $exportWorkerErrorLog `
    -PassThru
Set-Content -LiteralPath $exportWorkerPidFile -Value $exportWorkerProcess.Id -Encoding ASCII
Start-Sleep -Milliseconds 500
if ($exportWorkerProcess.HasExited) {
    if (Test-Path -LiteralPath $exportWorkerErrorLog) {
        Get-Content -LiteralPath $exportWorkerErrorLog -Tail 30
    }
    throw "Export worker startup failed. See $exportWorkerErrorLog"
}

Write-Step "Start the model training worker"
Stop-RecordedProcess -PidFile $modelTrainingWorkerPidFile
Remove-Item -LiteralPath $modelTrainingWorkerLog, $modelTrainingWorkerErrorLog -Force -ErrorAction SilentlyContinue
$modelTrainingWorkerProcess = Start-Process -FilePath $venvPython `
    -ArgumentList @("scripts\model_training_worker.py") `
    -WorkingDirectory $backendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $modelTrainingWorkerLog `
    -RedirectStandardError $modelTrainingWorkerErrorLog `
    -PassThru
Set-Content -LiteralPath $modelTrainingWorkerPidFile -Value $modelTrainingWorkerProcess.Id -Encoding ASCII
Start-Sleep -Milliseconds 500
if ($modelTrainingWorkerProcess.HasExited) {
    if (Test-Path -LiteralPath $modelTrainingWorkerErrorLog) {
        Get-Content -LiteralPath $modelTrainingWorkerErrorLog -Tail 30
    }
    throw "Model training worker startup failed. See $modelTrainingWorkerErrorLog"
}

if (-not $frontendPortOwner) {
    Write-Step "Start the Vite frontend"
    Remove-Item -LiteralPath $frontendLog, $frontendErrorLog -Force -ErrorAction SilentlyContinue
    $env:VITE_DEV_API_TARGET = "http://127.0.0.1:$BackendPort"
    $env:VITE_ALLOWED_HOSTS = $TunnelHostname
    Start-Process -FilePath $pnpm.Source `
        -ArgumentList @(
            "dev", "--",
            "--host", $FrontendHost,
            "--port", "$FrontendPort",
            "--strictPort"
        ) `
        -WorkingDirectory $frontendRuntimeDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendLog `
        -RedirectStandardError $frontendErrorLog | Out-Null

    if (-not (Wait-Http -Uri "http://127.0.0.1:$FrontendPort" -TimeoutSeconds 30)) {
        if (Test-Path -LiteralPath $frontendErrorLog) {
            Get-Content -LiteralPath $frontendErrorLog -Tail 30
        }
        throw "Frontend startup failed. See $frontendErrorLog"
    }
    $frontendProcessId = Get-PortProcessId -Port $FrontendPort
    Set-Content -LiteralPath $frontendPidFile -Value $frontendProcessId -Encoding ASCII
}

if ($EnableTunnel) {
    Write-Step "Start Cloudflare Tunnel"
    $cloudflared = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if (-not $cloudflared) {
        $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
    }
    if (-not $cloudflared) {
        throw "cloudflared was not found. Install it and ensure it is available in PATH."
    }

    if (-not $TunnelTokenFile) {
        $TunnelTokenFile = [Environment]::GetEnvironmentVariable(
            "CLOUDFLARE_TUNNEL_TOKEN_FILE"
        )
    }
    if (-not $TunnelTokenFile) {
        throw "Set -TunnelTokenFile or CLOUDFLARE_TUNNEL_TOKEN_FILE. Do not store the tunnel token in this project."
    }
    $resolvedTokenFile = (Resolve-Path -LiteralPath $TunnelTokenFile `
        -ErrorAction Stop).Path

    Stop-RecordedProcess -PidFile $tunnelPidFile
    Remove-Item -LiteralPath $tunnelLog, $tunnelErrorLog -Force `
        -ErrorAction SilentlyContinue
    $tunnelProcess = Start-Process -FilePath $cloudflared.Source `
        -ArgumentList @(
            "tunnel", "--no-autoupdate", "run",
            "--token-file", "`"$resolvedTokenFile`""
        ) `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $tunnelLog `
        -RedirectStandardError $tunnelErrorLog `
        -PassThru
    Set-Content -LiteralPath $tunnelPidFile -Value $tunnelProcess.Id `
        -Encoding ASCII
    Start-Sleep -Seconds 2
    if ($tunnelProcess.HasExited) {
        if (Test-Path -LiteralPath $tunnelErrorLog) {
            Get-Content -LiteralPath $tunnelErrorLog -Tail 30
        }
        throw "Cloudflare Tunnel startup failed. See $tunnelErrorLog"
    }
}

Write-Host "`nDevelopment services are ready:" -ForegroundColor Green
Write-Host "  Frontend http://127.0.0.1:$FrontendPort"
Write-Host "  Backend  http://127.0.0.1:$BackendPort"
Write-Host "  API docs http://127.0.0.1:$BackendPort/docs"
Write-Host "  ASR      $asrProvider"
if ($EnableTunnel) {
    Write-Host "  Public   https://$TunnelHostname"
}
Write-Host "  Logs     $logDir" -ForegroundColor DarkGray
Write-Host "  Stop     .\stop.ps1" -ForegroundColor DarkGray

if ($OpenBrowser) {
    Start-Process "http://127.0.0.1:$FrontendPort"
}
