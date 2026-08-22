# 專案自訂 Subagent

這裡的 5 個 agent 定義檔，選自使用者提供的 [`agency-agents`](https://github.com/msitarzewski/agency-agents)
（MIT 授權，作者 AgentLand Contributors，206 個 agent 人設的完整合集）。只挑了跟這個
repo（`trading_system/` 當沖訊號系統＋`knowledge_universe/` 知識宇宙）直接相關的 5 個，
不是照單全收——多數其他分類（design/marketing/game-development/spatial-computing 等）
跟這個專案關聯不大，沒有拉進來。

| 檔案 | 適合用在 |
|---|---|
| `finance-investment-researcher.md` | 深入研究單一標的的基本面（幫 knowledge_universe 寫新知識卡、或幫使用者查證某個投資論點時） |
| `finance-financial-analyst.md` | 財務模型/情境分析相關工作 |
| `engineering-ai-engineer.md` | 這個專案本身大量整合 AI（news_client.py 的新聞情緒、ai_coach.py 的辯論空間），改動這塊時可以參考 |
| `engineering-code-reviewer.md` | 對 trading_system/ 或 knowledge_universe/ 的改動做程式碼審查 |
| `engineering-backend-architect.md` | trading_system 的 FastAPI 後端架構調整時參考 |

用法：Agent 工具的 `subagent_type` 參數可以指定這裡任一個 agent 的 `name`（例如
"Code Reviewer"）來啟用對應人設；也可以直接把檔案內容當參考文件讀，照著裡面的框架/
checklist 自己做，不一定要透過 subagent 機制。

原始 LICENSE（MIT）保留在 `agency-agents-main/LICENSE`（沒有整個複製進 repo，只留這 5 個
檔案）；完整版權聲明：Copyright (c) 2025 AgentLand Contributors，授權條款見
https://github.com/msitarzewski/agency-agents/blob/main/LICENSE。
