# 投資理財知識宇宙（Investment Knowledge Universe）

遊戲化的交易/投資知識學習平台——知識卡以視覺化知識圖呈現、搭配等級/XP/任務解鎖機制與
AI 教練問答。目前狀態：**資料庫 schema 與第一批種子內容已部署完成，前端尚未開發**。

跟 repo 裡的 `backend/`（節流晨報）與 `trading_system/`（當沖訊號大腦）是三個完全獨立的
專案，互不依賴、互不影響。

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
├─ schema.sql               # 完整資料庫結構（已部署，來源見上）
├─ seed_knowledge_nodes.sql  # 第一批 17 張原創知識卡 + 8 條關聯 + 5 個任務（已部署）
├─ .env.example               # SUPABASE_URL / SUPABASE_ANON_KEY 範本，供之後的前端使用
└─ README.md
```

## 已部署的種子內容

17 張知識卡，橫跨 schema 定義的 5 個分類：

| 分類 | 卡片 |
|---|---|
| 技術面 (technical) | 均線與趨勢判斷、盤整區間與突破交易、裸K/Price Action、中樞與背馳（結構分析）、多週期分析 |
| 基本面 (fundamental) | 財報三表基礎、護城河與競爭優勢、成長股選股框架、指數化投資與持續買進 |
| 籌碼面 (chips) | 三大法人籌碼觀察、融資融券與借券、股權分散表與大戶動向 |
| 情緒面 (sentiment) | 恐懼貪婪與逆勢思維、交易心理與紀律、黑天鵝與尾部風險 |
| 總經面 (macro) | 常用總經領先/落後指標、利率循環與資產價格 |

多數卡片 `level_requirement=1`、`unlock_status='available'`（一開始就能看）；少數較進階的
（中樞背馳、成長股選股框架、融資融券、黑天鵝、利率循環）設成 `level_requirement=2`、
`unlock_status='locked'`，用來實際體現 schema 設計的等級解鎖機制——這幾張要等前端做出
升級邏輯後才會真的解鎖，目前用 SQL 直接查還是看得到內容。

8 條 `knowledge_edges` 把幾張卡連成初步的知識脈絡（例如「均線判斷方向」→「盒子突破找進場
時機」→「有訊號後紀律決定能不能執行」），5 個 `missions` 對應到其中 5 張卡片。

## 還沒做的事（Next Steps）

這次只完成了資料層，以下都還沒動工：

1. **前端**：知識圖視覺化（`position_x`/`position_y` 已經給好座標，可以直接拿來畫節點
   位置）、等級/XP/任務解鎖 UI、交易日記介面。
2. **AI 教練**（`ai_coach_sessions`）：需要接 LLM API（可以參考 `trading_system/news_client.py`
   接 Anthropic Claude API 的寫法），把使用者提問、選中的知識卡、AI 回答、弱點分析都寫進這張表。
3. **使用者系統**：schema 已經預留 `auth.users` 關聯與 RLS policy，但還沒有實際串接
   Supabase Auth 的登入流程。
4. **更多知識卡**：目前 17 張只涵蓋 Drive 書單所代表概念的一小部分，之後要擴充一樣要走
   「原創改寫、不摘錄」的方針。
5. **`dingyao-tw` 的 RLS 缺口**：獨立於這個知識平台之外，但仍然是待處理的安全問題，
   需要你自己確認那個專案的用途與存取設計。
