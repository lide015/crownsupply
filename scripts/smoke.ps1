# 節流晨報後端 — 驗收煙霧測試 (M2 REST + M3 WebSocket)
# 使用前請先在另一個視窗啟動服務：
#   .\.venv\Scripts\Activate.ps1
#   uvicorn backend.main:app --host 127.0.0.1 --port 8788

$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8788"
$failed = $false

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Url,
        [string[]]$RequiredFields
    )
    try {
        $resp = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 10
        foreach ($f in $RequiredFields) {
            if (-not ($resp.PSObject.Properties.Name -contains $f)) {
                Write-Host "[FAIL] $Name 缺少欄位 '$f'" -ForegroundColor Red
                $script:failed = $true
                return
            }
        }
        Write-Host "[PASS] $Name (200，欄位齊全)" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] $Name : $($_.Exception.Message)" -ForegroundColor Red
        $script:failed = $true
    }
}

Write-Host "== M2 REST 驗收 =="
Test-Endpoint -Name "/api/health" -Url "$base/api/health" -RequiredFields @("ok", "last_fetch_ts", "source", "consecutive_failures")
Test-Endpoint -Name "/api/latest" -Url "$base/api/latest" -RequiredFields @("ts", "source", "quotes", "fng", "indicators")
Test-Endpoint -Name "/api/klines" -Url "$base/api/klines?symbol=BTC&days=90" -RequiredFields @()

Write-Host "`n== M3 WebSocket 驗收（最多等 90 秒）=="
$wsScript = Join-Path $PSScriptRoot "ws_smoke.py"
python $wsScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] /ws 在 90 秒內未收到快照" -ForegroundColor Red
    $failed = $true
} else {
    Write-Host "[PASS] /ws 收到快照" -ForegroundColor Green
}

if ($failed) {
    Write-Host "`n煙霧測試：有項目失敗" -ForegroundColor Red
    exit 1
} else {
    Write-Host "`n煙霧測試：全數通過" -ForegroundColor Green
    exit 0
}
