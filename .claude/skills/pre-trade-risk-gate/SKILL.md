---
name: Pre-Trade Risk Gate
description: Reference this when extending brain.py's signal-fusion logic with additional discipline/risk gates (beyond the existing fee-trap check) — e.g. a daily-loss circuit breaker or a pre-entry checklist — so new gates follow the same "compute the number, attach a reason string, never silently drop info" pattern already established for the fee-trap gate.
---

# Pre-Trade Risk Gate（進場前風控關卡：設計參考）

## 出處與授權

概念參考 [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills)
（MIT License）裡的 `pre-trade-discipline-gate`（進場前檢查清單，攔截沒有計畫或部位
過大的進場）跟 `drawdown-circuit-breaker`（帳戶層級的虧損斷路器）兩個 skill 的核心
概念。**不是**照搬對方針對美股/期貨的具體規則（那兩個 skill 大量假設美股盤中時段、
帳戶保證金等跟這個 repo 無關的情境），是借用「在訊號產生之後、使用者真的進場之前，
再加一層跟技術面/新聞面無關的獨立把關」這個思路。

## 這個 repo 已經有的同類先例

`brain.py` 的手續費淨盈虧比把關（`fee_info`／`FEE_TRAP` 那段邏輯，見
`.claude/skills/backtest-strategy/SKILL.md` 引用的同一輪功能）已經是這個模式的
第一個實作：技術面 + 新聞面都共振、看起來應該進場，但淨盈虧比太薄或已經倒虧，一樣
會被攔截成警告，不建議進場。**任何新的風控關卡都應該照這個既有的模式走**，不要
另外發明一套機制：

1. 獨立算出一個具體的數字（不是模糊的「風險偏高」，是可以顯示給使用者看的實際
   數值——手續費把關算的是「淨盈虧比」，數字擺在那裡讓使用者自己判斷）。
2. 把這個數字當成 `brain.fuse()` 的一個額外參數傳進去（向下相容：預設 `None`，
   不影響沒有這項資料時的既有行為）。
3. 條件不成立時，回傳跟 `COLOR_YELLOW` 同一等級的警告（不是紅色/致命錯誤——這些
   關卡的本意是「提醒謹慎評估」，不是「系統故障」），並附上完整可讀的理由字串，
   讓使用者知道具體是哪個數字、哪個門檻不成立。
4. **絕對不要静默丟棄資訊**：就算最後判定「不建議進場」，原始的技術面訊號、新聞
   情緒判讀、淨盈虧比數字都還是要完整顯示在卡片上——攔截的是「建議動作」，不是
   「使用者看得到的資料」。

## 目前尚未實作、留給未來擴充的方向（不是這個 repo 已經有的功能）

- **每日虧損斷路器**：如果 `outcome_tracker` 追蹤到「今天」已經有連續 N 筆
  `hit_sl`，或者今天的已結算 R 倍數總和已經到了使用者自訂的虧損上限，之後的新訊號
  改標示「⚠️ 今日已達虧損上限，建議停止交易」，而不是照常顯示強烈做多/做空——
  這是「訊號本身沒問題，但『現在』不是進場的好時機」的另一種風控角度。
- **進場前檢查清單**：把「這筆訊號的停損停利有沒有設好、淨盈虧比划不划算、
  有沒有跟現有持倉重複」列成一個簡短的是/非清單，附在訊號卡片上，比純文字的
  「大腦研判」多一層可以逐項核對的結構。

實作任何一項之前，先讀 `backtest.py` 跟 `brain.py` 現有的模式與自我測試慣例
（`if __name__ == "__main__":` 區塊、純函式、向下相容的可選參數），新功能要維持
同樣的風格，不要另起爐灶。
