# 節流晨報後端 — 開機/登入自啟腳本
# 供「工作排程器」在登入時呼叫，見 README「開機自啟」一節。

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvActivate = Join-Path $root ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
    Write-Host "找不到 .venv，請先執行：python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}

. $venvActivate
uvicorn backend.main:app --host 127.0.0.1 --port 8788
