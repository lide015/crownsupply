---
name: Backtest Strategy
description: Use when adding, extending, or reviewing historical-backtest logic for this repo's trading strategy (trading_system/backtest.py) — how to replay strategy.py's rules over past OKX candles without look-ahead bias, and which risk/performance metrics (win rate, R-multiple, profit factor, max consecutive losses) to compute and why.
---

# Backtest Strategy（歷史回測方法論）

## 出處與授權

方法論精神參考 [gauss314/skills](https://github.com/gauss314/skills) 的
`skills/backtesting` skill（MIT License，Copyright the repo's contributors）。
**不是**照搬對方的程式碼或資料源——對方是一個泛用、多資產類別（股票/選擇權/外匯）的
獨立回測框架，這裡只借用它「Data → Research → Metrics → Validation」五階段方法論裡
最核心的「Metrics」思路，重新實作成專屬這個 repo 的版本：`trading_system/backtest.py`，
套用在**這個 repo 自己的策略**（`strategy.py` 的 20 EMA + 盤整盒子突破）跟**自己的
資料來源**（OKX 歷史 K 線，`okx_client.fetch_confirmed_candles`）上。

## 什麼時候用這個 skill

- 修改 `trading_system/backtest.py` 的重播邏輯或統計指標。
- 幫這個策略新增/調整回測相關功能（例如新增一種績效指標、支援多商品批次回測、
  把回測結果存進資料庫做歷史比較）。
- 審查任何「用歷史資料驗證策略」的程式碼改動，檢查有沒有犯 look-ahead bias。

## 核心原則（不可妥協）

1. **零未來函數（no look-ahead bias）**：在歷史上的時間點 i 算訊號時，只能把
   `candles[:i+1]`（也就是「當時」已經收盤、還看不到後面走勢的 K 線）餵給
   `strategy.compute_signal()`。訊號觸發後，才用「當時之後」的 K 線
   （`candles[i+1:]`）去模擬結果。任何一個版本如果讓訊號生成邏輯看到了「未來」的
   K 線，這個回測數字就是假的、毫無參考價值——這是這個 skill 最重要的紅線。

2. **跟線上即時追蹤用同一套結算規則**：`backtest.py` 呼叫
   `outcome_tracker.simulate_resolution()`，而不是自己重新發明一套「怎麼判斷停損/
   停利先到」的邏輯。這樣回測出來的勝率，才跟使用者平常在網頁上看到的「訊號結果
   追蹤」勝率是同一套算法算出來的，可以互相對照，不是兩套標準各說各話。

3. **不確定的交易不計入統計**：訊號觸發後，如果資料在停損/停利任一個先到之前就
   用完了（`simulate_resolution` 回傳 `resolution=None`），代表這筆交易在歷史上
   當時「還沒走完」，必須跳過、不計入勝率分母——不能因為手上沒有它的結果，就把它
   當成輸家或贏家瞎猜一個結果進去，那樣會讓統計失真。

4. **一段走勢只算一筆交易，不重疊計算**：一筆交易結算之後，重播位置要跳到
   `bars_to_resolution` 之後（`i += max(bars, 1)`），而不是逐根往前挪一格——否則
   同一段突破走勢，會因為停損/停利還沒觸及前的每一根 K 線都被誤判成「新訊號」，
   同一筆交易被灌水算成好幾筆重疊的交易，勝率/次數都會失真膨脹。

## 指標選擇（為什麼是這幾個）

- **勝率（win rate）**：最直覺的指標，但單獨看容易誤導（低勝率高賠率的策略也可能
  整體是正期望值）——一定要搭配平均 R 倍數／獲利因子一起看。
- **平均 R 倍數（avg R multiple）**：每筆交易的損益，用「進場到停損的風險距離」
  當作 1 個單位（1R）換算——這樣不同商品、不同停損距離的交易可以放在同一把尺上
  比較，不會因為某個商品波動比較大就顯得比較賺。
- **獲利因子（profit factor）＝總獲利 R 加總 ÷ 總虧損 R 加總**：>1 代表整體是正
  期望值。**完全沒有虧損交易時比值理論上是無限大——不要回傳 `Infinity`**（這既不是
  合法 JSON，也容易被誤解成「這套策略穩賺不賠」），應該回傳 `None`／`null`，讓前端
  老實顯示「尚無虧損交易，無法計算」。
- **最大連續虧損（max consecutive losses）**：規則式風控最實際的指標之一——就算
  長期期望值是正的，連續虧損拉得太長，使用者的心理跟資金曲線撐不住，半路就不會
  照規則執行下去了，這比「總勝率」更貼近「這套策略實際上執不執行得下去」。

## 這個 repo 特有的注意事項

- `backtest.py` 是**純函式模組**（跟 `strategy.py`、`outcome_tracker.py` 同一個
  慣例）：不碰網路、不碰資料庫，`candles` 一律由呼叫端（`app.py` 的
  `/api/v1/backtest` 端點）先用 `okx_client.fetch_confirmed_candles()` 抓好再傳
  進來。新增功能時維持這個切分，不要在 `backtest.py` 裡直接打 API。
- OKX `/market/candles` 單次呼叫上限 300 根（`config.BACKTEST_CANDLE_LIMIT`）。
  想要更長的回測時間跨度，使用者要自己選更長的 K 線週期（例如 1H 取代 5m），而不是
  加大 `limit`——那個值本身就不能超過 OKX 的硬限制。
- 每個新函式都要照這個 repo 的慣例，在檔案底部的 `if __name__ == "__main__":`
  區塊寫自我測試（見 `backtest.py` 現有的測試：資料不足、單筆獲利、單筆虧損、
  訊號觸發但資料用完不計入、完全沒有突破、混合勝負彙總邏輯）。
