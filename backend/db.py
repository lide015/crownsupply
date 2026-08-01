"""SQLite storage — stdlib sqlite3 only, WAL mode, no ORM."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "brief.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  ts INTEGER PRIMARY KEY,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kline_daily (
  symbol TEXT NOT NULL,
  day TEXT NOT NULL,
  close REAL NOT NULL,
  PRIMARY KEY (symbol, day)
);
CREATE TABLE IF NOT EXISTS kline_ohlc_daily (
  symbol TEXT NOT NULL,
  day TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  PRIMARY KEY (symbol, day)
);
"""


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def insert_snapshot(ts: int, payload_json: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO snapshots (ts, payload) VALUES (?, ?)",
            (ts, payload_json),
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_snapshot():
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT ts, payload FROM snapshots ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()


def get_snapshots_since(ts_from: int, limit: int = 720):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT ts, payload FROM snapshots WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
            (ts_from, limit),
        ).fetchall()
        return list(reversed(rows))
    finally:
        conn.close()


def prune_snapshots(before_ts: int) -> int:
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM snapshots WHERE ts < ?", (before_ts,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def upsert_klines(symbol: str, rows):
    """rows: iterable of (day: 'YYYY-MM-DD', close: float)."""
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO kline_daily (symbol, day, close) VALUES (?, ?, ?) "
            "ON CONFLICT(symbol, day) DO UPDATE SET close = excluded.close",
            [(symbol, day, close) for day, close in rows],
        )
        conn.commit()
    finally:
        conn.close()


def get_closes(symbol: str, limit: int = 100):
    """Returns [(day, close), ...] ascending by day (oldest first), most recent `limit` days."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT day, close FROM kline_daily WHERE symbol = ? ORDER BY day DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return list(reversed(rows))
    finally:
        conn.close()


def upsert_ohlc(symbol: str, rows):
    """rows: iterable of (day, open, high, low, close, volume)."""
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO kline_ohlc_daily (symbol, day, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(symbol, day) DO UPDATE SET "
            "open = excluded.open, high = excluded.high, low = excluded.low, "
            "close = excluded.close, volume = excluded.volume",
            [(symbol, day, o, h, l, c, v) for day, o, h, l, c, v in rows],
        )
        conn.commit()
    finally:
        conn.close()


def get_ohlc(symbol: str, limit: int = 100):
    """Returns [(day, open, high, low, close), ...] ascending by day, most recent `limit` days."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT day, open, high, low, close FROM kline_ohlc_daily "
            "WHERE symbol = ? ORDER BY day DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return list(reversed(rows))
    finally:
        conn.close()
