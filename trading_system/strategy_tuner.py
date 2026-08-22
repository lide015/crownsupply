"""自動優化：累積夠多已驗證訊號後，根據近期勝率動態調整「24h 振幅門檻」——勝率偏低就
調高門檻（篩掉波動較弱、雜訊較多的商品），勝率夠好就把門檻往回調低（放寬篩選，抓更多
機會，不要因為之前收緊過就一路卡死在高門檻不動）。保守、透明、有上下限——不是黑箱：
每次調整都回傳可以直接顯示給使用者的理由字串，樣本數不夠時完全不動（避免對少數幾筆
雜訊反應過度）。
"""

MIN_SAMPLES = 10          # 少於這個已驗證訊號數，不調整——樣本太少會對雜訊反應過度
LOW_WATERMARK_PCT = 40.0   # 勝率低於這個百分比，調高門檻（更保守篩選）
HIGH_WATERMARK_PCT = 65.0  # 勝率高於這個百分比，調低門檻（放寬篩選，抓更多機會）
STEP = 0.5                 # 每次調整的幅度
MAX_AMPLITUDE_PCT = 8.0    # 往上收緊的上限，避免門檻被一路調到篩不出任何商品


def maybe_auto_tune(
    win_rate_stats: dict,
    current_min_amplitude_pct: float,
    last_tune_sample_count: int = 0,
    floor_amplitude_pct: float = 1.0,
) -> dict | None:
    """win_rate_stats: outcome_tracker.compute_win_rate() 的輸出。
    last_tune_sample_count：上次觸發調整當下的已驗證訊號總數——沒有新增資料就不能再調一次，
    不然使用者連續點兩次「立即分析」、中間完全沒有新的訊號結算，門檻卻被連續調整兩次，
    等於對同一筆舊資料重複反應，不是根據新證據調整。
    floor_amplitude_pct：往下放寬的下限——呼叫端傳使用者自己在 .env 設定的原始
    MIN_AMPLITUDE_PCT，系統只會在這個值「之上」動態調整（往上收緊、往下放寬），不會放寬
    到低於使用者自己設定的起點，尊重使用者原本的意圖，不會擅自變得比使用者要求的還寬鬆。

    回傳 None 代表這次不調整；否則回傳
    {"param","old_value","new_value","reason","direction"}（direction 是
    "tighten"/"loosen"，純粹方便呼叫端做其他判斷，前端目前只顯示 reason 文字）。
    """
    if win_rate_stats["total"] < MIN_SAMPLES:
        return None
    if win_rate_stats["total"] <= last_tune_sample_count:
        return None  # 自從上次調整後沒有新的已驗證訊號，沒有新證據，不重複調整
    win_rate_pct = win_rate_stats["win_rate_pct"]
    if win_rate_pct is None:
        return None

    if win_rate_pct < LOW_WATERMARK_PCT:
        new_value = round(min(current_min_amplitude_pct + STEP, MAX_AMPLITUDE_PCT), 2)
        if new_value <= current_min_amplitude_pct:
            return None  # 已經到上限，調不動了
        reason = (
            f"近 {win_rate_stats['total']} 筆已驗證訊號勝率僅 {win_rate_pct}%"
            f"（{win_rate_stats['wins']} 中 {win_rate_stats['losses']} 負，低於門檻 {LOW_WATERMARK_PCT}%），"
            f"系統自動把 24h 振幅門檻從 {current_min_amplitude_pct}% 調高到 {new_value}%，"
            f"篩掉波動較弱、雜訊較多的商品，提高後續訊號品質。"
        )
        return {
            "param": "MIN_AMPLITUDE_PCT", "old_value": current_min_amplitude_pct,
            "new_value": new_value, "reason": reason, "direction": "tighten",
        }

    if win_rate_pct > HIGH_WATERMARK_PCT:
        new_value = round(max(current_min_amplitude_pct - STEP, floor_amplitude_pct), 2)
        if new_value >= current_min_amplitude_pct:
            return None  # 已經回到使用者設定的下限，調不動了
        reason = (
            f"近 {win_rate_stats['total']} 筆已驗證訊號勝率達 {win_rate_pct}%"
            f"（{win_rate_stats['wins']} 中 {win_rate_stats['losses']} 負，高於門檻 {HIGH_WATERMARK_PCT}%），"
            f"系統自動把 24h 振幅門檻從 {current_min_amplitude_pct}% 調低到 {new_value}%，"
            f"目前規則表現不錯，放寬篩選讓更多符合條件的機會進得來。"
        )
        return {
            "param": "MIN_AMPLITUDE_PCT", "old_value": current_min_amplitude_pct,
            "new_value": new_value, "reason": reason, "direction": "loosen",
        }

    return None  # 勝率落在正常區間，不需要調整


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

    # 2) 樣本夠、勝率落在正常區間（40%~65%之間）-> 不調整
    check(
        "enough samples but win rate in normal range -> no tune",
        maybe_auto_tune({"total": 20, "wins": 10, "losses": 10, "win_rate_pct": 50.0}, 3.0),
        None,
    )

    # 3) 樣本夠、勝率偏低 -> 調高門檻，理由字串要有數字
    result = maybe_auto_tune({"total": 20, "wins": 6, "losses": 14, "win_rate_pct": 30.0}, 3.0)
    check("low win rate with enough samples -> tunes MIN_AMPLITUDE_PCT", result["param"], "MIN_AMPLITUDE_PCT")
    check("new value is old + STEP", result["new_value"], 3.5)
    check("reason mentions the win rate number", "30.0%" in result["reason"], True)
    check("direction is tighten", result["direction"], "tighten")

    # 4) 已經到收緊上限 -> 不再調整
    check(
        "already at max -> no further tighten",
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

    # 8) 勝率夠高 -> 調低門檻（放寬篩選），理由字串要有數字
    result3 = maybe_auto_tune({"total": 20, "wins": 15, "losses": 5, "win_rate_pct": 75.0}, 5.0, floor_amplitude_pct=3.0)
    check("high win rate -> loosens MIN_AMPLITUDE_PCT", result3["new_value"], 4.5)
    check("direction is loosen", result3["direction"], "loosen")
    check("reason mentions the win rate number", "75.0%" in result3["reason"], True)

    # 9) 勝率高、但已經回到使用者設定的下限 -> 不再放寬（不會低於使用者自己的原始設定）
    check(
        "already at user's floor -> no further loosen",
        maybe_auto_tune({"total": 20, "wins": 18, "losses": 2, "win_rate_pct": 90.0}, 3.0, floor_amplitude_pct=3.0),
        None,
    )

    # 10) 剛好在高水位邊界（不大於，不觸發）-> 不調整，確認邊界是嚴格 >，不是 >=
    check(
        "exactly at HIGH_WATERMARK_PCT boundary -> no tune (strict >)",
        maybe_auto_tune({"total": 20, "wins": 13, "losses": 7, "win_rate_pct": HIGH_WATERMARK_PCT}, 5.0),
        None,
    )

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
