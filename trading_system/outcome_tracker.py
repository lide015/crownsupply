"""訊號結果追蹤：模擬訊號產生後價格路徑，判斷後來是中停利還是停損；停損時用純規則（零 AI
成本）判斷可能的失效原因。全部是純函式，跟網路/資料庫呼叫分開，方便單元測試。
"""


def simulate_resolution(signal_type, entry_price, stop_loss, take_profit_1, take_profit_2, candles):
    """candles：訊號產生「之後」的已收盤 K 線，升冪（舊到新）。

    回傳 (resolution, resolution_price, resolved_at_ts, bars_to_resolution) 或
    (None, None, None, None) 代表這批資料裡還沒有結果（維持 open，下次再檢查）。

    規則：
    - 同一根 K 線內同時觸及停損與停利時，一律先當作停損——保守假設，避免高估勝率。
    - TP1 達成後視為這筆訊號已經「成功」（模擬「有先減碼部位」的心態），之後就算價格
      又拉回跌破停損，也不會倒扣成 hit_sl；只有還沒到 TP1 之前觸及停損才算 hit_sl。
      如果 TP1 之後價格繼續推進到 TP2，會升級成 hit_tp2。
    """
    hit_tp1 = False
    tp1_price = tp1_ts = tp1_bar_idx = None

    for idx, c in enumerate(candles):
        if signal_type == "long":
            sl_hit = c["l"] <= stop_loss
            tp1_hit = c["h"] >= take_profit_1
            tp2_hit = c["h"] >= take_profit_2
        else:
            sl_hit = c["h"] >= stop_loss
            tp1_hit = c["l"] <= take_profit_1
            tp2_hit = c["l"] <= take_profit_2

        if not hit_tp1:
            if sl_hit:
                return "hit_sl", stop_loss, c["ts"], idx + 1
            if tp1_hit:
                hit_tp1 = True
                if tp2_hit:
                    return "hit_tp2", take_profit_2, c["ts"], idx + 1
                tp1_price, tp1_ts, tp1_bar_idx = take_profit_1, c["ts"], idx + 1
        else:
            if tp2_hit:
                return "hit_tp2", take_profit_2, c["ts"], idx + 1

    if hit_tp1:
        return "hit_tp1", tp1_price, tp1_ts, tp1_bar_idx
    return None, None, None, None


def classify_failure_reason(signal_row: dict, bars_to_sl: int) -> str:
    """signal_row 至少要有 entry_price / box_high / box_low / ema。純規則判斷，零 AI 呼叫成本。
    可能同時符合多個型態，全部列出來，讓使用者自己判斷哪個最貼切。"""
    reasons = []

    if bars_to_sl <= 2:
        reasons.append("突破後 1~2 根 K 線內就立刻反轉觸及停損，動能沒有延續，很可能是插針假突破。")

    box_high, box_low = signal_row.get("box_high"), signal_row.get("box_low")
    if box_high is not None and box_low is not None and box_low > 0:
        box_width_pct = (box_high - box_low) / box_low * 100.0
        if box_width_pct < 1.0:
            reasons.append(f"盤整盒子過窄（僅 {box_width_pct:.2f}%），突破後波動容易被放大，雜訊很容易就觸發停損。")

    ema, entry = signal_row.get("ema"), signal_row.get("entry_price")
    if ema is not None and entry:
        ema_margin_pct = abs(entry - ema) / entry * 100.0
        if ema_margin_pct < 0.15:
            reasons.append(f"進場當下價格離 20 EMA 只有 {ema_margin_pct:.2f}%，趨勢過濾條件在邊緣，訊號強度本來就偏弱。")

    if not reasons:
        reasons.append("找不到明顯的結構性弱點，可能單純是短期雜訊或整體市場氣氛轉變，不代表策略邏輯本身有誤。")

    return " ".join(reasons)


def compute_win_rate(resolved_rows: list[dict]) -> dict:
    """resolved_rows: signal_history 裡 resolution != 'open' 的紀錄（至少要有 "resolution" 欄位）。
    'expired'（追蹤逾期都沒結果）不計入勝率分母——沒有明確輸贏，算進去會失真。"""
    wins = sum(1 for r in resolved_rows if r["resolution"] in ("hit_tp1", "hit_tp2"))
    losses = sum(1 for r in resolved_rows if r["resolution"] == "hit_sl")
    total = wins + losses
    win_rate_pct = round(wins / total * 100.0, 1) if total > 0 else None
    return {"total": total, "wins": wins, "losses": losses, "win_rate_pct": win_rate_pct}


def compute_average_win_r_multiple(resolved_rows: list[dict]) -> float | None:
    """算「平均獲利倍數」（凱利公式裡的 b）：只看真的中停利的交易，用每一筆的
    「實際獲利距離 ÷ 進場到停損的風險距離」算出這一筆的 R 倍數，全部平均。

    resolved_rows 需含 entry_price / stop_loss / resolution / resolution_price
    （db.get_resolved_trades_for_kelly() 的格式）。用實際的 resolution_price 而不是
    直接假設等於 take_profit_1/2，避免任何未來調整結算邏輯時兩邊對不起來。

    一筆都沒中停利時回傳 None（凱利公式需要至少一筆正報酬樣本才算得出有意義的 b，
    不能瞎猜一個數字）。"""
    win_r_multiples = []
    for row in resolved_rows:
        if row["resolution"] not in ("hit_tp1", "hit_tp2"):
            continue
        risk = abs(row["entry_price"] - row["stop_loss"])
        if risk <= 0:
            continue
        reward = abs(row["resolution_price"] - row["entry_price"])
        win_r_multiples.append(reward / risk)
    if not win_r_multiples:
        return None
    return sum(win_r_multiples) / len(win_r_multiples)


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

    # 1) 直接觸及停損 -> hit_sl
    candles = [{"ts": 100, "h": 101, "l": 89}]  # long: entry=100, sl=90 -> low 89 <= 90
    res = simulate_resolution("long", 100, 90, 110, 120, candles)
    check("immediate SL hit -> hit_sl", res, ("hit_sl", 90, 100, 1))

    # 2) 先到 TP1 再到 TP2
    candles = [
        {"ts": 100, "h": 111, "l": 99},   # 觸及 TP1=110
        {"ts": 200, "h": 121, "l": 108},  # 觸及 TP2=120
    ]
    res = simulate_resolution("long", 100, 90, 110, 120, candles)
    check("TP1 then TP2 -> hit_tp2 at bar 2", res, ("hit_tp2", 120, 200, 2))

    # 3) 只到 TP1，資料用完 -> hit_tp1
    candles = [{"ts": 100, "h": 111, "l": 99}]
    res = simulate_resolution("long", 100, 90, 110, 120, candles)
    check("only TP1 reached -> hit_tp1", res, ("hit_tp1", 110, 100, 1))

    # 4) TP1 之後價格拉回跌破停損 -> 仍然算 hit_tp1（不倒扣），因為模擬已減碼心態
    candles = [
        {"ts": 100, "h": 111, "l": 99},   # 觸及 TP1
        {"ts": 200, "h": 105, "l": 85},   # 拉回跌破停損 90，但不改判定
    ]
    res = simulate_resolution("long", 100, 90, 110, 120, candles)
    check("pullback below SL after TP1 still counts as win", res[0], "hit_tp1")

    # 5) 同一根K線同時觸及停損跟停利 -> 保守判定為停損
    candles = [{"ts": 100, "h": 111, "l": 89}]
    res = simulate_resolution("long", 100, 90, 110, 120, candles)
    check("same-bar SL+TP ambiguity -> conservative hit_sl", res[0], "hit_sl")

    # 6) 資料不夠、都沒觸及 -> 維持 open (全部 None)
    candles = [{"ts": 100, "h": 105, "l": 95}]
    res = simulate_resolution("long", 100, 90, 110, 120, candles)
    check("still open -> all None", res, (None, None, None, None))

    # 7) short 方向對稱測試
    candles = [{"ts": 100, "h": 111, "l": 89}]  # short: entry=100, sl=110 -> high 111 >= 110
    res = simulate_resolution("short", 100, 110, 90, 80, candles)
    check("short SL hit", res[0], "hit_sl")

    # 8) classify_failure_reason -- 快速反轉
    reason = classify_failure_reason({"box_high": 105, "box_low": 100, "ema": 95, "entry_price": 106}, bars_to_sl=1)
    check("fast reversal mentioned", "插針假突破" in reason, True)

    # 9) classify_failure_reason -- 窄盒子
    reason = classify_failure_reason({"box_high": 100.5, "box_low": 100, "ema": 90, "entry_price": 101}, bars_to_sl=10)
    check("narrow box mentioned", "盤整盒子過窄" in reason, True)

    # 10) classify_failure_reason -- 找不到明顯弱點時的預設文字
    reason = classify_failure_reason({"box_high": 110, "box_low": 90, "ema": 50, "entry_price": 111}, bars_to_sl=10)
    check("fallback reason when nothing matches", "找不到明顯的結構性弱點" in reason, True)

    # 11) compute_win_rate
    rows = [{"resolution": "hit_tp1"}, {"resolution": "hit_tp2"}, {"resolution": "hit_sl"}, {"resolution": "expired"}]
    stats = compute_win_rate(rows)
    check("win_rate excludes expired from denominator", stats, {"total": 3, "wins": 2, "losses": 1, "win_rate_pct": 66.7})

    # 12) compute_win_rate -- 沒有已結算紀錄
    check("no resolved rows -> win_rate_pct None", compute_win_rate([]), {"total": 0, "wins": 0, "losses": 0, "win_rate_pct": None})

    # 13) compute_average_win_r_multiple -- 兩筆中停利，R倍數分別是 1.5 跟 2.0，平均 1.75
    kelly_rows = [
        {"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_tp1", "resolution_price": 107.5},  # risk=5, reward=7.5 -> R=1.5
        {"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_tp2", "resolution_price": 110.0},   # risk=5, reward=10 -> R=2.0
        {"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_sl", "resolution_price": 95.0},     # 停損不計入 b
    ]
    check("compute_average_win_r_multiple averages only winning trades", compute_average_win_r_multiple(kelly_rows), 1.75)

    # 14) compute_average_win_r_multiple -- 一筆中停利都沒有 -> None（不瞎猜）
    check("no winning trades -> None", compute_average_win_r_multiple([{"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_sl", "resolution_price": 95.0}]), None)

    # 15) compute_average_win_r_multiple -- 空清單 -> None
    check("empty rows -> None", compute_average_win_r_multiple([]), None)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
