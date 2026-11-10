param([switch]$SkipModels)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot
if ($env:OS -ne 'Windows_NT') { throw 'This installer requires Windows 10/11 x64.' }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit code $LASTEXITCODE)." }
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Find-Python {
    $candidates = @()
    if (Get-Command python.exe -ErrorAction SilentlyContinue) {
        $path = (Get-Command python.exe).Source
        if ($path -notlike '*\WindowsApps\python.exe') { $candidates += $path }
    }
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        try {
            $path = & py.exe -3.12 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0) { $candidates += $path }
        } catch { }
    }
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            try {
                & $candidate -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 1)' 2>$null
                if ($LASTEXITCODE -eq 0) { return $candidate }
            } catch { }
        }
    }
    return $null
}

function Install-WithWinget {
    param([string]$Package, [switch]$PerUser)
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "winget is missing. Install Microsoft App Installer from Microsoft Store, or install $Package manually and rerun setup.bat."
    }
    $arguments = @('install', '--id', $Package, '--exact', '--architecture', 'x64', '--accept-package-agreements', '--accept-source-agreements')
    if ($PerUser) { $arguments += @('--scope', 'user') }
    Invoke-Checked 'winget.exe' $arguments
    Refresh-Path
}

function Download-File {
    param([string]$Url, [string]$Destination)
    if (Test-Path $Destination) { return }
    Write-Host "Downloading $Destination (rerun setup.bat to resume if interrupted)..."
    Invoke-Checked 'curl.exe' @('--fail', '--location', '--retry', '3', '--continue-at', '-', '--output', "$Destination.part", $Url)
    Move-Item -LiteralPath "$Destination.part" -Destination $Destination
}

$python = Find-Python
if (-not $python) {
    Install-WithWinget 'Python.Python.3.12' -PerUser
    $python = Find-Python
}
if (-not $python) { throw 'Python 3.12 x64 was not found. Reopen the terminal and rerun setup.bat.' }
if (-not (Test-Path "$env:WINDIR\System32\vcruntime140_1.dll")) {
    Write-Host 'Installing the Microsoft C++ runtime. Windows may ask for administrator approval.'
    Install-WithWinget 'Microsoft.VCRedist.2015+.x64'
}
if (-not (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue)) {
    Install-WithWinget 'Gyan.FFmpeg' -PerUser
}
if (-not (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue)) {
    throw 'FFmpeg was not found. Reopen the terminal and rerun setup.bat.'
}
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    throw 'curl.exe is required (included in current Windows 10/11). Update Windows and retry.'
}

Invoke-Checked $python @('-m', 'venv', '.venv')
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--upgrade', 'pip')
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--only-binary=llama-cpp-python', '--extra-index-url', 'https://abetlen.github.io/llama-cpp-python/whl/cpu', '-r', 'requirements.txt')
Invoke-Checked $venvPython @('-c', 'from vosk import Model; from llama_cpp import Llama; from piper import PiperVoice; import fastapi, pyngrok')
Write-Host 'Native libraries: OK'

if (-not $SkipModels) {
    New-Item -ItemType Directory -Force 'models' | Out-Null
    if (-not (Test-Path 'models\vosk-model-small-ru-0.22\am\final.mdl')) {
        Download-File 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip' 'models\vosk.zip'
        Expand-Archive -LiteralPath 'models\vosk.zip' -DestinationPath 'models' -Force
        Remove-Item -LiteralPath 'models\vosk.zip'
    }
    Download-File 'https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf' 'models\qwen3-4b.gguf'
    foreach ($suffix in @('onnx', 'onnx.json')) {
        Download-File "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.$suffix" "models\voice.$suffix"
    }
}
Write-Host 'Setup complete. Run start.bat, or start.bat -Ngrok for phone access.'
