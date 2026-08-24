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

## 對照「25種主升浪啟動形態」型態圖鑑的延伸內容（第七批卡片，⚠️ 已撰寫、尚未部署）

第七批 7 張卡片的靈感來源是使用者分享的一套「25種主升浪啟動形態」型態圖鑑（社群教學
圖卡，非嚴謹學術文獻，圖卡本身也註明「僅供參考，不做為任何投資建議」）。跟這批同時，
`trading_system` 那邊也新增了 `pattern_recognition.py`（見
`trading_system/README.md`「🔍 型態辨識」一節），把其中 6 種能用純 OHLC 數字量化定義
的型態做成可回測驗證的偵測邏輯（純資訊揭露，不參與 `brain.fuse()` 的訊號融合）；這批
知識卡就是對應同一組型態的教學內容，讓使用者理解「系統偵測到的這個型態標籤代表什麼」：

- `tech_break_previous_high`（突破前高）——對應 `pattern_recognition.detect_break_previous_high`
- `tech_gap_breakout`（跳空缺口突破）——對應 `detect_gap_breakout`
- `tech_ma_squeeze_expansion`（均線黏合發散）——對應 `detect_ma_convergence_divergence`
- `tech_double_bottom_neckline`（W底頸線突破）——對應 `detect_double_bottom`
- `tech_triangle_wedge_flag`（三角收斂/旗形/楔形收斂型態家族）——對應 `detect_triangle_convergence`
- `tech_head_shoulders_bottom`（頭肩底）——圖鑑裡廣為人知的型態，但因為「形狀是否夠
  對稱」不容易用簡單規則可靠量化，`pattern_recognition.py` 刻意沒有做成程式偵測
  （詳見該模組說明），這裡純粹當教學內容收錄
- `tech_retest_support_hold`（回踩不破）——突破訊號的驗證概念，不是型態圖鑑列表裡的
  項目，但緊密相關，一併補上

型態圖鑑裡「杯柄突破／圓弧底起漲／漲停突破／突破籌碼密集區」這幾種，`pattern_recognition.py`
基於可靠度考量刻意不做成程式偵測（原因見 `trading_system/README.md`），這批知識卡
同樣沒有收錄，避免教學內容暗示系統其實有在幫忙判斷這些型態。內容全部原創撰寫，延續
「不摘錄任何書籍原文」的方針。

**⚠️ 誠實揭露：這批一樣只存在 `seed_knowledge_nodes_7.sql` 這個檔案裡，還沒有實際寫進
Supabase 資料庫**——原因跟第六批相同（這個工作階段的 Supabase 寫入工具權限被擋下來，
重試同樣結果一致）。SQL 已通過結構驗證（跟第六批合併計算共 67 張卡片的 id 不衝突、
`position_x`/`position_y` 不重疊、`knowledge_edges`/`missions` 引用全部存在）。部署
方式同上：把檔案內容貼進 Supabase Dashboard 的 SQL Editor 執行即可。

## 內容深度補丁：全部 67 張卡片都重寫加深（⚠️ 部分已撰寫、尚未部署）

使用者實際點開已部署的 `tech_naked_price_action`（第一批卡片）之後回饋內容太薄——
只有一段原理、一個案例、兩條常見錯誤，「皮毛都學不到」。這張卡原本的寫法其實是**這
七批全部卡片共用的格式**（單段原理＋單一案例＋2 條常見錯誤），問題不是只有這一張卡
有，是系統性的。先把這張卡重寫成明顯更深的版本當作品質基準，使用者確認之後，把同一
套深度標準套用到剩下全部 66 張卡片。

統一的深度標準（每張卡三個欄位都重寫，`id`/`title`/`category`/`level_requirement`/
`unlock_status`/`xp_reward`/`description`/`position_x`/`position_y`全部不動）：
- **原理**從一段話擴充成三到四段——這個概念到底是什麼、機制怎麼運作(比原本更具體)、
  至少一個「容易誤讀成 X，其實是 Y」的細節澄清、以及它在整個交易流程裡跟其他判斷
  的相對位置。
- **案例**從一個情境擴充成二到三個對照情境(帶具體數字/價位/百分比/時間週期)，展示
  同一個概念在不同脈絡下代表的意義可以完全不同——這是從裸K那張卡驗證過最有效的
  寫法；少數不適合硬湊三個情境的主題，改成一個更完整、帶真實數字的深度案例。
- **常見錯誤**從 2 條擴充成 4 條，新增的兩條要跟原本的不重複。

同步做了一個小前端改動：`principle`/`case_study` 這兩個欄位的內容現在有分段(用
換行分隔各段)，如果直接塞進原本的 `<p>` 標籤會被瀏覽器預設行為擠成一長串、看不出
段落——`trading_system/index.html` 的知識卡詳情彈窗幫這兩個欄位加上
`whitespace-pre-line` 這個 CSS class，讓換行符號能正常顯示成段落分隔，`static/tailwind.css`
也已經重新編譯進去這個新用到的 class。這個彈窗排版改動不影響其他既有卡片的顯示
（原本沒有換行符號的舊卡片內容，套用這個 CSS 屬性前後顯示效果完全一樣）。

**內容全部原創撰寫**，延續「不摘錄任何書籍原文」的方針——七批深化工作分別交給七個
獨立的寫手並行處理(各自只負責一個 `seed_knowledge_nodes*.sql` 檔案，互不重疊)，完成
後統一用腳本驗證過：67 張卡片的 `id`/`title`/`category`/`level_requirement`/
`unlock_status`/`xp_reward`/`position_x`/`position_y` 跟深化前逐一比對完全一致(只有
三個內容欄位變了)，SQL 引號配對與括號深度全部通過結構檢查，`knowledge_edges`/
`missions` 沒有被誤動。

**⚠️ 誠實揭露：部署狀態依批次不同，分兩種情況**：

- **第一到第五批（已經實際部署在 Supabase 裡）**：光改 `seed_knowledge_nodes*.sql`
  (已同步更新，保持「以後重建全新專案」時的一致性)不會讓現有資料庫內容變新——這幾批
  原本的 INSERT 語法沒有 `on conflict`，直接整批重跑會因為主鍵重複整批失敗。實際更新
  現有資料，需要另外執行對應的 UPDATE 補丁檔：`update_naked_price_action.sql`(第一批，
  裸K那一張，前一輪已經寫好)、`update_batch1.sql`(第一批其餘 16 張)、
  `update_batch2.sql`(第二批 13 張)、`update_batch3.sql`(第三批 9 張)、
  `update_batch4.sql`(第四批 6 張)、`update_batch5.sql`(第五批 7 張)。
- **第六、七批（還沒部署過）**：直接改 `seed_knowledge_nodes_6.sql`/
  `seed_knowledge_nodes_7.sql` 本身就是完整的修正，之後第一次部署時貼的就已經是加深
  版本，不需要額外的 UPDATE 補丁。

這個工作階段的 Supabase 寫入工具權限一樣被擋下來，所以不管是 UPDATE 補丁還是還沒
部署的 INSERT，都只能請使用者自己貼到 Supabase Dashboard 的 SQL Editor 執行。**部署
順序建議**：先貼五份 UPDATE 補丁(順序不影響彼此，互相獨立)，再貼第六批 INSERT，最後
貼第七批 INSERT(第七批的 edges 參照了第六批新增的節點 id)。

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
├─ seed_knowledge_nodes_6.sql    # 第六批 8 張原創知識卡 + 14 條關聯 + 3 個任務（⚠️ 已撰寫、尚未部署，內容已加深，見上方說明）
├─ seed_knowledge_nodes_7.sql    # 第七批 7 張原創知識卡 + 8 條關聯 + 2 個任務（⚠️ 已撰寫、尚未部署，內容已加深，見上方說明）
├─ update_naked_price_action.sql # 補丁：加深「裸K / Price Action 交易」單張卡片內容（⚠️ 已撰寫、尚未部署，見上方說明）
├─ update_batch1.sql             # 補丁：加深第一批其餘 16 張卡片內容（⚠️ 已撰寫、尚未部署，見上方說明）
├─ update_batch2.sql             # 補丁：加深第二批 13 張卡片內容（⚠️ 已撰寫、尚未部署，見上方說明）
├─ update_batch3.sql             # 補丁：加深第三批 9 張卡片內容（⚠️ 已撰寫、尚未部署，見上方說明）
├─ update_batch4.sql             # 補丁：加深第四批 6 張卡片內容（⚠️ 已撰寫、尚未部署，見上方說明）
├─ update_batch5.sql             # 補丁：加深第五批 7 張卡片內容（⚠️ 已撰寫、尚未部署，見上方說明）
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
2. **部署第六批＋第七批知識卡，以及五份內容深化 UPDATE 補丁**：`seed_knowledge_nodes_6.sql`
   （8 張，見上方「呼應六階段框架的延伸內容」一節）跟 `seed_knowledge_nodes_7.sql`（7 張，
   見上方「對照『25種主升浪啟動形態』型態圖鑑的延伸內容」一節）都已經寫好並通過結構驗證，
   內容也已經是加深過的版本；另外還有 `update_naked_price_action.sql` +
   `update_batch1.sql` ~ `update_batch5.sql` 六份補丁，把第一到第五批已部署卡片的內容
   同步更新成加深版本（見上方「內容深度補丁」一節）。這個工作階段拿不到 Supabase 寫入
   權限的核准，全部都還沒實際執行進資料庫——建議部署順序：先貼六份 UPDATE 補丁（互相
   獨立，順序不重要），再貼第六批 INSERT，最後貼第七批 INSERT（第七批有幾條
   `knowledge_edges` 連到第六批新增的卡片，必須在它之後）；或之後有互動核准管道的階段
   請我直接跑。部署後記得回來更新這份 README 的「累計 52 張知識卡」表格跟卡片總數（部署
   完六、七批後應該是 67 張）。
3. **更多知識卡**：即使部署完第六、七批，67 張仍只涵蓋 Drive 書單、股票研究方法論、
   六階段框架相關概念、型態圖鑑的一部分，之後要擴充一樣要走「原創改寫、不摘錄」的方針。
4. **`dingyao-tw` 的 RLS 缺口**：獨立於這個知識平台之外，但仍然是待處理的安全問題，
   需要你自己確認那個專案的用途與存取設計。
