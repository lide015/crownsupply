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
# 量能突破確認：突破那根K線成交量要達到盒子回看窗平均量的這個倍數以上才算有效突破，
# 過濾量能稀薄的雜訊假突破。設 0 代表完全不啟用（維持舊行為）。
VOLUME_CONFIRM_MULTIPLE = float(os.getenv("VOLUME_CONFIRM_MULTIPLE", "1.1"))

# ---- 多時間週期共振（見 strategy.compute_trend_bias / brain.fuse 的 htf_trend） ----
# 5 分鐘線技術面突破時，另外抓一次更高週期的K線，確認大方向沒有明顯反向——逆著大趨勢
# 做的短線突破特別容易被雜訊洗出場。零額外AI成本，只是多一次免費的OKX K線查詢。
HTF_BAR = os.getenv("HTF_BAR", "1H")
HTF_EMA_PERIOD = int(os.getenv("HTF_EMA_PERIOD", "20"))
HTF_CANDLE_LIMIT = int(os.getenv("HTF_CANDLE_LIMIT", "50"))

# ---- 每日虧損斷路器（見 outcome_tracker.compute_daily_circuit_breaker） ----
# 今天已結算訊號觸及停損的次數達到這個數字，或今天累積R倍數低於 MAX_DAILY_LOSS_R，
# 之後的新訊號一律標示「今日已達虧損上限」，不管技術面/新聞面/淨盈虧比再好看都攔截。
# 任一項設成 0（次數）或 0 以上（R，門檻本身應該是負數）代表關閉那一項門檻。
MAX_DAILY_LOSS_COUNT = int(os.getenv("MAX_DAILY_LOSS_COUNT", "3"))
MAX_DAILY_LOSS_R = float(os.getenv("MAX_DAILY_LOSS_R", "-5.0"))

# ---- 歷史回測（見 backtest.py：把策略規則套在過去的 K 線上重播統計） ----
# OKX /market/candles 單次查詢上限 300 根；使用者可在前端選更短的 K 線週期（bar）
# 換取更長的實際回測時間跨度，但單次抓取根數本身受 OKX API 限制，不能無限加大。
BACKTEST_CANDLE_LIMIT = int(os.getenv("BACKTEST_CANDLE_LIMIT", "300"))

# ---- 當沖手續費（見 fee_calc.py：把風報比換算成扣掉來回手續費的「淨盈虧比」） ----
# OKX 永續合約一般用戶預設費率參考值（%）；如果你的帳號等級/回饋比率不同，改這裡即可。
# 當沖假設進出場都用市價單（Taker）搶時間，比只算 Maker 更保守，不會低估手續費成本。
TAKER_FEE_PCT = float(os.getenv("TAKER_FEE_PCT", "0.05"))
# 淨盈虧比（扣完來回手續費後）至少要達到這個倍數才算「值得進場」；沒有達到就算技術面
# 突破、新聞情緒也共振，一樣會被系統標示為「手續費侵蝕獲利」，提醒不要冒險進場。
MIN_NET_RR = float(os.getenv("MIN_NET_RR", "1.0"))

# ---- 訊號觸發通知（Telegram，見 telegram_notify.py） ----
# 建立方式：跟 Telegram 的 @BotFather 對話建立一個 Bot 拿到 Token；chat_id 最簡單的
# 取得方式是先跟這個 Bot 隨便說一句話，再打開瀏覽器連到
# https://api.telegram.org/bot<TOKEN>/getUpdates 查回應裡的 message.chat.id。
# 兩個都留空（預設）就完全停用，不影響任何其他功能，也不會嘗試發送任何請求。
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ---- 訊號觸發通知（Email，選用，見 email_notify.py） ----
# 用一般 SMTP 帳號寄信（Gmail 等服務通常要用「應用程式密碼」，不是登入密碼本身）。
# 5 個欄位（HOST/USERNAME/PASSWORD/FROM/TO）都留空就完全停用，不影響任何其他功能。
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

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

# ---- 背景排程自動分析（選用，預設關閉，見 scheduler.py） ----
# 開啟後系統會照下面的間隔自動觸發一輪分析（跟按「立即分析」一樣的邏輯），不用手動點擊。
# 這跟本系統原本「用量完全由使用者點擊次數決定」的設計精神不同，所以刻意預設關閉，需要
# 透過 POST /api/v1/scheduler 主動開啟——開關/間隔實際存在 SQLite（跨重啟持續生效，
# 可以不重啟伺服器就調整），這裡的環境變數只是「資料庫裡還沒被設定過時」的起始值。
SCHEDULER_ENABLED_DEFAULT = os.getenv("SCHEDULER_ENABLED", "false").lower() == "true"
SCHEDULER_INTERVAL_SECONDS_DEFAULT = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "1800"))
# 強制下限：不管使用者透過 API 設多短，實際排程間隔都不會短於這個值，防止設定錯誤
# （或誤觸 API）變成失控的高頻迴圈，把 OKX／AI 用量燒爆。
SCHEDULER_MIN_INTERVAL_SECONDS = 900

# ---- 背景排程模式下的 AI 用量治理（見 ai_governor.py） ----
# 規則大腦（技術面 EMA/突破/量能/趨勢，見 strategy.py／brain.py）每一輪排程都會跑，
# 零額外成本；AI 新聞情緒（見 news_client.py）不是每輪都問，靠以下三道防線把關：
# 1. 節流週期：預設每 3 輪才問一次 AI，除非這輪剛好偵測到新技術訊號，那種情況一律優先問
#    （新訊號的新聞情緒判讀對使用者最有價值，不該被固定週期卡住）。
AI_REFRESH_EVERY_N_CYCLES = int(os.getenv("AI_REFRESH_EVERY_N_CYCLES", "3"))
# 2. 每日呼叫上限：0 代表不限制。這個上限只套用在「背景排程」觸發的 AI 呼叫；使用者自己
#    手動按「立即分析」一律照舊不受這個上限影響——手動點擊本來就已經被點擊次數天然節流，
#    不該因為背景排程用掉了額度就連手動分析也被擋。
AI_DAILY_CALL_CAP = int(os.getenv("AI_DAILY_CALL_CAP", "48"))
# 3. 連續失敗斷路器：背景排程觸發的 AI 呼叫連續失敗達這個次數，之後幾輪暫停呼叫 AI（只跑
#    規則大腦），避免對著故障中的 AI API 一直重試燒 token；使用者下一次手動「立即分析」
#    會重置這個計數（見 background.refresh_cycle 說明）。0 代表不啟用這道防線。
AI_FAILURE_THRESHOLD = int(os.getenv("AI_FAILURE_THRESHOLD", "3"))

# ---- 使用者自訂警報（選用，見 alerts.py） ----
# repeat_mode="repeating" 的警報，距離上次觸發至少要過這麼多秒才允許再通知一次，避免
# 同一個條件持續成立時每輪分析都推播一次（通知疲勞）。
ALERT_MIN_RETRIGGER_SECONDS = int(os.getenv("ALERT_MIN_RETRIGGER_SECONDS", "3600"))
# 警報總數上限（不分商品），防止無上限累積；到上限後 POST /api/v1/alerts 會拒絕新建，
# 提示使用者先刪掉不需要的舊警報。
ALERT_MAX_TOTAL = int(os.getenv("ALERT_MAX_TOTAL", "50"))

# ---- 訊號結果追蹤與自動優化（見 db.py / outcome_tracker.py / strategy_tuner.py） ----
# 每次分析時回頭檢查未結算訊號要抓多少根已收盤 K 線（OKX /market/candles 單次上限 300）
RESOLUTION_LOOKBACK_CANDLES = int(os.getenv("RESOLUTION_LOOKBACK_CANDLES", "300"))
# 訊號追蹤超過這麼久還沒結果就標記為「逾期」，不再無限期追蹤——當沖訊號本來就不該留倉過夜，
# 拖過這個時限代表已經失去「當沖」的參考意義。預設 25 小時（涵蓋隔一天再來看的情況）。
SIGNAL_EXPIRE_HOURS = float(os.getenv("SIGNAL_EXPIRE_HOURS", "25"))
