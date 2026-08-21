# 投資理財知識宇宙（Investment Knowledge Universe）

遊戲化的交易/投資知識學習平台——知識卡以視覺化知識圖呈現、搭配等級/XP/任務解鎖機制與
AI 辯論空間。目前狀態：**資料庫、前端（卡片＋知識圖兩種檢視）、AI 辯論都已完成並可用；
只有「使用者登入」還沒接（見下方 Next Steps），所以等級/XP/任務進度暫時不會被記錄**。

跟 repo 裡的 `backend/`（節流晨報）是完全獨立的專案。**前端已經整合進 `trading_system/`**
——同一個網站的「📚 知識宇宙」分頁（見 `trading_system/index.html`），不是另外的獨立頁面；
`trading_system/app.py` 的 `GET /api/v1/config` 把這裡的 Supabase URL／anon key 交給前端，
前端直接用瀏覽器 `fetch()` 打 Supabase PostgREST API 讀資料，沒有另外寫後端代理。

## 這是什麼、從哪裡來的

使用者的 Google Drive「LIDE」資料夾裡有 100 多本交易/投資相關電子書，以及一份
`investment-knowledge-universe-schema.sql`——一個已經設計好的遊戲化學習平台資料庫結構。
本次工作把這個 schema 實際部署到 Supabase，並填入第一批種子知識卡。

## ⚠️ 版權方針：不摘錄任何書籍原文

那份 Drive 資料夾裡有多本書的檔名直接寫著「Z-Library」「Z-lib-org」「77ebooks.com」——
這些是知名的電子書盜版來源。因此本專案的 `knowledge_nodes` 內容**一律是原創撰寫的概念
說明**，不從任何一本書擷取、複製或改寫原文段落。技術指標、選股框架、交易心理學這些概念
本身廣為人知、可公開討論（版權保護的是特定作者的表達方式，不是概念本身），但具體某本書
的行文、案例、原話不會被收錄進資料庫。

之後如果要擴充知識卡，請延續這個方針：用自己的話寫「這個概念是什麼、為什麼重要、常見的
錯誤用法」，不要貼書摘。

## Supabase 專案資訊

| 項目 | 值 |
|---|---|
| 專案名稱 | `investment-knowledge-universe` |
| 專案 ref | `qirovvwpeblxgpobptlc` |
| Region | `ap-northeast-1`（東京） |
| API URL | `https://qirovvwpeblxgpobptlc.supabase.co` |
| Anon/Publishable Key | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFpcm92dndwZWJseGdwb2JwdGxjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODczMTAzNzEsImV4cCI6MjEwMjg4NjM3MX0.bqGLdtDaRu_5lc-c5SOHWc7-p-oz8gunQ5YWkMTPAvk` |
| 費用 | 免費方案（$0/月） |

Anon/publishable key 設計上就是給前端直接使用的公開金鑰，不是密鑰，所以直接寫在這裡沒問題
（跟資料庫連線密碼、service role key 不一樣，那些才需要保密）。

**這是全新建立的專案**，跟帳號下另外兩個既有專案完全獨立：
- 不是 `dingyao-tw`（另一個已經在跑的台股籌碼＋AI辯論系統，34 張表 RLS 全部沒開，
  這件事還沒處理，需要你自己確認那個專案的存取設計後再決定怎麼補 policy）。
- 不是 `sky10152004@gmail.com's Project`（原本 crownsupply 電商/抽獎會員系統，RLS 已開，
  已經重新 pause 回閒置狀態，沒有寫入任何東西）。

## 檔案

```
knowledge_universe/
├─ schema.sql                  # 完整資料庫結構（已部署，來源見上）
├─ seed_knowledge_nodes.sql     # 第一批 17 張原創知識卡 + 8 條關聯 + 5 個任務（已部署）
├─ seed_knowledge_nodes_2.sql    # 第二批 13 張原創知識卡 + 12 條關聯 + 3 個任務（已部署）
├─ .env.example                   # SUPABASE_URL / SUPABASE_ANON_KEY 範本，供之後的前端使用
└─ README.md
```

## 已部署的種子內容

累計 **30 張知識卡**，橫跨 schema 定義的 5 個分類：

| 分類 | 卡片 |
|---|---|
| 技術面 (technical) | 均線與趨勢判斷、盤整區間與突破交易、裸K/Price Action、中樞與背馳、多週期分析、RSI/MACD 震盪指標、布林通道、支撐與壓力位 |
| 基本面 (fundamental) | 財報三表基礎、護城河與競爭優勢、成長股選股框架、指數化投資、估值倍數、盈餘品質與現金流量、股息投資與殖利率 |
| 籌碼面 (chips) | 三大法人籌碼觀察、融資融券與借券、股權分散表與大戶動向、選擇權 Put/Call 比率、期貨未平倉量 |
| 情緒面 (sentiment) | 恐懼貪婪與逆勢思維、交易心理與紀律、黑天鵝與尾部風險、FOMO 與損失趨避、群眾心理與從眾效應、確認偏誤 |
| 總經面 (macro) | 常用總經領先/落後指標、利率循環與資產價格、通膨與 CPI、殖利率曲線與衰退訊號 |

多數卡片 `level_requirement=1`、`unlock_status='available'`（一開始就能看）；較進階的十張
設成 `level_requirement=2`、`unlock_status='locked'`，體現 schema 設計的等級解鎖機制——
目前前端沒有真的登入/等級判斷（見 Next Steps），鎖頭只是畫面上的示意，內容仍點得開。

20 條 `knowledge_edges` 把知識卡連成脈絡（例如「均線判斷方向」→「盒子突破找進場時機」→
「有訊號後紀律決定能不能執行」），8 個 `missions` 對應到其中 8 張卡片。

## 已完成的前端（在 `trading_system/index.html` 裡）

- **兩種檢視**：🗂️ 卡片格狀列表，或 🗺️ 知識地圖（用 `position_x`/`position_y` 畫成 SVG
  節點+連線圖，`knowledge_edges` 畫成連線，依分類上色，點節點一樣開詳情彈窗）——右上角
  切換鈕即時互換，不用重新整理頁面。
- 分類篩選（全部/技術面/基本面/籌碼面/情緒面/總經面），兩種檢視都吃這個篩選。
- 詳情彈窗：核心原理、案例、常見錯誤、延伸概念（依 `knowledge_edges` 雙向找關聯卡）。
- **🥊 AI 辯論空間**（詳情彈窗下半部）：針對這張知識卡跟 AI 多輪來回辯論，不是單次問答——
  你的論點有道理 AI 會承認，講不通 AI 會指出問題在哪。無狀態設計：對話只存在瀏覽器分頁
  記憶體，重新整理就清空，不會寫進 `ai_coach_sessions`（那張表的 RLS 需要真正登入才能寫，
  見下方 Next Steps）。單輪辯論上限 16 則訊息（8 個來回），避免無限累積燒 AI token；
  後端邏輯在 `trading_system/ai_coach.py`，走跟 `news_client.py` 一樣的 Anthropic/OpenAI
  呼叫方式，沒金鑰時優雅顯示提示，不會讓頁面掛掉。
- 任務列表，每個任務可連回對應的知識卡。

用無頭瀏覽器完整驗證過（這個開發環境連不到 `supabase.co`，用假資料模擬 Supabase 回傳來測，
邏輯本身沒有網路依賴）：卡片/地圖檢視切換、篩選、彈窗、辯論送出成功與失敗兩種路徑（含
失敗時正確把使用者那則訊息退回、不留半截對話）、多輪對話正確累積歷史。實際 Supabase 資料
抓取跟真正呼叫 AI 金鑰，需要你在自己電腦上開瀏覽器測試才能完整確認——Supabase 的 REST API
已經用 MCP 工具直接查過資料庫確認資料存在、RLS policy 正確允許公開讀取，理論上沒問題。

## 還沒做的事（Next Steps）

1. **使用者系統**：schema 已經預留 `auth.users` 關聯與 RLS policy，但還沒有實際串接
   Supabase Auth 的登入流程，所以等級/XP/任務完成度、AI 辯論紀錄目前都不會真的被記錄下來。
   一個可以考慮、不用自己刻登入頁面的選項是 Supabase 的「匿名登入」（Anonymous Sign-ins）
   ——訪客一進站就自動拿到一個 `auth.uid()`，滿足現有 RLS policy，不需要任何登入表單；
   但那是 Dashboard 層級的 Auth Provider 設定，目前可用的 Supabase 工具查不到、也改不了，
   需要你自己到 Supabase Dashboard 開啟。
2. **更多知識卡**：30 張仍只涵蓋 Drive 書單所代表概念的一部分，之後要擴充一樣要走
   「原創改寫、不摘錄」的方針。
3. **`dingyao-tw` 的 RLS 缺口**：獨立於這個知識平台之外，但仍然是待處理的安全問題，
   需要你自己確認那個專案的用途與存取設計。
