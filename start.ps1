param(
    [switch]$Ngrok,
    [string]$NgrokUrl = '',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot
if ($env:OS -ne 'Windows_NT') { throw 'This launcher requires Windows 10/11 x64.' }
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run setup.bat first.' }
foreach ($file in @('models\qwen3-4b.gguf', 'models\voice.onnx', 'models\voice.onnx.json', 'models\vosk-model-small-ru-0.22\am\final.mdl')) {
    if (-not (Test-Path $file)) { throw "Missing $file. Run setup.bat first (without -SkipModels)." }
}
# A fresh terminal may be needed after winget changes PATH.
$env:Path += ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue)) { throw 'FFmpeg is missing. Run setup.bat first.' }
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is in use. Close the previous app instance and retry.'
}
if ($Ngrok -and -not $env:NGROK_AUTHTOKEN -and -not (Test-Path '.ngrok.yml')) {
    $secret = Read-Host 'Enter the ngrok Agent Authtoken (hidden)' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try { $env:NGROK_AUTHTOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if (-not $env:NGROK_AUTHTOKEN) { throw 'An ngrok Agent Authtoken is required.' }
}
if ($NgrokUrl) { $env:NGROK_URL = $NgrokUrl }

$server = $null
try {
    $server = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '8000') -PassThru -NoNewWindow -RedirectStandardOutput 'server.log' -RedirectStandardError 'server-error.log'
    Write-Host 'Loading local models. First startup can take a few minutes...'
    $deadline = (Get-Date).AddMinutes(5)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($server.HasExited) { throw 'Server exited. See server-error.log.' }
        $state = $null
        if (Test-Path '.access-token') {
            $token = (Get-Content -LiteralPath '.access-token' -Raw).Trim()
            try { $state = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/status' -Headers @{ 'x-access-token' = $token } -TimeoutSec 2 }
            catch { $state = $null }
        }
        if ($null -ne $state) {
            if ($state.error) { throw "Model loading failed: $($state.error)" }
            if ($state.ready) { $ready = $true; break }
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Model loading timed out. See server-error.log.' }
    $localUrl = 'http://localhost:8000/#' + $token
    Write-Host "Local app: $localUrl"
    Write-Host 'Keep this window open. Press Ctrl+C to stop.'
    if (-not $NoBrowser) { Start-Process $localUrl }
    if ($Ngrok) {
        & $python 'tunnel.py'
        if ($LASTEXITCODE -ne 0) { throw 'ngrok stopped with an error. Check the message above.' }
    } else {
        while (-not $server.HasExited) { Start-Sleep -Seconds 1 }
        if ($server.ExitCode -ne 0) { throw 'Server exited with an error. See server-error.log.' }
    }
} finally {
    if ($null -ne $server -and -not $server.HasExited) { Stop-Process -Id $server.Id -ErrorAction SilentlyContinue }
}
