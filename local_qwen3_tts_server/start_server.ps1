param(
    [string] $Voice = "Aiden",
    [int] $Port = 8000,
    [string] $Model = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
    [string] $HostAddress = "0.0.0.0",
    [string] $HfHome = "",
    [string] $SoxPath = ""
)

$ErrorActionPreference = "Stop"

$ServerRoot = $PSScriptRoot
$RepoRoot = Split-Path -Parent $ServerRoot
$Python = Join-Path $ServerRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Missing Qwen3-TTS venv at $Python. Create it and install local_qwen3_tts_server\requirements.txt first."
}

if (-not $HfHome) {
    $HfHome = Join-Path (Split-Path -Parent $RepoRoot) "hf_cache"
}

if (-not $SoxPath) {
    $SoxCommand = Get-Command sox.exe -ErrorAction SilentlyContinue
    if ($SoxCommand) {
        $SoxPath = Split-Path -Parent $SoxCommand.Source
    } else {
        $WingetSox = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter sox.exe -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
        if ($WingetSox) {
            $SoxPath = Split-Path -Parent $WingetSox
        }
    }
}

if ($SoxPath) {
    $env:Path = "$SoxPath;$env:Path"
}

$env:HF_HOME = $HfHome
$env:QWEN_TTS_MODEL = $Model
$env:QWEN_TTS_VOICE = $Voice
$env:QWEN_TTS_HOST = $HostAddress
$env:QWEN_TTS_PORT = "$Port"
$env:QWEN_TTS_ATTN_IMPLEMENTATION = ""
$env:QWEN_TTS_WARMUP = "0"

Write-Host "Starting Qwen3-TTS on http://$HostAddress`:$Port with voice $Voice"
Write-Host "HF_HOME=$env:HF_HOME"
& $Python -m local_qwen3_tts_server.server
