# Crown Supply 專案 — 主備忘錄

> 建立日期：2026-05-11
> 用途：跨對話的單一真相來源 (single source of truth)。每次討論到新內容、新決策、新進度，都更新這份檔案。

---

## 1. 專案身份 (Identity)

- **專案代號**：crownsupply
- **形式**：靜態網站（HTML + CSS），部署在 Vercel
- **原始對話 session ID**：`local_c71a397a-a084-4fe6-aa85-987c1534c12b`
- **對話狀態**：已被 Archive（不是 Delete），UI 隱藏中但檔案完好
- **transcript 檔位置**：
  `C:\Users\sky10\AppData\Roaming\Claude\local-agent-mode-sessions\7274aecf-ae37-4d86-b701-7fb29616b786\8424b6de-788b-4dfe-9fb6-82ad4da4cc5f\local_c71a397a-a084-4fe6-aa85-987c1534c12b\.claude\projects\...\be26a499-371b-4db4-a7ee-c6d06f7bab88.jsonl`

## 2. 檔案清單 (Inventory) — 共 21 份

### HTML 頁面（17 份）
| 類別 | 檔名 |
|---|---|
| 主結構 | index.html / about.html / contact.html |
| 商品/服務 | products.html / services.html / industry-packs.html |
| 信任建立 | case-studies.html / partners.html / resources.html |
| 內容行銷 | notes.html / note-detail.html |
| 轉換漏斗 | checkout.html / thank-you.html |
| 標準頁 | privacy.html / terms.html / 404.html |

### 設定與資產（4 份）
- `styles.css` — 樣式
- `vercel.json` — 部署設定
- `.gitignore` — git 排除規則
- `README.md` — 專案說明

### 內容文件（1 份，重要）
- `10種AI線上產品模型對照表_完整內容.md` — **疑為商業策略核心**

## 3. 已確認資訊 (Confirmed Facts) — 2026-05-11 更新

### 商品 / 商業模式
- **品牌名**：CROWN SUPPLY（站名以全大寫 serif 字體呈現）
- **首賣商品**：「**AI 線上產品啟動筆記**」
- **定價**：NT$ 299（一次性付費、數位下載）
- **付款方式**：街口支付 (JKO Pay)
- **交付方式**：付款確認後 24 小時內寄送下載連結
- **退費政策**：「付款並寄送連結後即視為完成交付，**不接受退費**」（已寫進結帳同意條款）

### 線上資產
- **網址**：https://crownsupply.vercel.app
- **Threads**：https://www.threads.com/@_crownsupply_
- **官方 LINE（使用者口述）**：`@994erofm`
- **網站上顯示的 LINE**：`@crownsupply` ⚠️
- **客服 Email**：crownsupply0111@gmail.com

### 視覺風格
- 深藍/海軍藍底色（#0a1428 之類深色系）
- 白色 serif 字體 logo（CROWN SUPPLY 全大寫）
- 表單按鈕為淡灰白底深色字
- 整體調性：質感、安靜、精品

## 4. 待修問題清單 (Issue Tracker)

| 編號 | 問題 | 嚴重度 | 狀態 |
|---|---|---|---|
| #1 | 結帳頁「我已閱讀並同意」同意條款 **一字一行垂直排版** | 🔴 高（影響轉換） | 待修 |
| #2 | 網站 LINE (@crownsupply) 與口述官方 LINE (@994erofm) **不一致** | 🔴 高（影響營運） | 待確認 |
| #3 | 桌機版排版尚未檢查 | 🟡 中 | 待檢查 |
| #4 | 其他頁面排版尚未檢查（only 截圖了 checkout） | 🟡 中 | 待檢查 |

## 5. 已知未知 (Known Unknowns)

- [ ] 目標客群是？（猜測：想做副業 / AI 工具入門 / 數位產品創業者）
- [ ] 「10 種 AI 線上產品模型」具體是哪 10 種？
- [ ] 是否有後續產品線規劃？（299 元當引流商品 → 高單價課程？）
- [ ] 流量來源：Threads 為主嗎？有跑廣告嗎？
- [ ] 目前累積銷量？

## 6. 重要決策記錄 (Decision Log)

- 2026-05-11 — 建立此備忘錄作為跨對話記憶 — 因原對話被 Archive，避免訊息散佚
- 2026-05-11 — 從截圖確認商品、定價、結帳流程、聯絡方式 — 由使用者提供截圖
- 2026-05-11 — 確認 LINE @994erofm（連結 https://lin.ee/tJzrO05）為**唯一官方** — 網站上 @crownsupply 是錯的須移除
- 2026-05-11 — 抓取 styles.css + checkout.html + index.html 完整內容分析 bug
- 2026-05-11 — 用「防禦性 CSS + :has() + !important」修補 checkbox 排版 bug，產出 styles.css v2

## 7. 從原始 HTML 抓到的進階資訊

### 完整產品階梯
| 階 | 名稱 | 價格 | 定位 |
|---|---|---|---|
| 0 | 模型表 | NT$ 0 | Lead magnet 收名單 |
| 1 | AI 線上產品啟動筆記 | NT$ 299 | 驗證付費意願 |
| 2 | AI 線上產品完整模板包 | NT$ 1,999 | 中價深度款 |
| 2.5 | 啟動筆記+模板包合購 | NT$ 2,098 | 省 200 的 bundle |
| 3 | 雛形代做包 | NT$ 4,980-19,800 | 主要現金流 |
| 4 | 產業授權包 | NT$ 19,800/年起 | 給整個團隊用 |

### 內測階段付款流程（人工確認）
1. 選產品 → 選付款方式
2. 將來銀行轉帳（代碼 815，戶名張O得）或街口支付（代碼 396 / 帳號 909072775）
3. 回填付款後五碼
4. 24 小時內人工寄送下載連結

### 分潤合作
- 299 產品：50%
- 1999 包：40%
- 9800 服務：30%
- 團隊授權：客製

### 站點定位（提煉自首頁）
> "用 AI 做出你的第一個可販售線上產品"
> "整理 AI 工具、數位模板、線上產品模型與一人公司資源"
> "幫你用低成本做出第一個可測試、可上架、可成交的線上產品"
> "不講暴富，不碰違法，只拆解怎麼做、怎麼賣、風險在哪"

### 視覺/品牌語言關鍵字
- 一人公司
- AI 資源供應站
- 內測階段（誠實標註目前狀態，非常聰明）
- 「人工付款 / 人工確認」（透明度高、信任建立）

## 8. CSS Bug 修補技術筆記（給未來的自己）

### Bug：checkout 頁同意條款一字一行
**Root cause（推測，未實際 inspect DOM）：**
原 HTML 的 checkbox row 容器使用：
```css
display: flex;
justify-content: space-between;
```
但 `<label>` 沒設 `flex: 1`，瀏覽器將其壓到內容最小寬度 (min-content)。中文無空白 → 每字斷行。

**修法：用全站 styles.css 強制覆蓋（不必動 HTML）**
- `:has()` 選擇器抓出含 checkbox 的容器
- 強制 `display: flex` + `gap: 12px`（不用 space-between）
- label 強制 `flex: 1 1 auto` + `width: auto` + `white-space: normal`
- 用 `!important` 蓋過任何 inline style
- 多重 class 名稱（.checkbox-row, .agreement, .consent...）防禦性覆蓋

## 6. 學到的東西 / 教訓 (Lessons)

- **Archive ≠ Delete**：Claude 介面的 Archive 只是 UI 隱藏，硬碟上的對話 transcript 跟成果檔案都不會被動到。真正會永久消失的只有 Delete。
- **對話與成果是分開儲存的**：對話放在 `\.claude\projects\...jsonl`，成果放在 `\outputs\`。

---

## 更新規則 (Update Protocol)

每次我們討論完一個主題，我會：
1. 更新「3. 已知未知」→ 把問題改成已回答
2. 在「4. 待辦清單」加新的待決事項
3. 在「5. 決策記錄」記下做了什麼決定
4. 必要時在「6. 教訓」加新的觀念

這樣不管你過幾天回來、不管對話多長，打開這份檔案就能 30 秒內把脈絡重建起來。
