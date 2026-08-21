"""環境設定：全部走環境變數（.env 或 shell export），不把金鑰寫死在程式碼裡。
複製 .env.example 為 .env 並填入你的金鑰；.env 已加進 .gitignore，不會被 commit。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 明確指向 trading_system/.env（不管執行時的工作目錄是 repo 根目錄還是 trading_system/
# 本身），這樣 `uvicorn trading_system.app:app` 跟直接在 trading_system/ 裡跑都吃得到。
load_dotenv(Path(__file__).resolve().parent / ".env")

# ---- OKX 商品篩選門檻（見 okx_client.screen_active_instruments） ----
MIN_VOL_USDT = float(os.getenv("MIN_VOL_USDT", "50000000"))       # 24h 成交額門檻（USDT）
MIN_AMPLITUDE_PCT = float(os.getenv("MIN_AMPLITUDE_PCT", "3.0"))  # 24h 振幅門檻（%）
TOP_N = int(os.getenv("TOP_N", "6"))                               # 精選監控幾檔
# OKX 主要提供加密貨幣永續合約（*-USDT-SWAP）。黃金/白銀等大宗商品目前僅在 OKX 少數帳戶/
# 地區以特殊指數合約形式存在，非標準商品，這裡保留關鍵字擴充點，預設不啟用。
EXTRA_INSTRUMENT_KEYWORDS = tuple(
    kw for kw in os.getenv("EXTRA_INSTRUMENT_KEYWORDS", "").split(",") if kw
)

# ---- 技術面策略參數（20 EMA + 盤整盒子突破，見 strategy.py） ----
EMA_PERIOD = int(os.getenv("EMA_PERIOD", "20"))
BOX_LOOKBACK = int(os.getenv("BOX_LOOKBACK", "15"))
CANDLE_BAR = os.getenv("CANDLE_BAR", "5m")
CANDLE_LIMIT = int(os.getenv("CANDLE_LIMIT", "50"))
# 停利以「風報比」(reward : risk) 算：risk = |進場價 - 停損價|。
# TP1 較近、可先減碼；TP2 較遠、留給趨勢延續的部位。
TP1_RR = float(os.getenv("TP1_RR", "1.5"))
TP2_RR = float(os.getenv("TP2_RR", "2.0"))

# ---- 知識宇宙前端用（見 knowledge_universe/README.md）----
# anon/publishable key 設計上就是給前端直接使用的公開金鑰，不是密鑰，預設值可以直接寫在這裡；
# 之後如果換了 Supabase 專案，改這兩個環境變數即可，不用動程式碼。
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://qirovvwpeblxgpobptlc.supabase.co")
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFpcm92dndwZWJseGdwb2JwdGxjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODczMTAzNzEsImV4cCI6MjEwMjg4NjM3MX0.bqGLdtDaRu_5lc-c5SOHWc7-p-oz8gunQ5YWkMTPAvk",
)

# ---- AI 新聞情緒大腦（見 news_client.py） ----
# AI_PROVIDER: "anthropic" | "openai" | "none"（none = 完全停用 AI，訊號只看技術面）
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
# 沒有背景排程、沒有自動輪詢——分析只在使用者按下「立即分析」時才觸發一輪，
# 用量由點擊次數決定，不需要額外的節流間隔設定。

# ---- 美股代幣公司基本面（見 stock_fundamentals.py） ----
# 免費申請：https://finnhub.io（免費方案額度足夠這種偶爾查詢的用法）。留空就不會顯示
# 美股代幣的公司基本面那塊，商品報價／技術分析／AI 新聞情緒等其他功能完全不受影響。
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# ---- 推薦強度榜（見 ranking.py） ----
RANKING_TOP_N = int(os.getenv("RANKING_TOP_N", "5"))  # 做多/做空各顯示前幾名

# ---- 訊號結果追蹤與自動優化（見 db.py / outcome_tracker.py / strategy_tuner.py） ----
# 每次分析時回頭檢查未結算訊號要抓多少根已收盤 K 線（OKX /market/candles 單次上限 300）
RESOLUTION_LOOKBACK_CANDLES = int(os.getenv("RESOLUTION_LOOKBACK_CANDLES", "300"))
# 訊號追蹤超過這麼久還沒結果就標記為「逾期」，不再無限期追蹤——當沖訊號本來就不該留倉過夜，
# 拖過這個時限代表已經失去「當沖」的參考意義。預設 25 小時（涵蓋隔一天再來看的情況）。
SIGNAL_EXPIRE_HOURS = float(os.getenv("SIGNAL_EXPIRE_HOURS", "25"))
