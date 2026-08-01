# 節流晨報 — 後端化加密貨幣晨報

本機服務：**後端定時抓取加密市場公開數據 → 本地計算指標 → 存 SQLite → 前端經 REST API 與 WebSocket 讀取**。

硬約束：
- 資料層與運算層零 AI 呼叫、零 token 消耗，全程只打公開行情 API（不爬蟲、不解析 HTML）。
- 依賴僅：`fastapi`、`uvicorn[standard]`、`apscheduler`、`httpx`（後端）；指標計算為純 Python。
- 不用 Redis / Docker / Celery / ORM / 使用者認證 / pandas。

## 專案結構

```
backend/
├─ main.py         # FastAPI app：REST + WS + 啟動 APScheduler + OKX WS 背景任務 + 掛載前端靜態檔
├─ fetcher.py       # 抓取器：CoinGecko 為主、OKX public 為備援；台股/美股/大宗商品；OHLC
├─ indicators.py    # RSI14 / SMA / 年化波動率 / 最大回撤 / 布林通道 / DMI（純 Python，內建自測）
├─ smc.py           # SMC 市場結構分析：swing/BOS/CHoCH/FVG（純 Python，內建自測）
├─ trade_plan.py    # 規則式交易計畫合成（零 AI）：方向/評分/SL/TP1/TP2（純 Python，內建自測）
├─ okx_ws.py        # M6：OKX public WebSocket 客戶端，秒級 tick 直推前端
├─ db.py            # SQLite 連線、schema、讀寫函式（WAL 模式）
├─ scheduler.py      # APScheduler 任務定義與註冊（含測試模式）
└─ state.py         # 進程內記憶體快取（最新快照）＋ WS 連線管理器
frontend/           # Vite + React（《節流晨報》頁面）
data/brief.db       # SQLite（自動建立，已 .gitignore）
scripts/
├─ smoke.ps1        # 驗收煙霧測試（REST + WebSocket）
├─ ws_smoke.py       # smoke.ps1 的 WebSocket 檢查腳本
└─ start.ps1        # 開機/登入自啟腳本
requirements.txt
```

## 啟動方式

```powershell
cd C:\Users\sky10\projects\jieliu-brief
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8788
```

打開瀏覽器 `http://127.0.0.1:8788` 即可看到《節流晨報》頁面（後端啟動時已掛載 `frontend/dist`）。

### 前端開發模式（另開視窗，僅開發時需要）

```powershell
cd frontend
npm install
npm run dev
```

Vite dev server（`http://localhost:5173`）已設定 proxy，`/api/*` 與 `/ws` 會轉發到 `127.0.0.1:8788`；後端也已對 `http://localhost:5173` 開放 CORS。

### 重新建置前端（改完 `frontend/src` 後）

```powershell
cd frontend
npm run build
```

`npm run build` 會輸出到 `frontend/dist`，FastAPI 啟動時偵測到此目錄即自動掛載於 `/`。

## 驗收（Milestones）

跑之前先啟動服務（見上），再開一個新視窗：

```powershell
.\scripts\smoke.ps1
```

會依序打 `/api/health`、`/api/latest`、`/api/klines`（M2），再用 `ws_smoke.py` 連 `/ws` 等最多 90 秒看是否收到快照（M3）。全數印出 `[PASS]` 且結尾顯示「煙霧測試：全數通過」即算過。

M1（資料層）可獨立驗證，不需啟動 FastAPI：

```powershell
python -m backend.indicators   # RSI/SMA/波動率/回撤/布林/DMI 自測，全過印 PASS
python -m backend.smc          # SMC 市場結構/BOS/CHoCH/FVG 自測，全過印 PASS
python -m backend.trade_plan   # 交易計畫合成自測，全過印 PASS
python -m backend.scheduler    # 測試模式：跑一輪所有排程任務，檢查 data/brief.db 是否出現且有 snapshots
```

> `python -m backend.scheduler` 需要能連上 `api.coingecko.com` / `www.okx.com` / `api.alternative.me`。若你的網路環境（公司防火牆、代理伺服器）擋掉這些網域，該指令會在 log 印出重試失敗訊息並優雅跳過（不會 crash），但不會寫入 snapshot——這是設計行為，不是 bug。之後 `uvicorn` 正式啟動、能連上外網時就會恢復正常寫入。

## API 合約（`127.0.0.1:8788`）

- `GET /api/health` → `{ "ok": true, "last_fetch_ts": 1753850000, "source": "coingecko", "consecutive_failures": 0 }`
- `GET /api/latest` → 最新快照：
  ```json
  { "ts": 1753850000, "source": "coingecko",
    "quotes": { "BTC": {"usd": 96500.0, "chg24": -2.1}, "ETH": {...}, "SOL": {...}, "BNB": {...} },
    "fng": { "value": 34, "label": "Fear" },
    "indicators": { "rsi14": 41.0, "ma20": 95100.0, "ma60": 91800.0,
                    "ma_bias_pct": 3.59, "ann_vol_pct": 52.0, "mdd90_pct": -18.3, "chg7_pct": -1.2 },
    "markets": { "tw_stocks": {"2330": {"name": "台積電", "price": 1080.0, "chg_pct": 1.2}, ...},
                 "us_stocks": {"AAPL": {...}, ...}, "commodities": {"GC=F": {...}, ...} },
    "smc": { "structure": "bullish", "last_event": {"type": "BOS", "direction": "bullish", "level": 95000.0}, "fvgs": [...] },
    "trade_plan": { "available": true, "bias": "bullish", "plan_score": 80, "win_rate_pct": 74,
                     "levels": {"sl": 93000.0, "tp1": 99000.0, "tp2": 102000.0, "rr1": 1.0, "rr2": 1.5},
                     "reasons": [...], "disclaimer": "本地規則式合成，非 AI 研判、非投資建議" } }
  ```
- `GET /api/history?hours=24` → snapshots 陣列（同上結構，最多 720 筆）
- `GET /api/klines?symbol=BTC&days=90` → `[{ "day": "2026-07-30", "close": 96500.0 }, ...]`
- `GET /api/smc?symbol=BTC` → 同快照裡的 `smc` 欄位
- `GET /api/trade_plan?symbol=BTC` → 同快照裡的 `trade_plan` 欄位
- `WS /ws` → 連上先推最新快照，之後每次排程更新即推播完整快照；M6 額外會推播 `{"type":"tick","symbol":"BTC","usd":...,"chg24":...}` 秒級價格更新；閒置 30 秒送一次 `{"type":"heartbeat","ts":...}` 心跳

## 排程表（跑在 `main.py` 進程內，APScheduler）

| 任務 | 頻率 | 內容 |
|---|---|---|
| fetch_quotes | 每 60 秒 | BTC/ETH/SOL/BNB 現價＋24h 變化 → 合併快照 → 寫 DB → 推播 WS |
| fetch_fng | 每 60 分 | 恐懼貪婪指數 |
| fetch_klines | 每 60 分 | BTC 日 K（close-only）近 100 根 → upsert `kline_daily` → 重算 RSI/SMA/波動率/回撤 |
| fetch_ohlc | 每 60 分 | BTC 完整 OHLCV 近 100 根（OKX）→ upsert `kline_ohlc_daily` → 重算 SMC 與交易計畫 |
| fetch_markets | 每 5 分 | 台股（TWSE）／美股／大宗商品期貨（Yahoo Finance）預設觀察清單 |
| prune | 每日 04:00 | 清 30 天前的 snapshots |
| OKX WS（M6） | 常駐背景任務，非排程 | 連 OKX public WebSocket，秒級 tick 直推所有 `/ws` 連線；斷線自動重連（指數退避，2s→60s） |

抓取端點（CoinGecko 為主，連續失敗 3 次自動切 OKX 備援，恢復後自動切回）：

| 用途 | 端點 |
|---|---|
| 現價（主） | `GET https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana,binancecoin&vs_currencies=usd&include_24hr_change=true` |
| 現價（備援） | `GET https://www.okx.com/api/v5/market/tickers?instType=SPOT` |
| 恐懼貪婪指數 | `GET https://api.alternative.me/fng/?limit=1` |
| 日 K close-only（主） | `GET https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=100&interval=daily` |
| 日 K close-only（備援） | `GET https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1D&limit=100` |
| 日 K 完整 OHLCV（SMC 用） | `GET https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1D&limit=100`（CoinGecko 免費版 OHLC 端點超過 30 天會退化成 4 天一根，非真日K，故 SMC 固定用 OKX） |
| 台股即時 | `GET https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw\|tse_2317.tw\|...`（預設：加權指數、台積電、鴻海、聯發科） |
| 美股／大宗商品 | `GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}`（美股預設：SPY/AAPL/MSFT/NVDA；商品預設：黃金 GC=F／WTI原油 CL=F／白銀 SI=F） |
| OKX 秒級行情（M6，WebSocket） | `wss://ws.okx.com:8443/ws/v5/public`，訂閱 `tickers` 頻道 |

> 台股／美股／大宗商品都是**預設觀察清單**，不是全市場，想調整就改 `backend/fetcher.py` 裡的 `TW_STOCKS` / `US_STOCKS` / `COMMODITIES` 三個 dict。

## SMC 市場結構與交易計畫（零 AI）

`backend/smc.py` 用純 Python 對 BTC 的完整 OHLC 日K做三件事：
- **市場結構**：抓 local swing high/low，判斷 higher-high+higher-low（bullish）／lower-high+lower-low（bearish）／其餘 ranging。
- **BOS／CHoCH**：收盤價順著既有結構突破前高/前低＝BOS（順勢延續）；逆著結構突破＝CHoCH（結構轉變，可能反轉）。
- **FVG（公允價值缺口）**：三根K線一組，第1根高/低與第3根低/高之間出現價格真空。

`backend/trade_plan.py` 再疊加 RSI14、均線乖離、DMI（+DI/-DI/ADX）、布林通道，用簡單多數決規則（不是統計回測、不是 AI）給出方向、評分（0–100）、粗略勝率估算，以及 SL／TP1（1:1 風報比）／TP2（1:1.5）三個價位。這整條路徑（`fetch_ohlc` → `smc.compute_smc` → `trade_plan.build_trade_plan`）全程本地運算、零 AI token；輸出明確標示「本地規則式合成，非 AI 研判、非投資建議」。

## 開機自啟（M5，不做成 Windows 服務）

用「工作排程器」在登入時執行 `scripts\start.ps1`：

1. 開啟「工作排程器」→ 建立工作。
2. 觸發程序：新增 →「登入時」。
3. 動作：新增 → 程式/指令碼填 `powershell.exe`，引數填
   `-ExecutionPolicy Bypass -File "C:\Users\sky10\projects\jieliu-brief\scripts\start.ps1"`。

`start.ps1` 會啟用 `.venv` 並在 `127.0.0.1:8788` 跑 `uvicorn`（前景執行；若要背景執行，工作排程器的「不管使用者是否登入均執行」選項可搭配 `-WindowStyle Hidden`）。

## M6（選配，已實作）— OKX WebSocket 秒級即時

`backend/okx_ws.py` 在 `main.py` 啟動時起一個常駐背景 task，連 OKX public WebSocket（`wss://ws.okx.com:8443/ws/v5/public`）訂閱 BTC/ETH/SOL/BNB 的 `tickers` 頻道，每次有新報價就直接透過 `/ws` 推播 `{"type":"tick",...}` 給所有前端連線（不寫 DB、不動既有 60 秒快照管線）。斷線會指數退避重連（2s→60s）。用的是 `websockets` 套件，已隨 `uvicorn[standard]` 一併安裝，不用額外加依賴。
