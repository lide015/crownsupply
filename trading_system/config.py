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

# ---- AI 新聞情緒大腦（見 news_client.py） ----
# AI_PROVIDER: "anthropic" | "openai" | "none"（none = 完全停用 AI，訊號只看技術面）
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
# 新聞情緒每隔這麼久才重新呼叫一次 AI（省 token、避免前端每次輪詢都燒錢）
NEWS_REFRESH_SECONDS = int(os.getenv("NEWS_REFRESH_SECONDS", "600"))

# ---- 後端背景重新整理頻率（重算 OKX 篩選 + 技術訊號） ----
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "30"))
