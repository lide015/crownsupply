"""RSI14 / SMA / annualized volatility / max drawdown — pure Python, zero dependencies."""
import math


def sma(closes, n):
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def rsi14(closes, n=14):
    if len(closes) < n + 1:
        return None
    window = closes[-(n + 1):]
    gains = 0.0
    losses = 0.0
    for i in range(1, len(window)):
        delta = window[i] - window[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


def ann_vol_pct(closes, n=30):
    if len(closes) < n + 1:
        return None
    window = closes[-(n + 1):]
    rets = [math.log(window[i] / window[i - 1]) for i in range(1, len(window))]
    mean = sum(rets) / len(rets)
    variance = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(variance) * math.sqrt(365) * 100.0


def max_drawdown_pct(closes):
    if not closes:
        return None
    peak = closes[0]
    mdd = 0.0
    for price in closes:
        if price > peak:
            peak = price
        dd = (price - peak) / peak
        if dd < mdd:
            mdd = dd
    return mdd * 100.0


def chg_pct(closes, days_back):
    if len(closes) <= days_back:
        return None
    last = closes[-1]
    prior = closes[-1 - days_back]
    if prior == 0:
        return None
    return (last / prior - 1.0) * 100.0


def _round(v, d=2):
    return None if v is None else round(v, d)


def compute_indicators(closes):
    """closes: ascending-by-day list of daily close prices (oldest first)."""
    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)
    ma_bias_pct = ((ma20 - ma60) / ma60 * 100.0) if (ma20 is not None and ma60) else None
    return {
        "rsi14": _round(rsi14(closes)),
        "ma20": _round(ma20),
        "ma60": _round(ma60),
        "ma_bias_pct": _round(ma_bias_pct),
        "ann_vol_pct": _round(ann_vol_pct(closes)),
        "mdd90_pct": _round(max_drawdown_pct(closes[-90:]) if closes else None),
        "chg7_pct": _round(chg_pct(closes, 7)),
    }


if __name__ == "__main__":
    _passed = 0
    _total = 0

    def check(name, actual, expected, tol=1e-6):
        global _passed, _total
        _total += 1
        ok = (actual is None and expected is None) or (
            actual is not None and expected is not None and abs(actual - expected) <= tol
        )
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: got={actual} expected={expected}")
        if ok:
            _passed += 1

    # 1) SMA — hand-computable averages
    check("sma([10,20,30,40,50], 5)", sma([10, 20, 30, 40, 50], 5), 30.0)
    check("sma([10,20,30,40,50], 3)", sma([10, 20, 30, 40, 50], 3), 40.0)

    # 2) RSI — all gains -> 100
    up = [100 + i for i in range(15)]
    check("rsi14 all-gains -> 100", rsi14(up), 100.0)

    # 3) RSI — all losses -> 0
    down = [114 - i for i in range(15)]
    check("rsi14 all-losses -> 0", rsi14(down), 0.0)

    # 4) Annualized volatility of a flat series -> 0
    flat = [100.0] * 31
    check("ann_vol_pct flat series -> 0", ann_vol_pct(flat), 0.0)

    # 5) Max drawdown — peak 120 -> trough 80, (80-120)/120*100
    check("max_drawdown_pct([100,120,90,110,80])", max_drawdown_pct([100, 120, 90, 110, 80]), -100.0 / 3.0, tol=1e-9)

    # 6) 7-day change — closes 1..100, last=100, 7d-ago=93 -> (100/93-1)*100
    seq = list(range(1, 101))
    check("chg_pct(1..100, 7)", chg_pct([float(x) for x in seq], 7), 700.0 / 93.0, tol=1e-9)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
