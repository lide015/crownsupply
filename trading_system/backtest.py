"""策略回測：把 strategy.py 的 20 EMA + 盤整盒子突破規則，套用在「已經發生過」的歷史
K 線上逐根重播，統計如果這套規則過去每次觸發都真的照著停損/停利執行，會是什麼樣的
勝率、平均獲利倍數（R）、獲利因子（profit factor）、最大連續虧損——不用像
outcome_tracker.py 那樣，得靠使用者一次次按「立即分析」、等好幾天累積出足夠的已結算
樣本，馬上就能看到這套規則在過去一段歷史上表現如何。

方法論精神參考「backtesting」skill（gauss314/skills，MIT License，見
.claude/skills/backtest-strategy/SKILL.md 的完整出處說明）Data → Research → Metrics →
Validation 這套流程裡的「Metrics」思路——不是搬對方的程式碼或資料源，是把同一套評估
指標（勝率／獲利因子／連續虧損／R 倍數）套用在這個 repo 自己的策略邏輯跟自己的資料
來源（OKX 歷史 K 線）上。

⚠️ 嚴格避免「未來函數」（look-ahead bias）：在歷史上的每個時間點 i 計算訊號時，只把
candles[:i+1]（也就是「當時」已經收盤、還看不到後面走勢的 K 線）餵給
strategy.compute_signal()；訊號觸發後，才用「當時之後」的 K 線（candles[i+1:]）去
模擬結果——這是嚴謹回測跟「拿收盤價套後照鏡」最根本的差異。判定停損/停利用的是
outcome_tracker.simulate_resolution() **同一套規則**（同一根 K 線同時觸及停損停利，
保守判定為停損），確保回測跟線上盤中即時追蹤的勝率算法一致，不是兩套標準各說各話。

純函式、零額外網路/AI 呼叫——candles 由呼叫端事先用 okx_client.fetch_confirmed_candles
抓好（跟策略分析共用同一份資料格式），這裡只負責重播與統計。
"""
from . import outcome_tracker, strategy


def _resolution_r_multiple(resolution: str, entry_price: float, stop_loss: float, resolution_price: float) -> float:
    """R 倍數＝實際獲利/虧損距離 ÷ 進場到停損的風險距離；hit_sl 一律算 -1R（不管當時
    是不是有一點點滑價，回測用固定 -1R 更保守、不會低估虧損）。"""
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        return 0.0
    if resolution == "hit_sl":
        return -1.0
    return abs(resolution_price - entry_price) / risk


def run_backtest(
    candles: list[dict],
    ema_period: int = 20,
    box_lookback: int = 15,
    tp1_rr: float = 1.5,
    tp2_rr: float = 2.0,
    volume_confirm_multiple: float = 0.0,
) -> dict:
    """candles：升冪（舊到新）、已收盤的 [{ts,o,h,l,c,vol}, ...]，跟 strategy.compute_signal
    要求的格式一致（okx_client.fetch_confirmed_candles 的輸出可以直接餵進來）。

    volume_confirm_multiple：跟 strategy.compute_signal 的同名參數一樣意思——套用同一套
    量能突破確認規則來重播歷史，這樣「回測」跟「線上即時分析」用的是同一套判斷邏輯，
    不是回測一套、線上又是另一套。0（預設）代表不啟用。

    ⚠️ 這裡**沒有**套用多時間週期共振（htf_trend）跟每日虧損斷路器（circuit_breaker）
    這兩個線上分析才有的把關——htf_trend 需要同步重播「第二條」更高週期的K線序列，
    circuit_breaker 是跟「今天」這個當下日期綁定的概念，兩者都不是單純「這個策略在這批
    歷史K線上表現如何」這個問題的一部分，硬套進來反而會讓回測結果失去單純性、難以
    解讀。回測只驗證純技術面規則（含量能過濾）的歷史表現。

    回傳 {"total_trades","wins","losses","win_rate_pct","avg_r_multiple",
    "max_consecutive_losses","profit_factor","trades":[...]}；trades 依時間序列出每一筆
    模擬交易的方向/進場/停損/結果/R倍數，前端可以逐筆檢視，不是只丟一個籠統的總分。

    資料不夠跑完一次完整的 EMA+盒子週期時，回傳全部欄位為 0/None 的空結果（不拋例外，
    讓呼叫端可以直接顯示「這檔資料不足」，不用另外包一層防呆）。"""
    min_len = max(ema_period, box_lookback + 1)
    trades: list[dict] = []
    i = min_len
    n = len(candles)

    while i < n:
        window = candles[: i + 1]
        tech = strategy.compute_signal(window, ema_period, box_lookback, tp1_rr, tp2_rr, volume_confirm_multiple)

        if tech is not None and tech["signal"] is not None:
            after = candles[i + 1:]
            resolution, price, resolved_ts, bars = outcome_tracker.simulate_resolution(
                tech["signal"], tech["price"], tech["stop_loss"],
                tech["take_profit_1"], tech["take_profit_2"], after,
            )
            if resolution is None:
                # 這筆訊號到資料尾端都還沒有結果——維持 open，不計入統計（避免把「還沒
                # 走完的交易」誤算成輸家），直接停止重播（後面的窗口也只會是同一筆的延續）。
                break

            trades.append({
                "ts": window[-1]["ts"],
                "signal_type": tech["signal"],
                "entry_price": tech["price"],
                "stop_loss": tech["stop_loss"],
                "resolution": resolution,
                "resolution_price": price,
                "bars_to_resolution": bars,
                "r_multiple": round(_resolution_r_multiple(resolution, tech["price"], tech["stop_loss"], price), 3),
            })
            # 跳過這筆交易已經用掉的 K 線，避免同一段走勢被重複算成好幾筆重疊交易
            # （不跳過的話，突破後隔一根又會因為價格還在停損停利之間而被視為「新訊號」）。
            i += max(bars, 1)
            continue

        i += 1

    return _summarize(trades)


def _summarize(trades: list[dict]) -> dict:
    wins = [t for t in trades if t["resolution"] in ("hit_tp1", "hit_tp2")]
    losses = [t for t in trades if t["resolution"] == "hit_sl"]
    total = len(wins) + len(losses)
    win_rate_pct = round(len(wins) / total * 100.0, 1) if total > 0 else None

    r_multiples = [t["r_multiple"] for t in trades]
    avg_r_multiple = round(sum(r_multiples) / len(r_multiples), 3) if r_multiples else None

    # 最大連續虧損：規則式風控常看的指標——就算長期期望值是正的，連續虧損拉太長，
    # 使用者的心理/資金曲線也可能撐不住、半路就不照規則執行了。
    max_consecutive_losses = 0
    streak = 0
    for t in trades:
        if t["resolution"] == "hit_sl":
            streak += 1
            max_consecutive_losses = max(max_consecutive_losses, streak)
        else:
            streak = 0

    # 獲利因子（profit factor）＝總獲利 R 加總 ÷ 總虧損 R 加總（絕對值）；> 1 代表整體
    # 是正期望值。完全沒有虧損交易時比值理論上是無限大，但樣本數通常還很小，與其顯示
    # 一個容易被誤解成「穩賺」的 Infinity，老實回傳 None 讓前端顯示「尚無虧損交易」。
    gross_win_r = sum(t["r_multiple"] for t in wins)
    gross_loss_r = abs(sum(t["r_multiple"] for t in losses))
    profit_factor = round(gross_win_r / gross_loss_r, 2) if gross_loss_r > 0 else None

    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": win_rate_pct,
        "avg_r_multiple": avg_r_multiple,
        "max_consecutive_losses": max_consecutive_losses,
        "profit_factor": profit_factor,
        "trades": trades,
    }


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

    # 1) 資料完全不夠一次 EMA+盒子週期 -> 空結果，不拋例外
    empty = run_backtest([{"o": 1, "h": 1, "l": 1, "c": 1, "ts": 0}] * 5, ema_period=20, box_lookback=15)
    check("insufficient data -> empty result", empty["total_trades"], 0)
    check("insufficient data -> no trades list entries", empty["trades"], [])
    check("insufficient data -> win_rate_pct None", empty["win_rate_pct"], None)

    # 2) 建構一段歷史：20 根平盤盤整 + 突破上漲直接命中 TP2 -> 1 筆 hit_tp2 交易
    flat = [{"ts": i, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0} for i in range(20)]
    breakout_win = flat + [
        {"ts": 100, "o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0},  # 突破：entry=105, sl=box_mid=100, risk=5
        {"ts": 101, "o": 105.0, "h": 116.0, "l": 104.0, "c": 115.0},  # tp1=112.5, tp2=115 都命中 -> hit_tp2
    ]
    result_win = run_backtest(breakout_win, ema_period=20, box_lookback=15, tp1_rr=1.5, tp2_rr=2.0)
    check("one winning breakout -> 1 trade", result_win["total_trades"], 1)
    check("winning trade resolution is hit_tp2", result_win["trades"][0]["resolution"], "hit_tp2")
    check("winning trade r_multiple ~2.0", result_win["trades"][0]["r_multiple"], 2.0)
    check("win_rate_pct is 100.0", result_win["win_rate_pct"], 100.0)
    check("no losses -> profit_factor None (undefined ratio)", result_win["profit_factor"], None)

    # 3) 對稱情境：突破後立刻反轉觸及停損 -> 1 筆 hit_sl 交易，r_multiple = -1.0
    breakout_loss = flat + [
        {"ts": 100, "o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0},  # 突破：entry=105, sl=100
        {"ts": 101, "o": 105.0, "h": 105.0, "l": 95.0, "c": 96.0},    # 立刻跌破停損 100
    ]
    result_loss = run_backtest(breakout_loss, ema_period=20, box_lookback=15, tp1_rr=1.5, tp2_rr=2.0)
    check("one losing breakout -> 1 trade", result_loss["total_trades"], 1)
    check("losing trade resolution is hit_sl", result_loss["trades"][0]["resolution"], "hit_sl")
    check("losing trade r_multiple is -1.0", result_loss["trades"][0]["r_multiple"], -1.0)
    check("win_rate_pct is 0.0", result_loss["win_rate_pct"], 0.0)
    check("max_consecutive_losses is 1", result_loss["max_consecutive_losses"], 1)

    # 4) 訊號觸發但資料在結果出來之前就用完 -> 不計入統計（維持 open，不誤判輸贏）
    breakout_unresolved = flat + [
        {"ts": 100, "o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0},  # 突破，entry=105, sl=100, tp1=112.5
        {"ts": 101, "o": 105.0, "h": 106.0, "l": 104.0, "c": 105.5},  # 還在盤整，沒到停損也沒到停利
    ]
    result_unresolved = run_backtest(breakout_unresolved, ema_period=20, box_lookback=15, tp1_rr=1.5, tp2_rr=2.0)
    check("unresolved trade at data end -> not counted", result_unresolved["total_trades"], 0)

    # 5) 只在盤整區間內震盪，從頭到尾沒有任何突破 -> 沒有任何交易
    still_flat = flat + [{"ts": i, "o": 100.0, "h": 100.5, "l": 99.5, "c": 100.0} for i in range(20, 40)]
    result_none = run_backtest(still_flat, ema_period=20, box_lookback=15)
    check("no breakout at all -> zero trades", result_none["total_trades"], 0)

    # 6) 混合情境的彙總邏輯：直接測 _summarize()（不透過 run_backtest 重播真實 K 線）——
    # 用一筆 +2R 的贏、一筆 -1R 的輸，驗證 avg_r_multiple / profit_factor / 連續虧損都有
    # 把兩筆交易都算進去，不是只看最後一筆。這樣測試不受 strategy.compute_signal() 本身
    # 「box 剛好被前一次突破的極值汙染」這種既有、預期中的行為影響（那是 strategy.py 自己
    # 的特性，不是 backtest.py 要處理的邊界情況）。
    mixed_trades = [
        {"ts": 100, "signal_type": "long", "entry_price": 100.0, "stop_loss": 95.0,
         "resolution": "hit_sl", "resolution_price": 95.0, "bars_to_resolution": 1, "r_multiple": -1.0},
        {"ts": 200, "signal_type": "long", "entry_price": 100.0, "stop_loss": 95.0,
         "resolution": "hit_tp2", "resolution_price": 110.0, "bars_to_resolution": 2, "r_multiple": 2.0},
    ]
    result_mixed = _summarize(mixed_trades)
    check("mixed scenario -> 2 trades total", result_mixed["total_trades"], 2)
    check("mixed scenario -> 1 win 1 loss", (result_mixed["wins"], result_mixed["losses"]), (1, 1))
    check("mixed scenario -> win_rate 50%", result_mixed["win_rate_pct"], 50.0)
    check("mixed scenario -> avg_r_multiple is (-1.0+2.0)/2=0.5", result_mixed["avg_r_multiple"], 0.5)
    check("mixed scenario -> profit_factor is 2.0/1.0=2.0", result_mixed["profit_factor"], 2.0)
    check("mixed scenario -> max_consecutive_losses is 1", result_mixed["max_consecutive_losses"], 1)

    # 7) volume_confirm_multiple 有正確傳進 strategy.compute_signal：量能不足的突破
    # 在回測重播時也應該被過濾掉，跟線上即時分析用同一套判斷邏輯
    flat_with_vol = [{"ts": i, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "vol": 1000.0} for i in range(20)]
    weak_vol_breakout = flat_with_vol + [
        {"ts": 100, "o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0, "vol": 500.0},  # 量能只有均量一半
        {"ts": 101, "o": 105.0, "h": 116.0, "l": 104.0, "c": 115.0, "vol": 1000.0},
    ]
    result_weak_vol = run_backtest(weak_vol_breakout, ema_period=20, box_lookback=15, volume_confirm_multiple=1.2)
    check("weak-volume breakout filtered out during backtest replay", result_weak_vol["total_trades"], 0)

    strong_vol_breakout = flat_with_vol + [
        {"ts": 100, "o": 100.0, "h": 106.0, "l": 100.0, "c": 105.0, "vol": 2000.0},  # 量能是均量兩倍
        {"ts": 101, "o": 105.0, "h": 116.0, "l": 104.0, "c": 115.0, "vol": 1000.0},
    ]
    result_strong_vol = run_backtest(strong_vol_breakout, ema_period=20, box_lookback=15, volume_confirm_multiple=1.2)
    check("strong-volume breakout still counted during backtest replay", result_strong_vol["total_trades"], 1)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
