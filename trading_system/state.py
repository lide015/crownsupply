"""行程內記憶體狀態——單一背景迴圈負責寫入（background.py），REST 端點負責讀取
（app.py）。不用 Redis／資料庫：這是單人使用的本機監控工具，程序重啟資料重算即可。
"""


class SystemState:
    def __init__(self):
        self.last_update: str | None = None
        self.market_sentiment: str = "NEUTRAL"
        self.news_headline: str = "尚未讀取新聞"
        self.news_reason: str = "系統剛啟動，等待第一輪背景更新"
        self.last_news_refresh_ts: float = 0.0
        self.monitored: list[dict] = []
        self.signals: list[dict] = []
        self.last_error: str | None = None


STATE = SystemState()
