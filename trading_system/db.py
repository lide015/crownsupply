"""SQLite 儲存：訊號歷史（用來驗證勝率、抓失敗原因）+ 自動調整後的策略參數。
stdlib sqlite3、WAL 模式、不用 ORM——跟 backend/db.py 同樣的慣例。跟 backend/ 共用
repo 根目錄的 data/ 資料夾（不同檔名），該資料夾已經在 .gitignore 裡。

這張表讓「訊號後來到底有沒有用」這件事跨重啟持續累積，不會每次重啟伺服器就砍掉重練；
也讓自動調整後的參數持續生效，而不是每次啟動又跑回預設值。
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "trading_system.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  inst_id TEXT NOT NULL,
  name TEXT NOT NULL,
  asset_class TEXT NOT NULL,
  signal_type TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  entry_price REAL NOT NULL,
  stop_loss REAL NOT NULL,
  take_profit_1 REAL NOT NULL,
  take_profit_2 REAL NOT NULL,
  ema REAL,
  box_high REAL,
  box_low REAL,
  ai_sentiment TEXT,
  action_label TEXT,
  color TEXT,
  resolution TEXT NOT NULL DEFAULT 'open',
  resolved_at INTEGER,
  resolution_price REAL,
  failure_reason TEXT
);
CREATE INDEX IF NOT EXISTS signal_history_inst_idx ON signal_history(inst_id);
CREATE INDEX IF NOT EXISTS signal_history_resolution_idx ON signal_history(resolution);

CREATE TABLE IF NOT EXISTS strategy_params (
  key TEXT PRIMARY KEY,
  value REAL NOT NULL,
  updated_at INTEGER NOT NULL,
  reason TEXT
);

-- 每檔商品只留「最近一次」的未平倉量快照（見 oi_tracker.py），用來跟這一輪比較算出
-- 變化幅度。不留歷史序列——OI 儀表板只需要「跟上次分析週期比起來變化多少」，不需要
-- 長期時間序列，用 UPSERT 保持這張表只有 TOP_N 等級的少量列數。
CREATE TABLE IF NOT EXISTS oi_snapshot (
  inst_id TEXT PRIMARY KEY,
  oi REAL NOT NULL,
  oi_ccy REAL NOT NULL,
  updated_at INTEGER NOT NULL
);
"""


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def insert_signal(row: dict) -> int:
    """row 需含 signal_history 除了 id/resolution/resolved_at/resolution_price/failure_reason
    以外的所有欄位（那幾個有預設值或允許 NULL）。回傳新插入的 row id。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO signal_history
               (inst_id, name, asset_class, signal_type, created_at, entry_price,
                stop_loss, take_profit_1, take_profit_2, ema, box_high, box_low,
                ai_sentiment, action_label, color)
               VALUES (:inst_id, :name, :asset_class, :signal_type, :created_at, :entry_price,
                       :stop_loss, :take_profit_1, :take_profit_2, :ema, :box_high, :box_low,
                       :ai_sentiment, :action_label, :color)""",
            row,
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_open_signal_for(inst_id: str, signal_type: str):
    """同一個商品、同一個方向如果已經有一筆還沒結算的訊號，就不要重複插入新的一筆
    （使用者可能連續按好幾次「立即分析」，同一個突破不該每次都算一筆新紀錄）。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM signal_history WHERE inst_id = ? AND signal_type = ? "
            "AND resolution = 'open' ORDER BY created_at DESC LIMIT 1",
            (inst_id, signal_type),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_open_signals() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM signal_history WHERE resolution = 'open'").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def resolve_signal(signal_id: int, resolution: str, resolved_at: int, resolution_price: float, failure_reason: str | None):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE signal_history SET resolution = ?, resolved_at = ?, resolution_price = ?, "
            "failure_reason = ? WHERE id = ?",
            (resolution, resolved_at, resolution_price, failure_reason, signal_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_resolved(limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM signal_history WHERE resolution != 'open' "
            "ORDER BY resolved_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_resolved_for_stats() -> list[dict]:
    """給 outcome_tracker.compute_win_rate 用，不限筆數，讓勝率反映全部歷史。"""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT resolution FROM signal_history WHERE resolution != 'open'").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_signal_history_for(inst_id: str, limit: int = 10) -> list[dict]:
    """給「單一商品詳情頁」的事件時間軸用：這檔商品過去觸發過的訊號（不管有沒有結算），
    由新到舊排序。這是目前系統唯一持續累積的「這檔商品發生過什麼事」紀錄——沒有真正
    的新聞事件或鏈上事件資料源，誠實地說就是「本系統自己判斷過的訊號歷史」。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM signal_history WHERE inst_id = ? ORDER BY created_at DESC LIMIT ?",
            (inst_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_param(key: str, default: float) -> float:
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM strategy_params WHERE key = ?", (key,)).fetchone()
        return float(row["value"]) if row else default
    finally:
        conn.close()


def set_param(key: str, value: float, updated_at: int, reason: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO strategy_params (key, value, updated_at, reason) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, "
            "reason = excluded.reason",
            (key, value, updated_at, reason),
        )
        conn.commit()
    finally:
        conn.close()


def get_previous_oi(inst_id: str) -> float | None:
    """回傳上一輪分析記下的未平倉量（換算成標的幣種數量），沒有紀錄就回傳 None
    （oi_tracker.compute_oi_delta 看到 None 會回傳「尚無基準值」而不是亂猜方向）。"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT oi_ccy FROM oi_snapshot WHERE inst_id = ?", (inst_id,)).fetchone()
        return float(row["oi_ccy"]) if row else None
    finally:
        conn.close()


def set_oi_snapshot(inst_id: str, oi: float, oi_ccy: float, updated_at: int):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO oi_snapshot (inst_id, oi, oi_ccy, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(inst_id) DO UPDATE SET oi = excluded.oi, oi_ccy = excluded.oi_ccy, "
            "updated_at = excluded.updated_at",
            (inst_id, oi, oi_ccy, updated_at),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    import tempfile

    _passed = 0
    _total = 0

    def check(name, actual, expected):
        global _passed, _total
        _total += 1
        ok = actual == expected
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: got={actual} expected={expected}")
        if ok:
            _passed += 1

    # 全部測試都指向一個暫時的 DB 檔案，不會碰到 data/trading_system.db 真正的資料。
    with tempfile.TemporaryDirectory() as tmp:
        DB_PATH = Path(tmp) / "test.db"  # noqa: F811 — 刻意覆蓋模組層級變數，測試用
        globals()["DB_PATH"] = DB_PATH
        init_db()

        insert_signal({
            "inst_id": "BTC-USDT-SWAP", "name": "BTC-USDT", "asset_class": "crypto",
            "signal_type": "long", "created_at": 1000, "entry_price": 100.0,
            "stop_loss": 95.0, "take_profit_1": 110.0, "take_profit_2": 120.0,
            "ema": 98.0, "box_high": 101.0, "box_low": 99.0,
            "ai_sentiment": "BULLISH", "action_label": "強烈做多", "color": "green",
        })
        insert_signal({
            "inst_id": "BTC-USDT-SWAP", "name": "BTC-USDT", "asset_class": "crypto",
            "signal_type": "short", "created_at": 2000, "entry_price": 105.0,
            "stop_loss": 110.0, "take_profit_1": 95.0, "take_profit_2": 90.0,
            "ema": 106.0, "box_high": 107.0, "box_low": 104.0,
            "ai_sentiment": "NEUTRAL", "action_label": "做空", "color": "red",
        })
        insert_signal({
            "inst_id": "ETH-USDT-SWAP", "name": "ETH-USDT", "asset_class": "crypto",
            "signal_type": "long", "created_at": 1500, "entry_price": 50.0,
            "stop_loss": 48.0, "take_profit_1": 54.0, "take_profit_2": 56.0,
            "ema": 49.0, "box_high": 50.5, "box_low": 49.5,
            "ai_sentiment": "BULLISH", "action_label": "強烈做多", "color": "green",
        })

        history = get_signal_history_for("BTC-USDT-SWAP")
        check("get_signal_history_for only returns matching inst_id", len(history), 2)
        check("get_signal_history_for orders newest first", history[0]["created_at"], 2000)

        history_other = get_signal_history_for("ETH-USDT-SWAP")
        check("get_signal_history_for isolates other instruments", len(history_other), 1)

        history_limited = get_signal_history_for("BTC-USDT-SWAP", limit=1)
        check("get_signal_history_for respects limit", len(history_limited), 1)

        check("get_signal_history_for on unknown inst_id returns empty list",
              get_signal_history_for("NOPE-USDT-SWAP"), [])

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
