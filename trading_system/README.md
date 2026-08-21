# 交易大腦（獨立全端專案）

動態量化選幣 ＋ AI 總經新聞情緒 ＋ 20 EMA/盤整盒子技術面訊號的獨立監控平台，**同一個網站**
再整合了 `../knowledge_universe/`（Supabase 上的遊戲化投資知識庫）當第二個分頁。跟 repo 根目錄
的 `backend/`（節流晨報）是**完全獨立的專案**，互不依賴、互不影響，可以各自單獨啟動。

打開 `http://127.0.0.1:8000` 後，右上角有兩個分頁：
- **🎯 當沖訊號**：原本的當沖訊號儀表板（見下方各節）。
- **📚 知識宇宙**：知識卡瀏覽，卡片格狀列表／🗺️ 知識地圖（SVG 節點+連線圖）兩種檢視可切換，
  依技術面/基本面/籌碼面/情緒面/總經面篩選、點卡片看詳情、任務列表、還有 **🥊 AI 辯論空間**
  （針對這張卡跟 AI 多輪來回辯論，不是單次問答，詳見下方「AI 辯論空間」一節）。知識卡資料
  直接用瀏覽器打 Supabase REST API 讀取，不用另外啟動伺服器，只需要這個 FastAPI app 透過
  `/api/v1/config` 把 Supabase URL／anon key 交給前端；辯論則是打這個 app 自己的
  `/api/v1/coach` 端點。

> ⚠️ **這是訊號監控工具，不是自動化交易系統。** 全程不使用任何交易所 API 金鑰、不下單、
> 不動用真實資金。所有訊號僅供研究參考，不構成投資建議。若之後要接上真正的自動化下單，
> 需要另外評估金鑰保管、風控上限、模擬盤驗證等安全機制——目前刻意不包含。

## 架構

```
trading_system/
├─ app.py            # FastAPI 進入點：REST API（含手動觸發用的 POST /api/v1/analyze）+ 掛載 index.html
├─ background.py      # 分析邏輯：結算舊訊號 → OKX 篩選 → 逐檔+整體 AI 新聞情緒 → K線 → 技術訊號 → 融合，跑一輪
├─ okx_client.py       # OKX public REST：全部商品解析（parse_instruments）+ 自動篩選（screen_active_instruments）+ K線抓取
├─ strategy.py          # 技術面大腦：20 EMA + 盤整盒子突破（純函式，內建自測）
├─ news_client.py        # AI 新聞大腦：抓 RSS 頭條 → LLM 判斷多空情緒（Anthropic/OpenAI）
├─ brain.py               # 多空共振：技術面 + AI 情緒融合成最終建議（純函式，內建自測）
├─ outcome_tracker.py      # 訊號結果模擬 + 失效原因判斷（純規則，零 AI 成本，內建自測）
├─ strategy_tuner.py        # 勝率偏低時自動調高篩選門檻（純函式，內建自測）
├─ ai_coach.py                # AI 辯論空間：多輪對話，走 Anthropic/OpenAI（內建自測）
├─ position_sizing.py          # 🧮 倉位計算機：資金/風險%/進場停損價 → 建議部位大小（純函式，內建自測）
├─ ranking.py                    # 📊 推薦強度榜：技術/籌碼/情緒/量能四維度評分排名（純函式，內建自測）
├─ market_pulse.py                # 🌡️ 市場情緒：平均 RSI、山寨季代理指標、恐懼貪婪指數（內建自測）
├─ oi_tracker.py                    # 合約未平倉量（OI）追蹤，當「籌碼面」替代指標（純函式，內建自測）
├─ db.py                     # SQLite：訊號歷史 + 自動優化後的參數，跨重啟持續累積
├─ state.py                   # 行程內記憶體狀態（上一輪分析結果，REST 端點讀寫）
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
python -m trading_system.outcome_tracker  # 訊號結果模擬 + 失效原因判斷自測
python -m trading_system.strategy_tuner   # 自動優化門檻的判斷邏輯自測
python -m trading_system.ai_coach         # 辯論歷史驗證 + system prompt 組裝自測
python -m trading_system.position_sizing  # 倉位計算機公式自測
python -m trading_system.ranking          # 推薦強度榜四維度評分自測
python -m trading_system.market_pulse     # RSI / 山寨季代理指標自測
python -m trading_system.oi_tracker       # OI 變化判斷自測
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
| `RANKING_TOP_N` | 5 | 📊 推薦強度榜做多/做空各顯示前幾名 |

## 📋 全部商品總覽 vs. 自動篩選監控

`TOP_N`（預設 6）只決定「自動」做完整技術分析（EMA/突破/停損停利/OI/新聞）的商品數量，
**不是**畫面上看得到的商品數量上限。每次分析都會把 OKX 回傳的**全部**合約（通常
200~300+ 檔，含 `EXTRA_INSTRUMENT_KEYWORDS` 額外納入的品項）解析出基本報價（代號/
價格/24h振幅/成交額），列在「當沖訊號」分頁下方的「📋 全部商品總覽」表格，可以篩選
分類、搜尋代號——這份清單完全重複利用同一次 `fetch_swap_tickers()` 呼叫的資料，
**零額外 API 成本**。

想深入研究某一檔沒被自動選中的商品，點該列的「🔍 分析」——會呼叫
`POST /api/v1/analyze-instrument`，只對這一檔多打一次 K 線＋OI＋新聞搜尋，AI 呼叫也
只涵蓋這一檔（不是重新分析整個市場），跟自動篩選出的商品走同一套計算邏輯
（`background.analyze_one_instrument`），結果一樣會記錄進訊號歷史、參與勝率追蹤，
不會有「自動選的」跟「自己點的」兩套不同標準。分析結果會直接併入上方的訊號面板。

## API

| 端點 | 方法 | 說明 |
|---|---|---|
| `/api/v1/dashboard` | GET | 讀取「上一次」分析結果的快取，不觸發新分析、不打任何外部 API |
| `/api/v1/analyze` | POST | 觸發一輪全新分析（OKX 篩選＋K線＋AI 新聞情緒），跑完回傳結果；上一輪還沒跑完時回 `409` |
| `/api/v1/analyze-instrument` | POST | 🔍 對「全部商品總覽」裡任一檔按需求做完整分析。body：`{"inst_id": "ETH-USDT-SWAP"}`，只針對這一檔多打一次資料（不重新分析全部商品），結果會併入 `signals`。商品不存在（還沒按過 `/analyze` 抓清單，或代號打錯）回 `404` |
| `/api/v1/health` | GET | 存活檢查 + 上次更新時間 + 上次錯誤訊息 |
| `/api/v1/config` | GET | 給「知識宇宙」分頁的 Supabase URL／anon key（公開金鑰，非機密） |
| `/api/v1/coach` | POST | AI 辯論空間一輪對話。body：`{"node": {...知識卡}, "history": [{"role","content"}, ...]}`，回傳 `{"reply", "error"}` |
| `/api/v1/position-size` | POST | 🧮 倉位計算機，純本地計算、零外部 API 成本。body：`{"account_balance","risk_pct","entry_price","stop_loss_price","leverage_cap"?,"take_profit_1"?,"take_profit_2"?}` |

`/api/v1/dashboard`、`/api/v1/analyze` 的回傳現在還多了 `market_pulse`（市場情緒儀表板資料）
跟 `ranking`（推薦強度榜資料），見下一節。

## 🧮 倉位計算機、📊 推薦強度榜、🌡️ 市場情緒儀表板

三個新功能，靈感來自使用者提供的市場數據 App 截圖參考（DATAHUNTER 等）。刻意只用系統
本來就有、零額外 AI 成本的資料算出來，**不生造假的籌碼/基本面數字**，也**不做真正的鏈上
大戶錢包監控**（見下方「誠實範圍說明」）。

**🧮 倉位計算機**：帳戶資金 × 單筆風險% ÷ │進場價 − 停損價│ ＝ 建議部位大小，公式只寫一份
在 `position_sizing.py`（`POST /api/v1/position-size`），前端 debounce 300ms 即時試算，
也可以直接點任一訊號卡片的「🧮 用此訊號試算倉位」按鈕帶入該訊號的進場/停損/停利價。純
本地計算，不打任何外部 API，隨便試算都不會有用量疑慮。

**📊 推薦強度榜**：把每檔有方向的訊號拆成四個維度、各 0~100 分（`ranking.py`）：
- **技術面**：突破盒子的幅度 + 站上/跌破 20 EMA 的動能距離。
- **籌碼面**：合約市場未平倉量（OI）變化幅度，見下方 OI 追蹤說明。
- **情緒面**：AI 新聞情緒是否跟這個方向共振（跟 `brain.fuse()` 同一套判斷）。
- **量能面**：24h 成交額／振幅超過篩選門檻多少。

四個維度加權平均成總分，做多/做空各自依總分排序，`RANKING_TOP_N`（預設 5）可在 `.env` 調整。

**🌡️ 市場情緒儀表板**：
- **市場平均 RSI**：重複利用本輪已經抓好的 K 線算 Wilder's RSI，逐檔算完取平均，零額外 API 呼叫。
- **恐懼貪婪指數**：打 [alternative.me](https://alternative.me/crypto/fear-and-greed-index/) 的免費公開 API（不需金鑰），失敗會優雅降級顯示「無法取得」，不影響其他訊號。
- **山寨季代理指標**：見下方誠實範圍說明。

### ⚠️ 誠實範圍說明：這不是真正的鏈上大戶錢包監控

使用者參考的截圖裡有「大戶錢包監控」「巨鯨雷達」等功能，那是在追蹤特定錢包地址的鏈上資金
流向，需要額外的鏈上資料商（例如 Nansen／Arkham／Etherscan Pro），目前**沒有**接、也不在
免費公開 API 範圍內。這裡做的「籌碼面」維度跟 OI 儀表板，用的是 OKX 公開的合約未平倉量
（`oi_tracker.py`，`GET /api/v5/public/open-interest`）——OI 在價格持平時大幅變化，代表
有大額資金正在建倉/平倉（不論多空），是業界常見、對散戶也公開透明的替代解讀方式，但終究
是「合約未平倉量」，不是「錢包持倉」，兩者不能劃上等號。每次分析會把當下 OI 存進 SQLite
（`db.py` 的 `oi_snapshot` 表）當下次比較的基準，第一次看到某檔商品沒有基準值時如實顯示
「尚無基準值」，不會亂猜方向。

山寨季代理指標同理：業界常見定義（如 blockchaincenter.net）是「前 50 大幣種過去 90 天漲幅
贏過 BTC 的比例 > 75%」，這裡沒有另外接那個資料源，而是直接用本系統當下監控的商品清單
（`TOP_N`，預設 6 檔），在**同一段 K 線窗口**跟 BTC 比報酬率——樣本數少、窗口遠短於 90 天，
只能當「短線氛圍」的粗略參考，畫面上會清楚標註這個差異，不會包裝成正式指數。

## AI 辯論空間

「知識宇宙」分頁的每張知識卡詳情彈窗下半部，可以針對這張卡的內容跟 AI 多輪來回辯論——
不是單次問答，AI 扮演一個「有觀點、但講得通就會被說服」的教練角色：你的論點有道理會明確
承認，有邏輯漏洞或跟核心原理矛盾會指出來。

**無狀態設計**：前端在瀏覽器分頁的記憶體裡保存這輪對話歷史（`debateHistory` 陣列），每次
送出都把完整歷史一起傳給 `/api/v1/coach`，後端不存任何東西、也不寫進 Supabase 的
`ai_coach_sessions` 表——那張表的 RLS policy 要求 `auth.uid()` 對得上 `user_id`，這個專案
還沒接使用者登入，匿名呼叫本來就寫不進去（見 `knowledge_universe/README.md`）。重新整理
頁面、關掉彈窗再打開同一張卡，對話就會清空重來。

**用量控制**：單輪辯論上限 16 則訊息（`ai_coach.MAX_HISTORY_MESSAGES`，8 個來回）——每辯論
一次都要把整段歷史重新送給 AI，愈辯論愈長、這一次呼叫的 token 成本愈高，設上限強制「這輪
該收斂了」，畫面上會提示改按「重新開始」，不會無限累積燒 token。跟 AI 新聞情緒一樣，沒設定
`ANTHROPIC_API_KEY`（或 `AI_PROVIDER=none`）時會顯示明確提示訊息，不會讓頁面壞掉。

## 訊號結果追蹤與自動優化（零 AI 成本）

每次按「立即分析」，`background._resolve_open_signals` 會先回頭檢查之前產生、還沒結算的
訊號：抓該商品訊號產生「之後」的已收盤 K 線（`RESOLUTION_LOOKBACK_CANDLES`，預設 300 根、
約 25 小時），純規則模擬先中停利還是停損（`outcome_tracker.simulate_resolution`）——只是
多打幾次免費的 OKX K 線查詢，**不呼叫任何 AI**，符合「基本分析不要每次大量消耗用量」的
設計目標。同一根 K 線內同時觸及停損與停利時，保守判定為停損（避免高估勝率）；TP1 達成後
視為已經「成功」（模擬有先減碼的心態），之後就算拉回跌破停損也不會倒扣。追蹤超過
`SIGNAL_EXPIRE_HOURS`（預設 25 小時）還沒有結果，標記為「逾期」，不再無限期追蹤——當沖
訊號本來就不該留倉過夜。

觸及停損時，`outcome_tracker.classify_failure_reason` 用純規則判斷可能的失效原因（一樣
零 AI 成本）：突破後 1~2 根 K 線內就反轉（疑似插針假突破）、盤整盒子過窄（雜訊容易觸發
停損）、進場當下離 20 EMA 太近（趨勢過濾條件邊緣）——找不到明顯弱點就老實說「可能是短期
雜訊或市場氣氛轉變，不代表策略邏輯有誤」，不會硬掰一個聽起來很專業但沒根據的理由。

累積 `strategy_tuner.MIN_SAMPLES`（預設 10）筆以上已驗證訊號後，如果勝率低於
`LOW_WATERMARK_PCT`（預設 40%），自動把 `MIN_AMPLITUDE_PCT` 調高 `STEP`（預設 0.5，上限
`MAX_AMPLITUDE_PCT` 8.0），篩掉波動較弱、雜訊較多的商品。**不是黑箱**：每次調整都會在畫面
上顯示明確的理由（近幾筆勝率多少、從多少調到多少）；也不會對同一批舊資料重複調整——只有
自從上次調整後有新的訊號結算，才會再評估一次。調整後的門檻存在 SQLite（`db.py`），跨重啟
持續生效，不會每次重開伺服器就跑回預設值。想手動重置，刪除 `data/trading_system.db` 裡
`strategy_params` 表對應的那一列即可（或直接刪掉整個檔案，重新累積歷史）。

歷史資料存在 `data/trading_system.db`（跟 `backend/` 共用 repo 根目錄的 `data/` 資料夾，
已在 `.gitignore` 排除）——這是本地檔案，純粹讓「訊號有沒有用」這件事跨重啟持續累積，
不會傳到任何外部服務。

## 訊號邏輯

**技術面**（`strategy.py`）：跟 20 EMA 的相對位置決定只做多或只做空；最近 `BOX_LOOKBACK`
根已收盤 K 線的高低點框出「盤整盒子」；當前這根**已收盤**（非正在走的那根，避免插針假突破——
見 `okx_client.fetch_confirmed_candles` 的說明）K 線實體突破盒子且同向站上/跌破 EMA 才觸發訊號。
停損固定設在盒子中線；停利用風報比算：risk = │進場價 − 停損價│，TP1 = 進場價 ± risk × `TP1_RR`
（預設 1.5，可先減碼）、TP2 = 進場價 ± risk × `TP2_RR`（預設 2.0，留給趨勢延續的部位）。

**AI 新聞情緒**（`news_client.py`）：分兩層。整體市場情緒抓 CoinDesk／CoinTelegraph 公開 RSS
頭條判斷；**每一檔實際被監控的商品另外各自查一次 Google News RSS**（免費公開、不需金鑰），
讓「大腦研判」的新聞脈絡真的對到那一檔商品，而不是不管哪一檔訊號都套用同一份籠統的市場
情緒——一檔比特幣訊號跟一檔完全不相干的小幣訊號，過去會顯示一模一樣的新聞理由，這是不準確
的，現在會分開判讀。**兩層判讀塞在同一次 AI 呼叫裡問完**（`get_market_and_instrument_sentiment`），
不管監控幾檔商品，一次分析永遠只燒一次 AI token；查不到某檔的專屬新聞，畫面上會老實顯示
「沒有找到該標的專屬新聞，套用整體市場情緒」，不會假裝有資料。新聞抓取沒有任何時間快取，
每次「立即分析」都重新抓最新的——手動觸發本身就已經是節流，資料本來就是即時的。

**多空共振**（`brain.py`）：技術面訊號跟該檔的 AI 新聞情緒同向 → 標記「強烈做多/做空」；技術面
突破但該檔新聞情緒明確反向 → 標記「潛在假突破，觀望」並不建議進場；該檔新聞中性或 AI 未啟用
→ 顯示純技術面訊號。

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
