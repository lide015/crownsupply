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

## 深度金融知識延伸內容來源（第三批卡片）

第三批 9 張卡片（`fund_dcf_basics` 等，見下方檔案列表）聚焦專業股票研究方法論——估值
三方法交叉驗證、財報 beat 品質判讀、選股篩選邏輯、催化劑思維、風險分類、TAM 市場規模
迷思。這批卡片的方法論架構，參考了 Anthropic 公開釋出、Apache 2.0 授權的
[`github.com/anthropics/financial-services`](https://github.com/anthropics/financial-services)
專案裡股票研究相關 skill 文件所描述的分析框架。

需要說明兩點：
1. **這不是那個產品本身**。「Claude for Financial Services」是企業級付費服務，串接
   Daloopa、FactSet、S&P Global 等付費資料源；`financial-services` 這個 GitHub repo 是
   Anthropic 另外公開釋出、跟付費資料源脫鉤的方法論文件，本專案用的是這個公開 repo，
   沒有、也無法整合前者的企業付費功能。
2. **延續同一套版權方針**：DCF、WACC、可比公司分析、選股篩選這些是金融教科書等級的
   通用方法論，本身廣為人知、不是特定文本的表達方式；即使來源 repo 是 Apache 2.0（比
   單純「概念公開」更進一步、明確允許重製與衍生），這裡的文字仍然是重新用自己的話撰寫
   （案例、行文全部原創），沒有照抄任何原始 SKILL.md 檔案的段落。

## 交叉運用 Google Drive 電子書庫的延伸內容（第五批卡片）

第五批 7 張卡片（`tech_livermore_pyramid`、`tech_vcp_stage_analysis`、`tech_grid_trading`、
`tech_partial_exit_trailing_stop`、`macro_bear_market_phases`、`sentiment_kostolany_egg`、
`sentiment_kelly_criterion_risk_of_ruin`）的靈感來源，是「這是什麼、從哪裡來的」那節提到的
Google Drive 電子書庫本身——由 Claude（分析師 agent）逐本嘗試讀取書籍內容，只取「這本書
代表哪個廣為人知、公開流通的交易方法論名稱」當方向線索，內容全部改用自己的話重新寫成
教學卡片，沒有摘錄、改寫或翻譯書中任何段落，延續上面「不摘錄任何書籍原文」的方針。

實務上遇到的情況值得記錄：多本 PDF 是掃描件、Google Drive 的文字擷取工具讀不到文字層
（只讀到空白頁碼佔位符，或被廣告網站的浮水印文字覆蓋整個文件），這種情況下完全依賴既有的
公開知識撰寫，每張卡片對應的實作紀錄裡都誠實標註了這次讀取的信心程度；少數幾本（網格交易、
熊市啟示錄）讀到了實質的書籍文字（目錄、序言、部分正文），但也只拿來核對方向是否正確，
不是逐句引用的來源。

這批補的是先前完全空白的「部位/風險管理」角度（凱利公式/破產風險、分批出場紀律——後者
直接對應 `trading_system` 倉位計算機新增的「凱利公式建議」功能，見 `trading_system/README.md`），
以及技術面裡幾個先前沒收錄的具體交易方法（金字塔加碼、VCP波動收縮、網格交易），macro/
sentiment 各補一張跟既有卡片互補但角度不同的（熊市歷史階段、科斯托蘭尼雞蛋理論）。

## 呼應六階段框架的延伸內容（第六批卡片，⚠️ 已撰寫、尚未部署）

第六批 8 張卡片不是延續 Google Drive 書單，而是回應 `trading_system` 那邊「系統圍繞六階段
框架執行與開發」之後浮現的明確缺口：那邊這幾輪陸續補上了資金費率
（`trading_system/funding_rate.py`）、失效條件、波動風控關卡這幾個加密貨幣/當沖特有的
概念，但知識宇宙裡完全沒有對應的知識卡能讓使用者理解「這個數字/這道關卡背後代表什麼」；
順便補了幾個既有五批裡明顯缺席、但廣為人知的通用概念：

- `chips_funding_rate_longshort`（資金費率與多空比）——對應 `funding_rate.py`
- `fund_tokenomics_basics`（代幣經濟學）——加密貨幣沒有財報時的基本面替代品
- `tech_atr_volatility_stops`（ATR與波動度停損）——對應波動風控關卡背後的量化邏輯
- `tech_fibonacci_retracement`（費波那契回撤）——技術面通用工具，先前五批缺席
- `sentiment_sunk_cost_fallacy`（沉沒成本謬誤）——對應停損/失效條件背後的心理阻力
- `sentiment_anchoring_bias`（錨定效應）——行為金融學通用偏誤，先前五批缺席
- `macro_vix_fear_index`（VIX恐慌指數）——總經面通用概念，先前五批缺席
- `chips_etf_fund_flow`（ETF資金流向）——機構籌碼觀察的另一個窗口

內容一樣全部原創撰寫，寫的是概念本身，延續「不摘錄任何書籍原文」的方針。

**⚠️ 誠實揭露：這批目前只存在 `seed_knowledge_nodes_6.sql` 這個檔案裡，還沒有實際寫進
Supabase 資料庫**——跟前五批不同，這批的部署被這個工作階段的工具權限擋下來了：
`mcp__Supabase__execute_sql`／`apply_migration` 兩個能寫入資料庫的工具都回傳「需要
使用者核准」，但這個階段沒有互動式核准管道能完成這個授權流程，重試多次結果一樣。SQL
本身已經過結構驗證（引號/括號配對、跟既有 60 張卡片的 ID 不衝突、`position_x`/
`position_y` 不重疊、`knowledge_edges`/`missions` 引用的 `node_id` 全部存在），語法上
可以安全執行，只是差「有寫入權限的人跑一次」這一步——你可以自己把
`seed_knowledge_nodes_6.sql` 貼進 Supabase Dashboard 的 SQL Editor 執行，或之後在有
互動核准管道的階段裡請我直接跑。部署前，下方「累計 52 張知識卡」表格跟卡片總數**都還
沒反映這批**，避免文件講的跟資料庫實際內容對不上。

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
├─ seed_knowledge_nodes_3.sql    # 第三批 9 張原創知識卡 + 11 條關聯 + 3 個任務（已部署，見下方來源說明）
├─ seed_knowledge_nodes_4.sql    # 第四批 6 張原創知識卡 + 7 條關聯 + 2 個任務（已部署，補強籌碼/總經/情緒面）
├─ seed_knowledge_nodes_5.sql    # 第五批 7 張原創知識卡 + 9 條關聯 + 2 個任務（已部署，見上方來源說明）
├─ seed_knowledge_nodes_6.sql    # 第六批 8 張原創知識卡 + 14 條關聯 + 3 個任務（⚠️ 已撰寫、尚未部署，見上方說明）
├─ .env.example                   # SUPABASE_URL / SUPABASE_ANON_KEY 範本，供之後的前端使用
└─ README.md
```

## 已部署的種子內容

累計 **52 張知識卡**，橫跨 schema 定義的 5 個分類：

| 分類 | 卡片 |
|---|---|
| 技術面 (technical) | 均線與趨勢判斷、盤整區間與突破交易、裸K/Price Action、中樞與背馳、多週期分析、RSI/MACD 震盪指標、布林通道、支撐與壓力位、李佛摩式金字塔加碼法、階段分析與VCP波動收縮型態、網格交易策略、部分停利＋移動停損的分批出場紀律 |
| 基本面 (fundamental) | 財報三表基礎、護城河與競爭優勢、成長股選股框架、指數化投資、估值倍數、盈餘品質與現金流量、股息投資與殖利率、DCF現金流折現核心邏輯、終值陷阱、估值三隻腳交叉驗證、財報beat品質、財測guidance判讀、四種選股篩選邏輯、催化劑驅動的投資論點、四類風險分類、TAM市場規模迷思 |
| 籌碼面 (chips) | 三大法人籌碼觀察、融資融券與借券、股權分散表與大戶動向、選擇權 Put/Call 比率、期貨未平倉量、穩定幣供給與資金動能、鏈上大戶錢包監控的機會與侷限、山寨季與資金輪動 |
| 情緒面 (sentiment) | 恐懼貪婪與逆勢思維、交易心理與紀律、黑天鵝與尾部風險、FOMO 與損失趨避、群眾心理與從眾效應、確認偏誤、敘事驅動的市場週期、科斯托蘭尼雞蛋理論、破產風險與凱利公式 |
| 總經面 (macro) | 常用總經領先/落後指標、利率循環與資產價格、通膨與 CPI、殖利率曲線與衰退訊號、美元指數與風險性資產連動、景氣循環階段與資產配置、熊市階段循環與歷史底部模式 |

多數卡片 `level_requirement=1`、`unlock_status='available'`（一開始就能看）；較進階的十八張
設成 `level_requirement=2`、`unlock_status='locked'`，體現 schema 設計的等級解鎖機制——
目前前端沒有真的登入/等級判斷（見 Next Steps），鎖頭只是畫面上的示意，內容仍點得開。

47 條 `knowledge_edges` 把知識卡連成脈絡（例如「均線判斷方向」→「盒子突破找進場時機」→
「有訊號後紀律決定能不能執行」，或「DCF算出內在價值」→「終值陷阱是DCF最大弱點」→
「估值三隻腳交叉驗證，不能只信一種方法」，或「鏈上錢包監控的侷限」→「用未平倉量互補判讀」，
或「出場紀律」→「凱利公式」→「交易心理與紀律」這種部位/風險管理三張卡串起來的脈絡），
15 個 `missions` 對應到其中 15 張卡片。

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
2. **部署第六批知識卡**：`seed_knowledge_nodes_6.sql`（8 張，見上方「呼應六階段框架的
   延伸內容」一節）已經寫好並通過結構驗證，但這個工作階段拿不到 Supabase 寫入權限的
   核准，還沒實際執行進資料庫——把檔案內容貼進 Supabase Dashboard 的 SQL Editor 執行
   即可（或之後有互動核准管道的階段請我直接跑）。部署後記得回來更新這份 README 的
   「累計 52 張知識卡」表格跟卡片總數。
3. **更多知識卡**：即使部署完第六批，60 張仍只涵蓋 Drive 書單、股票研究方法論、
   六階段框架相關概念的一部分，之後要擴充一樣要走「原創改寫、不摘錄」的方針。
4. **`dingyao-tw` 的 RLS 缺口**：獨立於這個知識平台之外，但仍然是待處理的安全問題，
   需要你自己確認那個專案的用途與存取設計。
