"""自動優化：累積夠多已驗證訊號、勝率偏低時，自動調高「24h 振幅門檻」篩掉波動較弱、
雜訊較多的商品。保守、透明、有上限——不是黑箱：每次調整都回傳可以直接顯示給使用者的
理由字串，樣本數不夠時完全不動（避免對少數幾筆雜訊反應過度）。
"""

MIN_SAMPLES = 10         # 少於這個已驗證訊號數，不調整——樣本太少會對雜訊反應過度
LOW_WATERMARK_PCT = 40.0  # 勝率低於這個百分比才觸發調整
STEP = 0.5                # 每次調整的幅度
MAX_AMPLITUDE_PCT = 8.0   # 調整上限，避免門檻被一路調到篩不出任何商品


def maybe_auto_tune(win_rate_stats: dict, current_min_amplitude_pct: float, last_tune_sample_count: int = 0) -> dict | None:
    """win_rate_stats: outcome_tracker.compute_win_rate() 的輸出。
    last_tune_sample_count：上次觸發調整當下的已驗證訊號總數——沒有新增資料就不能再調一次，
    不然使用者連續點兩次「立即分析」、中間完全沒有新的訊號結算，門檻卻被拉高兩次，等於
    對同一筆舊資料重複反應，不是根據新證據調整。
    回傳 None 代表這次不調整；否則回傳 {"param","old_value","new_value","reason"}。"""
    if win_rate_stats["total"] < MIN_SAMPLES:
        return None
    if win_rate_stats["total"] <= last_tune_sample_count:
        return None  # 自從上次調整後沒有新的已驗證訊號，沒有新證據，不重複調整
    win_rate_pct = win_rate_stats["win_rate_pct"]
    if win_rate_pct is None or win_rate_pct >= LOW_WATERMARK_PCT:
        return None

    new_value = round(min(current_min_amplitude_pct + STEP, MAX_AMPLITUDE_PCT), 2)
    if new_value <= current_min_amplitude_pct:
        return None  # 已經到上限，調不動了

    reason = (
        f"近 {win_rate_stats['total']} 筆已驗證訊號勝率僅 {win_rate_pct}%"
        f"（{win_rate_stats['wins']} 中 {win_rate_stats['losses']} 負，低於門檻 {LOW_WATERMARK_PCT}%），"
        f"系統自動把 24h 振幅門檻從 {current_min_amplitude_pct}% 調高到 {new_value}%，"
        f"篩掉波動較弱、雜訊較多的商品，提高後續訊號品質。"
    )
    return {"param": "MIN_AMPLITUDE_PCT", "old_value": current_min_amplitude_pct, "new_value": new_value, "reason": reason}


if __name__ == "__main__":
    _passed = 0
    _total = 0

    def check(name, actual, expected):
        global _passed, _total
        _total += 1
        ok = actual == expected
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: got={actual} expected={expected}")
        if ok:
            _passed += 1

    # 1) 樣本不足 -> 不調整
    check(
        "too few samples -> no tune",
        maybe_auto_tune({"total": 5, "wins": 1, "losses": 4, "win_rate_pct": 20.0}, 3.0),
        None,
    )

    # 2) 樣本夠、勝率高 -> 不調整
    check(
        "enough samples but win rate healthy -> no tune",
        maybe_auto_tune({"total": 20, "wins": 15, "losses": 5, "win_rate_pct": 75.0}, 3.0),
        None,
    )

    # 3) 樣本夠、勝率偏低 -> 調整，理由字串要有數字
    result = maybe_auto_tune({"total": 20, "wins": 6, "losses": 14, "win_rate_pct": 30.0}, 3.0)
    check("low win rate with enough samples -> tunes MIN_AMPLITUDE_PCT", result["param"], "MIN_AMPLITUDE_PCT")
    check("new value is old + STEP", result["new_value"], 3.5)
    check("reason mentions the win rate number", "30.0%" in result["reason"], True)

    # 4) 已經到上限 -> 不再調整
    check(
        "already at max -> no further tune",
        maybe_auto_tune({"total": 20, "wins": 2, "losses": 18, "win_rate_pct": 10.0}, MAX_AMPLITUDE_PCT),
        None,
    )

    # 5) 沒有已結算紀錄 (win_rate_pct=None) -> 不調整
    check(
        "no resolved history yet -> no tune",
        maybe_auto_tune({"total": 0, "wins": 0, "losses": 0, "win_rate_pct": None}, 3.0),
        None,
    )

    # 6) 樣本沒比上次調整時多 -> 不重複調整（同一批舊資料不該被連續調兩次）
    check(
        "no new evidence since last tune -> no tune",
        maybe_auto_tune({"total": 12, "wins": 4, "losses": 8, "win_rate_pct": 33.3}, 3.5, last_tune_sample_count=12),
        None,
    )

    # 7) 樣本比上次調整時多 -> 可以再調一次
    result2 = maybe_auto_tune({"total": 15, "wins": 5, "losses": 10, "win_rate_pct": 33.3}, 3.5, last_tune_sample_count=12)
    check("new evidence since last tune -> tunes again", result2["new_value"], 4.0)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
