# 交易大腦（獨立全端專案）

動態量化選幣 ＋ AI 總經新聞情緒 ＋ 20 EMA/盤整盒子技術面訊號的獨立監控平台，**同一個網站**
再整合了 `../knowledge_universe/`（Supabase 上的遊戲化投資知識庫）當第二個分頁。跟 repo 根目錄
的 `backend/`（節流晨報）是**完全獨立的專案**，互不依賴、互不影響，可以各自單獨啟動。

打開 `http://127.0.0.1:8000` 後，右上角有兩個分頁：
- **🎯 當沖訊號**：原本的當沖訊號儀表板（見下方各節）。
- **📚 知識宇宙**：知識卡瀏覽（依技術面/基本面/籌碼面/情緒面/總經面篩選、點卡片看詳情、
  任務列表），直接用瀏覽器打 Supabase REST API 讀取，不用另外啟動伺服器，只需要這個
  FastAPI app 透過 `/api/v1/config` 把 Supabase URL／anon key 交給前端。

> ⚠️ **這是訊號監控工具，不是自動化交易系統。** 全程不使用任何交易所 API 金鑰、不下單、
> 不動用真實資金。所有訊號僅供研究參考，不構成投資建議。若之後要接上真正的自動化下單，
> 需要另外評估金鑰保管、風控上限、模擬盤驗證等安全機制——目前刻意不包含。

## 架構

```
trading_system/
├─ app.py            # FastAPI 進入點：REST API（含手動觸發用的 POST /api/v1/analyze）+ 掛載 index.html
├─ background.py      # 分析邏輯：OKX 篩選 → K線 → 技術訊號 → 融合 AI 新聞情緒，跑一輪
├─ okx_client.py       # OKX public REST：商品篩選（screen_active_instruments）+ K線抓取
├─ strategy.py          # 技術面大腦：20 EMA + 盤整盒子突破（純函式，內建自測）
├─ news_client.py        # AI 新聞大腦：抓 RSS 頭條 → LLM 判斷多空情緒（Anthropic/OpenAI）
├─ brain.py               # 多空共振：技術面 + AI 情緒融合成最終建議（純函式，內建自測）
├─ state.py                # 行程內記憶體狀態（上一輪分析結果，REST 端點讀寫）
├─ index.html                # 網頁前端：🎯當沖訊號／📚知識宇宙 兩個分頁的單一 SPA
├─ static/tailwind.css        # 編譯好的樣式表（已 commit，見下方「前端樣式」），伺服器直接掛載 /static
├─ package.json                # 只用來跑 Tailwind CLI 編譯 static/tailwind.css，非必要不用裝
├─ requirements.txt           # fastapi / uvicorn / httpx / pandas / python-dotenv
└─ .env.example                # 環境變數範本
```

### 前端樣式：不依賴任何外部 CDN

`index.html` 原本用 `<script src="https://cdn.tailwindcss.com">`——這是 Tailwind 官方文件
自己都寫明「僅供原型測試，不建議正式使用」的執行期 JIT 編譯器：每次打開頁面都要連網抓
這個 script、在瀏覽器裡即時編譯樣式。網路環境較嚴（公司防火牆、部分地區）連不上這個 CDN，
整頁會完全沒有樣式（這不是假設——這個專案的開發環境就完全連不上它，也連不上 `okx.com`）。

現在改成用 Tailwind CLI 預先編譯出 `static/tailwind.css`（已經 commit 進 repo，一般啟動
伺服器不需要 Node.js，直接能跑）。如果你改了 `index.html` 裡用到的 class（新增/修改樣式），
需要重新編譯：

```bash
cd trading_system
npm install    # 只裝 tailwindcss 這一個 devDependency
npm run build:css
```

`node_modules/` 已加進 `.gitignore`，不會被 commit；`static/tailwind.css`（編譯產物）跟
`package.json`／`package-lock.json`／`tailwind.config.js`（編譯設定）都會被 commit，這樣
別人 clone 下來不用裝 Node 也能直接跑，只有要改樣式的人才需要。

`config.py` 另外存了 `SUPABASE_URL` / `SUPABASE_ANON_KEY`（預設值指向已部署好的
`investment-knowledge-universe` 專案，anon key 是公開金鑰、給前端直接用沒有資安疑慮）。
`GET /api/v1/config` 把這兩個值交給前端，「知識宇宙」分頁載入時直接用瀏覽器 `fetch()` 打
Supabase 的 PostgREST API（`{SUPABASE_URL}/rest/v1/knowledge_nodes` 等），沒有另外寫後端
代理端點——因為 `knowledge_nodes`／`knowledge_edges`／`missions` 這三張表在 Supabase 上本來
就設成公開唯讀（見 `../knowledge_universe/README.md`）。

> **沒有背景排程。** 舊版本會在背景每 30 秒自動重算一次、每 10 分鐘自動打一次 AI，
> 現在改成純手動：伺服器啟動後**完全不會**呼叫任何 OKX／AI API，只有你在網頁上按下
> 「🔍 立即分析」，前端才會打 `POST /api/v1/analyze`，後端才跑一輪分析。用量（尤其是
> AI token）完全由你點擊的次數決定，不會有背景空轉的隱藏消耗。

## 啟動方式

```bash
cd trading_system
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env        # 沒有 AI 金鑰也能跑，見下方「AI 新聞情緒」
# 用編輯器打開 .env 視需要調整門檻/金鑰

cd ..                       # 回到 repo 根目錄，因為模組用相對匯入（trading_system 套件）
uvicorn trading_system.app:app --host 127.0.0.1 --port 8000
```

打開瀏覽器 `http://127.0.0.1:8000` 即可看到儀表板（後端直接把 `index.html` 掛在 `/`）。
也可以不啟動網頁伺服器服務前端，直接雙擊 `trading_system/index.html` 用瀏覽器打開——
後端 CORS 全開放，一樣能連上 `http://127.0.0.1:8000/api/v1/dashboard`。

頁面打開後不會自動跑分析，按右上角「🔍 立即分析」才會觸發一輪 OKX 篩選＋K線＋AI 新聞情緒；
分析中按鈕會顯示「分析中…」並鎖住，避免手滑連點打出兩輪同時進行的請求。

## 自測（不需要網路，也不需要 AI 金鑰）

```bash
python -m trading_system.okx_client   # 商品篩選邏輯自測
python -m trading_system.strategy     # 20 EMA + 盒子突破訊號自測
python -m trading_system.brain        # 多空共振融合邏輯自測
python -m trading_system.news_client  # JSON 解析（LLM 回覆容錯）自測
```

## AI 新聞情緒 — 如何啟用

預設 `AI_PROVIDER=anthropic`。沒填金鑰時系統不會出錯，只是新聞情緒固定回傳 `NEUTRAL`
並在 `news_reason` 附上提示，技術面訊號仍照常運作（面板上會顯示「技術面做多/做空（未經新聞驗證）」）。

**建立 Anthropic（Claude）API 金鑰：** https://console.anthropic.com/settings/keys
1. 用你的帳號登入 Anthropic Console。
2. 左側選單「API Keys」→「Create Key」，複製產生的金鑰（只會顯示一次）。
3. 貼進 `trading_system/.env` 的 `ANTHROPIC_API_KEY=`。
4. 重新啟動 `uvicorn`，回到網頁按一次「立即分析」，就會看到真實的 AI 新聞判讀。

也支援 OpenAI 當替代方案：把 `.env` 的 `AI_PROVIDER` 改成 `openai`，並在
https://platform.openai.com/api-keys 建立金鑰後填入 `OPENAI_API_KEY`。

`.env` 已加進根目錄 `.gitignore`（`trading_system/.env`），金鑰不會被 commit 進版本控制。

## 商品篩選門檻（`.env` 可調）

| 變數 | 預設 | 說明 |
|---|---|---|
| `MIN_VOL_USDT` | 50,000,000 | 24h 成交額門檻（USDT），過濾流動性不足的商品 |
| `MIN_AMPLITUDE_PCT` | 3.0 | 24h 振幅門檻（%），過濾波動太小、扣手續費後沒利潤空間的商品 |
| `TOP_N` | 6 | 最終精選監控幾檔（依振幅由高到低排序） |
| `EMA_PERIOD` / `BOX_LOOKBACK` | 20 / 15 | 20 EMA 週期、盒子回看根數 |
| `CANDLE_BAR` | 5m | K 線週期 |
| `TP1_RR` / `TP2_RR` | 1.5 / 2.0 | 停利風報比（reward:risk）；risk = │進場價 − 停損價│ |

## API

| 端點 | 方法 | 說明 |
|---|---|---|
| `/api/v1/dashboard` | GET | 讀取「上一次」分析結果的快取，不觸發新分析、不打任何外部 API |
| `/api/v1/analyze` | POST | 觸發一輪全新分析（OKX 篩選＋K線＋AI 新聞情緒），跑完回傳結果；上一輪還沒跑完時回 `409` |
| `/api/v1/health` | GET | 存活檢查 + 上次更新時間 + 上次錯誤訊息 |

## 訊號邏輯

**技術面**（`strategy.py`）：跟 20 EMA 的相對位置決定只做多或只做空；最近 `BOX_LOOKBACK`
根已收盤 K 線的高低點框出「盤整盒子」；當前這根**已收盤**（非正在走的那根，避免插針假突破——
見 `okx_client.fetch_confirmed_candles` 的說明）K 線實體突破盒子且同向站上/跌破 EMA 才觸發訊號。
停損固定設在盒子中線；停利用風報比算：risk = │進場價 − 停損價│，TP1 = 進場價 ± risk × `TP1_RR`
（預設 1.5，可先減碼）、TP2 = 進場價 ± risk × `TP2_RR`（預設 2.0，留給趨勢延續的部位）。

**AI 新聞情緒**（`news_client.py`）：抓 CoinDesk／CoinTelegraph 公開 RSS 頭條，丟給 LLM 判斷
整體市場是利多/利空/中性。

**多空共振**（`brain.py`）：技術面訊號跟 AI 新聞情緒同向 → 標記「強烈做多/做空」；技術面突破但
AI 新聞情緒明確反向 → 標記「潛在假突破，觀望」並不建議進場；AI 新聞中性或未啟用 → 顯示純技術面訊號。

## 股票永續合約（Stock Perpetuals）支援狀況

OKX 已於 2026 年上線股票永續合約（TSLA/AAPL/NVDA/GOOGL/MSFT/AMZN/META 等，USDT 計價、
24/7 交易，形式跟加密貨幣永續合約一樣）。`screen_active_instruments()` 本身**不分資產
類別**，只要商品 `instId` 符合 `*-USDT-SWAP` 且達到成交額/振幅門檻就會一起入選、套用
同一套 20 EMA + 盒子策略——如果 OKX 把股票永續也掛在同一個 `instType=SWAP` 底下，
理論上不需要額外開發就會自動出現在監控清單，畫面上會標「📈 股票永續」跟加密貨幣的
「🪙 加密貨幣」區分開來（見 `okx_client.KNOWN_STOCK_TICKERS` / `asset_class()`）。

這件事目前**還沒有實際對 API 驗證過**（開發環境的網路政策擋掉了 okx.com，連不上）。
建議你在能連上 OKX 的機器上跑一次：

```powershell
# PowerShell
(Invoke-RestMethod "https://www.okx.com/api/v5/market/tickers?instType=SWAP").data |
  Where-Object { $_.instId -match "TSLA|AAPL|NVDA|GOOGL|MSFT|AMZN|META" } |
  Select-Object instId, last
```

```bash
# curl（Mac/Linux 或 Windows 的 WSL/Git Bash）
curl -s "https://www.okx.com/api/v5/market/tickers?instType=SWAP" | \
  grep -oE '"instId":"[^"]*(TSLA|AAPL|NVDA|GOOGL|MSFT|AMZN|META)[^"]*"'
```

跑出來如果看到類似 `TSLA-USDT-SWAP` 的結果，代表現有程式碼不用改就能撈到；如果命名
格式不一樣（例如帶了其他前綴/後綴），把實際看到的代碼告訴我，我再調整
`asset_class()` 的比對規則，或直接透過 `.env` 的 `EXTRA_INSTRUMENT_KEYWORDS` 手動納入。

## 跟 `backend/`（節流晨報）的關係

完全獨立，兩者可以同時或分別運行，不共用程式碼、不共用資料庫、不共用連接埠（節流晨報用
`8788`，這個專案預設用 `8000`）。節流晨報刻意維持「零 AI／零 token」的設計原則；這個專案
是另一條路線的實驗（會呼叫 AI、需要 API 金鑰），所以獨立成自己的資料夾，不動節流晨報既有程式碼。
