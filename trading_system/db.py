"""SQLite 儲存：訊號歷史（用來驗證勝率、抓失敗原因）+ 自動調整後的策略參數 + 使用者自訂
警報（見 alerts.py）。stdlib sqlite3、WAL 模式、不用 ORM——跟 backend/db.py 同樣的慣例。
跟 backend/ 共用 repo 根目錄的 data/ 資料夾（不同檔名），該資料夾已經在 .gitignore 裡。

這張表讓「訊號後來到底有沒有用」這件事跨重啟持續累積，不會每次重啟伺服器就砍掉重練；
也讓自動調整後的參數持續生效，而不是每次啟動又跑回預設值。
"""
import json
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
  failure_reason TEXT,
  -- 使用者對這筆訊號的個人決策標籤：'approved'（已核准，我會照這筆訊號行動）／
  -- 'watching'（先觀察，還沒決定）／'rejected'（拒絕，不採用）。NULL＝還沒表態
  -- （預設）。這是使用者自己的紀錄用途，本系統仍然不會替使用者真的下單——見
  -- app.py 的 POST /api/v1/signal-decision 說明。
  user_decision TEXT,
  user_decision_at INTEGER
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

-- 使用者自訂警報（見 alerts.py 的評估邏輯）：價格漲破/跌破門檻、或出現新技術訊號。
-- channels 存 JSON 陣列字串（例如 '["telegram","email"]'），db.py 邊界負責 dumps/loads，
-- 呼叫端一律拿到/傳入 Python list，不用自己處理 JSON。
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  inst_id TEXT NOT NULL,
  name TEXT NOT NULL,
  alert_type TEXT NOT NULL,
  threshold REAL,
  repeat_mode TEXT NOT NULL DEFAULT 'once',
  channels TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  last_triggered_at INTEGER,
  trigger_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS alerts_inst_idx ON alerts(inst_id);
CREATE INDEX IF NOT EXISTS alerts_enabled_idx ON alerts(enabled);
"""


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_missing_columns(conn: sqlite3.Connection):
    """`CREATE TABLE IF NOT EXISTS` 只對「全新資料庫」有效——已經存在的 signal_history
    表不會因為 _SCHEMA 字串多了新欄位就自動補上，需要對已存在的舊資料庫額外
    `ALTER TABLE ADD COLUMN`。這裡用 PRAGMA table_info 檢查欄位存不存在，缺才補，
    冪等（重複執行也不會出錯），新資料庫（CREATE TABLE 那一步就已經有這些欄位了）
    這裡直接是無事可做。"""
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(signal_history)").fetchall()}
    if "user_decision" not in existing_cols:
        conn.execute("ALTER TABLE signal_history ADD COLUMN user_decision TEXT")
    if "user_decision_at" not in existing_cols:
        conn.execute("ALTER TABLE signal_history ADD COLUMN user_decision_at INTEGER")


def init_db():
    conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
        _migrate_missing_columns(conn)
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


VALID_SIGNAL_DECISIONS = ("approved", "watching", "rejected")


def get_signal_by_id(signal_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM signal_history WHERE id = ?", (signal_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_signal_decision(signal_id: int, decision: str | None, now_ms: int) -> bool:
    """使用者對這筆訊號的個人決策標籤（見「訊號核准」功能，app.py 的
    POST /api/v1/signal-decision）。decision 必須是 VALID_SIGNAL_DECISIONS 其中一個，
    或 None（清除回「還沒表態」，例如使用者點了「已核准」又想反悔）——無效值直接
    raise ValueError，不會悄悄存進一個前端從沒出現過的狀態。

    回傳是否真的更新到一列（id 不存在就回傳 False，呼叫端可以據此回 404），
    跟 set_alert_enabled 同樣的慣例。"""
    if decision is not None and decision not in VALID_SIGNAL_DECISIONS:
        raise ValueError(f"invalid decision: {decision!r}, must be one of {VALID_SIGNAL_DECISIONS} or None")
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE signal_history SET user_decision = ?, user_decision_at = ? WHERE id = ?",
            (decision, now_ms if decision is not None else None, signal_id),
        )
        conn.commit()
        return cur.rowcount > 0
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


def get_resolved_trades_for_kelly() -> list[dict]:
    """給 outcome_tracker.compute_average_win_r_multiple 用：所有已結算訊號的
    entry_price/stop_loss/resolution/resolution_price，不限筆數（凱利公式的樣本
    越多越準，跟 get_all_resolved_for_stats 的「不限筆數」邏輯一致）。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT entry_price, stop_loss, resolution, resolution_price "
            "FROM signal_history WHERE resolution != 'open'"
        ).fetchall()
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


def get_resolved_today(now_ms: int) -> list[dict]:
    """給「每日虧損斷路器」用（見 background.py `_compute_circuit_breaker` 說明）：
    「今天」以 now_ms 所在的 UTC 日曆日為準（day_start_ms 到隔天 00:00 之間結算的訊號），
    不做使用者所在時區的轉換——這跟資料庫裡 created_at/resolved_at 儲存的 epoch ms
    本來就是 UTC 時間戳一致，避免額外猜測使用者時區反而讓「今天」的邊界對不上。
    只回傳 entry_price/stop_loss/resolution/resolution_price（斷路器只需要算 R 倍數），
    跟 get_resolved_trades_for_kelly 給的欄位一致，方便共用 outcome_tracker 的計算邏輯。"""
    conn = get_connection()
    try:
        day_start_ms = (now_ms // 86_400_000) * 86_400_000
        day_end_ms = day_start_ms + 86_400_000
        rows = conn.execute(
            "SELECT entry_price, stop_loss, resolution, resolution_price "
            "FROM signal_history WHERE resolution != 'open' AND resolved_at >= ? AND resolved_at < ?",
            (day_start_ms, day_end_ms),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_previous_oi() -> dict[str, float]:
    """跟 get_previous_oi 同樣的用途，但一次撈出「全部」商品的上一輪 OI 快照，給熱力圖
    的「📌 持倉」模式用——現在要同時比較全部合約（可能兩三百檔）的 OI 變化，逐檔各開一次
    連線太浪費，一次查詢、一個連線就夠。回傳 {inst_id: oi_ccy}。"""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT inst_id, oi_ccy FROM oi_snapshot").fetchall()
        return {r["inst_id"]: float(r["oi_ccy"]) for r in rows}
    finally:
        conn.close()


def set_oi_snapshots_bulk(rows: list[dict], updated_at: int):
    """set_oi_snapshot 的批次版本：rows 是 [{"inst_id", "oi", "oi_ccy"}, ...]，全部商品
    共用同一個連線、同一次 commit，避免全市場規模（兩三百檔）逐一開關連線的開銷。"""
    if not rows:
        return
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO oi_snapshot (inst_id, oi, oi_ccy, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(inst_id) DO UPDATE SET oi = excluded.oi, oi_ccy = excluded.oi_ccy, "
            "updated_at = excluded.updated_at",
            [(r["inst_id"], r["oi"], r["oi_ccy"], updated_at) for r in rows],
        )
        conn.commit()
    finally:
        conn.close()


def _alert_row_to_dict(row: sqlite3.Row) -> dict:
    """統一的 alerts 表列 -> dict 轉換，channels 欄位從 JSON 字串還原成 list（呼叫端一律
    拿到 Python list，不用自己處理 JSON），三個地方共用（create/list/get），避免各自重複
    寫一次還原邏輯、之後改欄位漏改其中一處。"""
    d = dict(row)
    try:
        d["channels"] = json.loads(d["channels"])
    except (TypeError, ValueError):
        d["channels"] = []
    d["enabled"] = bool(d["enabled"])
    return d


def create_alert(row: dict) -> dict:
    """row 需含 inst_id/name/alert_type/threshold(可 None)/repeat_mode/channels(list)/
    created_at。回傳新建立的完整警報 dict（含 id），channels 已經還原成 list。"""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO alerts
               (inst_id, name, alert_type, threshold, repeat_mode, channels, enabled, created_at)
               VALUES (:inst_id, :name, :alert_type, :threshold, :repeat_mode, :channels, 1, :created_at)""",
            {**row, "channels": json.dumps(row["channels"])},
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM alerts WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _alert_row_to_dict(new_row)
    finally:
        conn.close()


def get_alerts() -> list[dict]:
    """全部警報，供管理面板用，依建立時間新到舊排序。"""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM alerts ORDER BY created_at DESC").fetchall()
        return [_alert_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_enabled_alerts() -> list[dict]:
    """只讀啟用中的警報，供每輪分析的評估迴圈用（見 background.py）——停用的警報不用
    每輪都撈出來判斷條件，省一點查詢跟迴圈開銷。"""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM alerts WHERE enabled = 1").fetchall()
        return [_alert_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def count_alerts() -> int:
    """給建立警報前的總數上限檢查用（見 config.ALERT_MAX_TOTAL），避免無上限累積。"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM alerts").fetchone()
        return int(row["c"])
    finally:
        conn.close()


def set_alert_enabled(alert_id: int, enabled: bool) -> bool:
    """回傳是否真的更新到一列（id 不存在就回傳 False，呼叫端可以據此回 404）。"""
    conn = get_connection()
    try:
        cur = conn.execute("UPDATE alerts SET enabled = ? WHERE id = ?", (1 if enabled else 0, alert_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_alert(alert_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def record_alert_trigger(alert_id: int, triggered_at: int, auto_disable: bool):
    """警報真的觸發（should_fire 回傳 True）之後呼叫：累計次數、記下觸發時間；
    auto_disable=True（一次性警報，見 alerts.should_fire 的 repeat_mode="once" 說明）時
    連同 enabled 一起關掉，觸發完就停用，不用靠 should_fire 每次重新判斷 trigger_count。"""
    conn = get_connection()
    try:
        if auto_disable:
            conn.execute(
                "UPDATE alerts SET last_triggered_at = ?, trigger_count = trigger_count + 1, enabled = 0 WHERE id = ?",
                (triggered_at, alert_id),
            )
        else:
            conn.execute(
                "UPDATE alerts SET last_triggered_at = ?, trigger_count = trigger_count + 1 WHERE id = ?",
                (triggered_at, alert_id),
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

        # get_resolved_trades_for_kelly：目前 3 筆都還是 open，先確認回傳空清單，
        # 再實際結算兩筆（一勝一敗），確認已結算的才會出現、還沒結算的不會混進來。
        check("get_resolved_trades_for_kelly excludes still-open signals", get_resolved_trades_for_kelly(), [])

        win_id = insert_signal({
            "inst_id": "SOL-USDT-SWAP", "name": "SOL-USDT", "asset_class": "crypto",
            "signal_type": "long", "created_at": 3000, "entry_price": 100.0,
            "stop_loss": 95.0, "take_profit_1": 110.0, "take_profit_2": 120.0,
            "ema": 98.0, "box_high": 101.0, "box_low": 99.0,
            "ai_sentiment": "BULLISH", "action_label": "強烈做多", "color": "green",
        })
        resolve_signal(win_id, "hit_tp1", 3100, 110.0, None)
        loss_id = insert_signal({
            "inst_id": "SOL-USDT-SWAP", "name": "SOL-USDT", "asset_class": "crypto",
            "signal_type": "long", "created_at": 4000, "entry_price": 100.0,
            "stop_loss": 95.0, "take_profit_1": 110.0, "take_profit_2": 120.0,
            "ema": 98.0, "box_high": 101.0, "box_low": 99.0,
            "ai_sentiment": "BULLISH", "action_label": "強烈做多", "color": "green",
        })
        resolve_signal(loss_id, "hit_sl", 4100, 95.0, None)

        kelly_rows = get_resolved_trades_for_kelly()
        check("get_resolved_trades_for_kelly returns only resolved signals", len(kelly_rows), 2)
        check("get_resolved_trades_for_kelly rows carry the fields Kelly math needs",
              set(kelly_rows[0].keys()), {"entry_price", "stop_loss", "resolution", "resolution_price"})

        # get_all_previous_oi / set_oi_snapshots_bulk：熱力圖「持倉」模式的全市場批次版本
        check("get_all_previous_oi empty before any snapshot", get_all_previous_oi(), {})
        set_oi_snapshots_bulk([
            {"inst_id": "BTC-USDT-SWAP", "oi": 1000.0, "oi_ccy": 500.0},
            {"inst_id": "ETH-USDT-SWAP", "oi": 2000.0, "oi_ccy": 800.0},
        ], updated_at=5000)
        all_oi = get_all_previous_oi()
        check("set_oi_snapshots_bulk writes both rows", all_oi, {"BTC-USDT-SWAP": 500.0, "ETH-USDT-SWAP": 800.0})

        # 再跑一次、換一組數值 -> 驗證是 UPSERT（覆蓋掉舊值），不是無限累積重複列
        set_oi_snapshots_bulk([{"inst_id": "BTC-USDT-SWAP", "oi": 1100.0, "oi_ccy": 550.0}], updated_at=6000)
        check("set_oi_snapshots_bulk upserts existing inst_id", get_all_previous_oi()["BTC-USDT-SWAP"], 550.0)
        check("set_oi_snapshots_bulk does not touch other inst_ids", get_all_previous_oi()["ETH-USDT-SWAP"], 800.0)

        # 空清單不該炸掉，也不該建立任何連線副作用
        set_oi_snapshots_bulk([], updated_at=7000)
        check("set_oi_snapshots_bulk with empty list is a no-op", len(get_all_previous_oi()), 2)

        # get_resolved_today：每日虧損斷路器用的查詢——day_start_ms 當天（含邊界）算「今天」，
        # 前一天最後一毫秒不算，跟「今天」之後幾小時的正常情況都要驗證到。
        day_start_ms = 100 * 86_400_000
        today_id = insert_signal({
            "inst_id": "XRP-USDT-SWAP", "name": "XRP-USDT", "asset_class": "crypto",
            "signal_type": "long", "created_at": day_start_ms - 5000, "entry_price": 1.0,
            "stop_loss": 0.95, "take_profit_1": 1.1, "take_profit_2": 1.2,
            "ema": 0.98, "box_high": 1.01, "box_low": 0.99,
            "ai_sentiment": "NEUTRAL", "action_label": "做多", "color": "green",
        })
        resolve_signal(today_id, "hit_sl", day_start_ms, 0.95, None)  # 剛好在邊界上 -> 算今天

        today_id_2 = insert_signal({
            "inst_id": "XRP-USDT-SWAP", "name": "XRP-USDT", "asset_class": "crypto",
            "signal_type": "long", "created_at": day_start_ms, "entry_price": 1.0,
            "stop_loss": 0.95, "take_profit_1": 1.1, "take_profit_2": 1.2,
            "ema": 0.98, "box_high": 1.01, "box_low": 0.99,
            "ai_sentiment": "NEUTRAL", "action_label": "做多", "color": "green",
        })
        resolve_signal(today_id_2, "hit_sl", day_start_ms + 3_600_000, 0.95, None)  # 今天中午 -> 算今天

        yesterday_id = insert_signal({
            "inst_id": "XRP-USDT-SWAP", "name": "XRP-USDT", "asset_class": "crypto",
            "signal_type": "long", "created_at": day_start_ms - 10000, "entry_price": 1.0,
            "stop_loss": 0.95, "take_profit_1": 1.1, "take_profit_2": 1.2,
            "ema": 0.98, "box_high": 1.01, "box_low": 0.99,
            "ai_sentiment": "NEUTRAL", "action_label": "做多", "color": "green",
        })
        resolve_signal(yesterday_id, "hit_sl", day_start_ms - 1, 0.95, None)  # 前一天最後一毫秒 -> 不算今天

        resolved_today = get_resolved_today(day_start_ms + 7_200_000)  # 今天下午 2 點呼叫
        check("get_resolved_today includes boundary + same-day rows only", len(resolved_today), 2)
        check("get_resolved_today rows carry the fields needed for R-multiple math",
              set(resolved_today[0].keys()), {"entry_price", "stop_loss", "resolution", "resolution_price"})

        check("get_resolved_today on a day with nothing resolved returns empty list",
              get_resolved_today(day_start_ms - 30 * 86_400_000), [])

        # --- 警報 CRUD（見 alerts.py 的評估邏輯，這裡只測儲存層） ---
        check("get_alerts empty before any created", get_alerts(), [])
        check("count_alerts starts at 0", count_alerts(), 0)

        price_alert = create_alert({
            "inst_id": "BTC-USDT-SWAP", "name": "BTC-USDT", "alert_type": "price_above",
            "threshold": 120.0, "repeat_mode": "once", "channels": ["telegram", "email"],
            "created_at": 1000,
        })
        check("create_alert returns dict with id assigned", isinstance(price_alert["id"], int), True)
        check("create_alert channels round-trips as a list (not a JSON string)", price_alert["channels"], ["telegram", "email"])
        check("create_alert defaults enabled=True", price_alert["enabled"], True)
        check("create_alert trigger_count starts at 0", price_alert["trigger_count"], 0)
        check("create_alert last_triggered_at starts as None", price_alert["last_triggered_at"], None)

        signal_alert = create_alert({
            "inst_id": "ETH-USDT-SWAP", "name": "ETH-USDT", "alert_type": "signal",
            "threshold": None, "repeat_mode": "repeating", "channels": ["telegram"],
            "created_at": 2000,
        })
        check("count_alerts reflects both created rows", count_alerts(), 2)

        all_alerts = get_alerts()
        check("get_alerts returns newest-first", all_alerts[0]["id"], signal_alert["id"])
        check("get_alerts returns both rows", len(all_alerts), 2)

        check("get_enabled_alerts returns both (both enabled by default)", len(get_enabled_alerts()), 2)

        disabled_ok = set_alert_enabled(price_alert["id"], False)
        check("set_alert_enabled on existing id returns True", disabled_ok, True)
        check("get_enabled_alerts now excludes the disabled one", len(get_enabled_alerts()), 1)
        check("set_alert_enabled on unknown id returns False", set_alert_enabled(999999, True), False)

        record_alert_trigger(signal_alert["id"], 3000, auto_disable=False)
        triggered_row = next(a for a in get_alerts() if a["id"] == signal_alert["id"])
        check("record_alert_trigger (repeating) increments trigger_count", triggered_row["trigger_count"], 1)
        check("record_alert_trigger (repeating) sets last_triggered_at", triggered_row["last_triggered_at"], 3000)
        check("record_alert_trigger (repeating) leaves it enabled", triggered_row["enabled"], True)

        record_alert_trigger(price_alert["id"], 4000, auto_disable=True)
        auto_disabled_row = next(a for a in get_alerts() if a["id"] == price_alert["id"])
        check("record_alert_trigger (auto_disable) also disables the alert", auto_disabled_row["enabled"], False)
        check("record_alert_trigger (auto_disable) still increments trigger_count", auto_disabled_row["trigger_count"], 1)

        deleted_ok = delete_alert(signal_alert["id"])
        check("delete_alert on existing id returns True", deleted_ok, True)
        check("count_alerts reflects the deletion", count_alerts(), 1)
        check("delete_alert on unknown id returns False", delete_alert(999999), False)

        # --- 訊號決策標籤（見「訊號核准」功能，app.py 的 POST /api/v1/signal-decision） ---
        decision_signal_id = insert_signal({
            "inst_id": "SOL-USDT-SWAP", "name": "SOL-USDT", "asset_class": "crypto",
            "signal_type": "long", "created_at": 5000, "entry_price": 20.0,
            "stop_loss": 19.0, "take_profit_1": 22.0, "take_profit_2": 24.0,
            "ema": 19.5, "box_high": 20.5, "box_low": 19.5,
            "ai_sentiment": "BULLISH", "action_label": "強烈做多", "color": "green",
        })
        fresh_row = get_signal_by_id(decision_signal_id)
        check("newly inserted signal has user_decision=None by default", fresh_row["user_decision"], None)
        check("newly inserted signal has user_decision_at=None by default", fresh_row["user_decision_at"], None)

        approved_ok = set_signal_decision(decision_signal_id, "approved", 6000)
        check("set_signal_decision on existing id returns True", approved_ok, True)
        approved_row = get_signal_by_id(decision_signal_id)
        check("set_signal_decision stores the decision", approved_row["user_decision"], "approved")
        check("set_signal_decision stores the timestamp", approved_row["user_decision_at"], 6000)

        # 改變心意：核准 -> 觀察，確認會覆蓋掉舊的決策，不是疊加/累積。
        set_signal_decision(decision_signal_id, "watching", 7000)
        check("set_signal_decision overwrites a previous decision", get_signal_by_id(decision_signal_id)["user_decision"], "watching")

        # 清除回「還沒表態」——decision=None 是合法輸入，不是錯誤。
        set_signal_decision(decision_signal_id, None, 8000)
        cleared_row = get_signal_by_id(decision_signal_id)
        check("set_signal_decision(None) clears the decision", cleared_row["user_decision"], None)
        check("set_signal_decision(None) also clears the timestamp", cleared_row["user_decision_at"], None)

        check("set_signal_decision on unknown id returns False", set_signal_decision(999999, "approved", 9000), False)
        check("get_signal_by_id on unknown id returns None", get_signal_by_id(999999), None)

        try:
            set_signal_decision(decision_signal_id, "not_a_real_decision", 10000)
            check("set_signal_decision rejects an invalid decision value", False, True)
        except ValueError:
            check("set_signal_decision rejects an invalid decision value", True, True)

        # --- Schema 遷移：模擬「升級前就已經有資料庫」的既有使用者，signal_history 表
        # 存在但沒有 user_decision/user_decision_at 兩個欄位——init_db() 要能補上這兩個
        # 欄位、不動到既有資料，而且重複執行要是冪等的（不會因為欄位已經加過就出錯）。
        original_db_path = DB_PATH  # 先存起來，這個子區塊結束後要復原，不能直接用 DB_PATH
        # 這個名字本身——底下會把它重新指向遷移測試用的暫時檔案，屆時裸讀 DB_PATH 拿到的
        # 已經是新值，不是這裡想保留的原始值。
        with tempfile.TemporaryDirectory() as tmp_migrate:
            migrate_db_path = Path(tmp_migrate) / "old_schema.db"
            old_conn = sqlite3.connect(migrate_db_path)
            old_conn.execute(
                """CREATE TABLE signal_history (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  inst_id TEXT NOT NULL, name TEXT NOT NULL, asset_class TEXT NOT NULL,
                  signal_type TEXT NOT NULL, created_at INTEGER NOT NULL,
                  entry_price REAL NOT NULL, stop_loss REAL NOT NULL,
                  take_profit_1 REAL NOT NULL, take_profit_2 REAL NOT NULL,
                  ema REAL, box_high REAL, box_low REAL, ai_sentiment TEXT,
                  action_label TEXT, color TEXT, resolution TEXT NOT NULL DEFAULT 'open',
                  resolved_at INTEGER, resolution_price REAL, failure_reason TEXT
                )"""
            )
            old_conn.execute(
                "INSERT INTO signal_history (inst_id, name, asset_class, signal_type, created_at, "
                "entry_price, stop_loss, take_profit_1, take_profit_2) VALUES "
                "('OLD-USDT-SWAP', 'OLD-USDT', 'crypto', 'long', 100, 10.0, 9.0, 11.0, 12.0)"
            )
            old_conn.commit()
            old_conn.close()

            globals()["DB_PATH"] = migrate_db_path
            init_db()  # 應該補上缺的兩個欄位，不動到既有資料
            migrated_row = get_signal_by_id(1)
            check("migration: pre-existing row survives schema upgrade", migrated_row["inst_id"], "OLD-USDT-SWAP")
            check("migration: new column defaults to None on old rows", migrated_row["user_decision"], None)
            # 遷移後這個功能要能正常運作，不是只有欄位存在但寫不進去。
            set_signal_decision(1, "rejected", 200)
            check("migration: set_signal_decision works after migrating an old DB", get_signal_by_id(1)["user_decision"], "rejected")
            # 冪等：再跑一次 init_db()（模擬伺服器重啟）不該出錯。
            init_db()
            check("migration: running init_db() twice is idempotent (no error, data intact)", get_signal_by_id(1)["user_decision"], "rejected")

        globals()["DB_PATH"] = original_db_path  # 復原成這個測試檔案原本用的路徑

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
