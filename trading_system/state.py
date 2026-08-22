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
        # OKX 上「全部」商品的基本報價（不套流動性/振幅門檻、不截斷），給前端的「全部商品
        # 總覽」瀏覽/篩選/搜尋用；`monitored` 才是自動篩選出來、真正做完整分析的子集合。
        self.all_instruments: list[dict] = []
        self.last_error: str | None = None
        # 訊號結果追蹤與自動優化（見 db.py / outcome_tracker.py / strategy_tuner.py）
        self.win_rate_stats: dict = {"total": 0, "wins": 0, "losses": 0, "win_rate_pct": None}
        self.recent_resolved: list[dict] = []
        self.kelly_suggestion: dict | None = None
        self.tuning_note: str | None = None  # 這一輪如果剛好觸發自動優化，放調整理由；沒有就 None
        self.effective_min_amplitude_pct: float = 0.0  # 目前實際生效的振幅門檻（可能已被自動優化調整過）
        # 市場情緒儀表板（見 market_pulse.py）：平均 RSI、山寨季代理指標、恐懼貪婪指數
        self.market_pulse: dict = {
            "rsi": {"avg_rsi": None, "label": "尚未分析", "sample_size": 0},
            "altseason": {"pct_outperforming_btc": None, "label": "尚未分析", "sample_size": 0},
            "fear_greed": None,
        }
        # 推薦強度榜（見 ranking.py）：做多/做空各自依四維度總分排序
        self.ranking: dict = {"long": [], "short": []}
        # 每日虧損斷路器（見 outcome_tracker.compute_daily_circuit_breaker）：今天已結算
        # 訊號有沒有觸及虧損上限，前端用這個顯示「今日戰績」跟斷路器是否啟動。
        self.circuit_breaker: dict = {"active": False, "reason": None, "loss_count": 0, "total_r": 0.0}


STATE = SystemState()
