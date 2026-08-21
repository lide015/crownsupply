"""行程內記憶體狀態——手動按「立即分析」觸發時寫入（background.refresh_cycle），
REST 端點負責讀取（app.py）。不用 Redis／資料庫：這是單人使用的本機監控工具，
程序重啟資料重算即可。

沒有背景排程了：不點按鈕就不會有任何 OKX／AI API 呼叫，用量完全由使用者自己控制。
"""


class SystemState:
    def __init__(self):
        self.last_update: str | None = None
        self.has_run: bool = False  # 是否已經手動分析過至少一次
        self.is_analyzing: bool = False  # 目前是否有一次分析正在進行（避免重複點擊同時打兩輪）
        self.market_sentiment: str = "NEUTRAL"
        self.news_headline: str = "尚未分析"
        self.news_reason: str = "請點擊「立即分析」開始，本系統不會自動在背景執行分析。"
        self.monitored: list[dict] = []
        self.signals: list[dict] = []
        self.last_error: str | None = None


STATE = SystemState()
