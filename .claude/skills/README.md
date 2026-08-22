# 專案自訂 Skills

這裡的 2 個 skill，參考自 GitHub 上跟量化交易／回測相關、評價不錯的公開 skill 合集，
挑選跟這個 repo（`trading_system/` 當沖訊號系統）直接相關的方法論重新改寫，**不是**
照搬對方的程式碼或資料源——對方大多是泛用、多資產類別（美股/期貨/選擇權）的獨立
框架，這裡只借用其中跟這個 repo 自己的策略（20 EMA + 盤整盒子突破）跟資料來源
（OKX）真正對得上的思路。

| Skill | 出處 | 這輪有沒有拿來實際升級網站 |
|---|---|---|
| `backtest-strategy/SKILL.md` | [gauss314/skills](https://github.com/gauss314/skills)（MIT License）的 `backtesting` skill | ✅ 有——`trading_system/backtest.py` + `/api/v1/backtest` 端點 + 詳情頁「📊 執行歷史回測」按鈕，都是照這個 skill 的方法論實作的**真實新功能**，不是只放著參考 |
| `pre-trade-risk-gate/SKILL.md` | [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills)（MIT License）的 `pre-trade-discipline-gate` / `drawdown-circuit-breaker` | ⏳ 還沒——目前只整理成設計參考文件，記錄「這個 repo 已經有的手續費把關（`brain.py` 的 FEE TRAP）就是同一種模式」跟「還沒做、留給未來擴充」的兩個方向（每日虧損斷路器／進場前檢查清單），老實標註目前還沒有實際功能對應 |

兩份都特意**沒有**照抄來源 repo 裡跟這個系統無關的部分（美股 CANSLIM 選股、選擇權
策略、期貨保證金計算等）——那些原始合集裡有 60~90+ 個 skill，多數是美股/期貨/
選擇權情境，跟這個 repo 純粹追蹤 OKX 加密貨幣/股票代幣永續合約的當沖訊號系統關聯
不大，沒有整批拉進來。

用法：這兩份都是「設計方法論／原則」文件，不是可執行程式碼——修改
`trading_system/backtest.py` 或未來要幫 `brain.py` 加新的風控關卡時，先讀對應的
`SKILL.md` 對齊既有慣例（零未來函數、跟 `outcome_tracker` 同一套結算規則、純函式＋
自我測試等），比從零開始設計更不容易踩到這個 repo 已經踩過的坑。
