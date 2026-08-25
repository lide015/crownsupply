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


# 分類代碼對應的知識宇宙卡片 id（見 knowledge_universe/seed_knowledge_nodes*.sql）：
# - fake_breakout / narrow_consolidation 都跟「盤整區間與突破交易」這張卡直接相關
# - weak_trend_confirmation 對應「均線與趨勢判斷」
# 這個對照表是前端（index.html 的 FAILURE_CATEGORY_TO_CARD）用的同一份分類代碼，這裡只是
# 說明分類代碼從何而來；實際的卡片 id 對照表維護在前端（那裡才知道 Supabase 卡片資料）。
def categorize_failure_reason(failure_reason: str | None) -> list[str]:
    """把 classify_failure_reason() 產生的人類可讀理由字串，反推出結構化的分類代碼，
    給知識宇宙卡片推薦用。直接讀已經存進資料庫的 failure_reason 文字比對關鍵字，不需要
    另外幫 signal_history 表新增欄位、也不用改資料庫 schema——這個函式本身就是「查詢時」
    才做的推導，不是寫入時的額外狀態，所以不影響任何既有資料。

    可能同時符合多個分類（跟 classify_failure_reason 一樣，一筆失效原因可能包含多種
    結構性弱點）；完全比對不到已知關鍵字時回傳 ["unclear"]，不會回傳空清單讓呼叫端
    誤以為「這筆沒有任何可以參考的知識點」。"""
    if not failure_reason:
        return []
    categories = []
    if "插針假突破" in failure_reason:
        categories.append("fake_breakout")
    if "盤整盒子過窄" in failure_reason:
        categories.append("narrow_consolidation")
    if "趨勢過濾條件在邊緣" in failure_reason:
        categories.append("weak_trend_confirmation")
    if not categories:
        categories.append("unclear")
    return categories


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


MIN_SAMPLE_FOR_RELIABLE_HIT_RATE = 5  # 跟 backtest.SWEEP_MIN_RELIABLE_TRADES 同樣的門檻慣例


def compute_pattern_hit_rates(resolved_rows: list[dict]) -> list[dict]:
    """型態命中率統計：pattern_recognition.py 偵測到的型態標籤（見該模組說明）目前純粹是
    資訊揭露，從不參與 brain.fuse() 的訊號融合——這個函式回頭看已經累積的訊號歷史，才
    知道「這個標籤出現時，後續勝率實際上比較高還是比較低」，把單純的資訊揭露變成有實據
    可以參考的訊息。

    resolved_rows: db.get_resolved_for_hit_rate_stats() 的格式，需含
    resolution/detected_patterns（detected_patterns 是 pattern key 字串的 list，同一筆
    訊號可能同時掛好幾個標籤，每個標籤各自累計一次，不是互斥分組）。

    回傳依樣本數（total）由多到少排序的
    [{"pattern_key","total","wins","losses","win_rate_pct","reliable"}, ...]——只收有
    出現過的標籤，沒出現過的不會生出一筆全 0 的紀錄。reliable=False 代表樣本數（少於
    MIN_SAMPLE_FOR_RELIABLE_HIT_RATE 筆）太少，數字僅供參考，不是偷偷過濾掉、也不是
    假裝每個標籤的統計都一樣可信。"""
    by_pattern: dict[str, list[dict]] = {}
    for row in resolved_rows:
        for key in row.get("detected_patterns") or []:
            by_pattern.setdefault(key, []).append(row)

    results = []
    for key, rows in by_pattern.items():
        stats = compute_win_rate(rows)
        results.append({
            "pattern_key": key,
            "total": stats["total"], "wins": stats["wins"], "losses": stats["losses"],
            "win_rate_pct": stats["win_rate_pct"],
            "reliable": stats["total"] >= MIN_SAMPLE_FOR_RELIABLE_HIT_RATE,
        })
    results.sort(key=lambda r: r["total"], reverse=True)
    return results


def compute_decision_hit_rates(resolved_rows: list[dict]) -> dict:
    """訊號核准決策事後命中率：使用者在「訊號核准」功能（見 app.py
    POST /api/v1/signal-decision）自己標記過 approved／watching／rejected 的訊號，
    後續實際勝率分別是多少——讓使用者知道自己手動判斷是不是真的比系統原始建議準，
    還是反而在扯後腿。沒有標記過（user_decision 是 None）的訊號另外分一組
    `no_decision` 當對照組，不會被排除在統計之外。

    resolved_rows: db.get_resolved_for_hit_rate_stats() 的格式，需含
    resolution/user_decision。

    回傳 {"approved": {...compute_win_rate 的形狀 + reliable}, "watching": {...},
    "rejected": {...}, "no_decision": {...}}——四組固定都會出現，就算某一組完全沒有
    樣本，win_rate_pct 是 None、reliable 是 False，不會讓那一組直接從回傳值裡消失，
    前端才知道「這組是真的沒資料」而不是誤以為統計壞了。"""
    groups: dict[str, list[dict]] = {"approved": [], "watching": [], "rejected": [], "no_decision": []}
    for row in resolved_rows:
        key = row.get("user_decision") or "no_decision"
        if key in groups:
            groups[key].append(row)

    result = {}
    for key, rows in groups.items():
        stats = compute_win_rate(rows)
        result[key] = {**stats, "reliable": stats["total"] >= MIN_SAMPLE_FOR_RELIABLE_HIT_RATE}
    return result


def compute_daily_circuit_breaker(resolved_today: list[dict], max_loss_count: int, max_loss_r: float) -> dict:
    """每日虧損斷路器：今天（db.get_resolved_today 篩出來的當天已結算訊號，格式跟
    get_resolved_trades_for_kelly 一致）有沒有觸發「建議停止交易」。

    兩個獨立門檻，任一個先達到就觸發（保守起見，不用等兩項都超標）：
    - max_loss_count：今天觸及停損（hit_sl）的次數達到這個數字。
    - max_loss_r：今天已結算訊號的 R 倍數加總（贏的算實際獲利倍數、輸的固定算 -1R，
      跟 fee_calc/backtest.py 同一套算法）低於這個值——這個值本身應該是負數（例如 -5.0）。

    max_loss_count <= 0 或 max_loss_r >= 0 代表使用者關閉了對應那一項門檻（不會誤觸發、
    也不會因為設定成 0 這種邊界值而動不動就觸發）。

    回傳 {"active": bool, "reason": str|None, "loss_count": int, "total_r": float}——
    total_r/loss_count 就算沒觸發也會回傳，前端可以拿來做「今日戰績」的顯示，不是只有
    觸發時才有數字。"""
    loss_count = sum(1 for r in resolved_today if r["resolution"] == "hit_sl")

    total_r = 0.0
    for r in resolved_today:
        risk = abs(r["entry_price"] - r["stop_loss"])
        if risk <= 0:
            continue
        if r["resolution"] == "hit_sl":
            total_r -= 1.0
        else:
            reward = abs(r["resolution_price"] - r["entry_price"])
            total_r += reward / risk
    total_r = round(total_r, 3)

    if max_loss_count > 0 and loss_count >= max_loss_count:
        return {
            "active": True,
            "reason": f"今天已經觸及停損 {loss_count} 次（達到上限 {max_loss_count} 次），累積R倍數 {total_r}，建議停止交易、等明天重新評估。",
            "loss_count": loss_count,
            "total_r": total_r,
        }
    if max_loss_r < 0 and total_r <= max_loss_r:
        return {
            "active": True,
            "reason": f"今天已結算訊號的累積R倍數是 {total_r}（低於上限 {max_loss_r}R），建議停止交易、等明天重新評估。",
            "loss_count": loss_count,
            "total_r": total_r,
        }
    return {"active": False, "reason": None, "loss_count": loss_count, "total_r": total_r}


def compute_portfolio_exposure(open_signals: list[dict]) -> dict:
    """目前所有「還沒結算」的訊號（db.get_open_signals() 的格式），看得到「現在同時開著
    幾筆」的曝險總覽——每日虧損斷路器算的是「今天已經發生的」，這個算的是「現在正在
    承受的」，是互補的兩個時間視角。

    刻意不假裝知道每筆訊號實際下單的部位大小——本系統不碰真實下單，只有
    position_sizing.py 的凱利公式試算，實際部位多大是使用者自己決定的——所以用最保守的
    假設：每筆訊號都當作同一份風險單位，「同時開著幾筆」本身就是曝險的近似值：3 筆同時
    開著，不管各自賺賠多少，都代表同時承擔 3 份風險，不是分散成互相獨立的 3 份小風險。

    「同方向集中度提醒」也刻意用最簡單、最誠實的規則：不是真正算 Pearson 相關係數（那
    需要額外抓每對商品的歷史報酬率序列，多一層複雜度跟 API 成本），而是老實提醒「同
    方向的未結算訊號數 ≥ 2」——加密貨幣主流幣普遍高度連動，同方向的部位本來就不是真正
    分散的風險。這不是嚴謹的統計相關係數，只是方向性的曝險集中度警訊，函式本身跟前端
    顯示都會講清楚這個侷限，不假裝比實際上更精確。

    回傳 {"total_open","long_count","short_count","concentration_warning"}
    （警訊沒觸發時 concentration_warning 是 None）。"""
    long_count = sum(1 for s in open_signals if s["signal_type"] == "long")
    short_count = sum(1 for s in open_signals if s["signal_type"] == "short")
    total_open = long_count + short_count

    concentration_warning = None
    if long_count >= 2:
        concentration_warning = (
            f"目前有 {long_count} 筆做多訊號同時進行中，加密貨幣主流幣普遍高度連動，"
            "同方向部位是疊加曝險、不是真正分散——這不是嚴謹的統計相關係數，只是方向性提醒。"
        )
    elif short_count >= 2:
        concentration_warning = (
            f"目前有 {short_count} 筆做空訊號同時進行中，加密貨幣主流幣普遍高度連動，"
            "同方向部位是疊加曝險、不是真正分散——這不是嚴謹的統計相關係數，只是方向性提醒。"
        )

    return {
        "total_open": total_open,
        "long_count": long_count,
        "short_count": short_count,
        "concentration_warning": concentration_warning,
    }


def compute_exposure_gate(total_open: int, max_open_positions: int) -> dict:
    """曝險上限關卡：現在同時開著的未結算訊號數（total_open，來自
    compute_portfolio_exposure）達到使用者自訂上限時，攔截「新」訊號——不是因為這筆新
    訊號本身技術面/新聞面不好，是帳戶整體已經同時承擔夠多份風險，不該再疊加。

    跟每日虧損斷路器（compute_daily_circuit_breaker）是互補的兩層 portfolio-level 關卡：
    斷路器看「今天已經發生的虧損」（事後、時間軸角度），這個看「現在正在承擔的部位數」
    （當下、部位數量角度）——一個帳戶可能今天還沒虧錢（斷路器沒觸發），但同時開了一堆
    部位，新訊號一樣該被這道關卡攔下來。

    max_open_positions <= 0 代表關閉這道關卡（不會誤觸發，也不會因為設成 0 這種邊界值
    就動不動觸發）。

    回傳 {"active": bool, "reason": str|None}——刻意跟 compute_daily_circuit_breaker
    同一種形狀，brain.fuse() 可以用一模一樣的方式套用兩者。"""
    if max_open_positions <= 0:
        return {"active": False, "reason": None}
    if total_open >= max_open_positions:
        return {
            "active": True,
            "reason": (
                f"目前同時有 {total_open} 筆未結算訊號，已達自訂曝險上限 {max_open_positions} 筆，"
                "帳戶整體風險已經足夠，新訊號先不建議加碼，等既有部位結算後再評估。"
            ),
        }
    return {"active": False, "reason": None}


def compute_direction_concentration_gate(same_direction_count: int, max_same_direction: int) -> dict:
    """同方向曝險關卡（可選，預設關閉）：同一個方向（多或空）的未結算訊號數達到使用者
    自訂上限時，攔截「這個方向」的新訊號——跟 compute_exposure_gate（看總數，不分方向）
    互補：那個關卡看「帳戶整體同時開了幾筆」，這個看「同一個方向是不是已經疊加太多趟
    同質曝險」。

    `compute_portfolio_exposure` 原本就有「同方向集中度提醒」（`concentration_warning`），
    但那只是文字警告、不會真的攔截新訊號——這個函式讓在意這件事的使用者可以把提醒升級
    成實際攔截，跟每日虧損斷路器／曝險上限關卡走同一套「可選、預設關閉、達門檻就攔」的
    設計。加密貨幣主流幣普遍高度連動，同方向部位下跌時容易一起虧，這不是嚴謹的統計相關
    係數，只是方向性的曝險集中度風控（呼叫端跟前端顯示都要講清楚這個侷限，跟
    `compute_portfolio_exposure` 的提醒文字一致）。

    `same_direction_count` 是這個方向（多或空，由呼叫端依據新訊號的方向自己決定要傳
    `long_count` 還是 `short_count` 進來，見 `compute_portfolio_exposure` 的回傳）；
    `max_same_direction <= 0` 代表關閉這道關卡（跟 compute_exposure_gate 同樣的慣例，
    不會誤觸發，也不會因為設成 0 這種邊界值就動不動觸發）。

    回傳 {"active": bool, "reason": str|None}——跟其餘關卡同一種形狀，brain.fuse() 用
    一樣的方式套用。"""
    if max_same_direction <= 0:
        return {"active": False, "reason": None}
    if same_direction_count >= max_same_direction:
        return {
            "active": True,
            "reason": (
                f"目前已經有 {same_direction_count} 筆同方向的未結算訊號，達到自訂上限 "
                f"{max_same_direction} 筆——加密貨幣主流幣普遍高度連動，同方向部位是疊加同質"
                "曝險、不是真正分散（不是嚴謹的統計相關係數，只是方向性提醒），新訊號先不"
                "建議同方向加碼，等既有部位結算後再評估。"
            ),
        }
    return {"active": False, "reason": None}


def compute_volatility_gate(amplitude_pct: float | None, max_amplitude_pct: float) -> dict:
    """波動風控關卡：這檔商品的 24h 振幅過大時攔截成警告——不是技術面/新聞面不好，是波動
    太劇烈的商品容易出現插針、滑價，極端行情下流動性也可能瞬間變差。20 EMA + 盒子突破
    這套策略是為「正常」波動幅度設計、拿歷史資料驗證過參數，波動極端偏離正常範圍時，
    驗證過的參數不見得還適用，值得提醒使用者格外謹慎。

    跟商品篩選階段的 MIN_AMPLITUDE_PCT（見 okx_client.screen_active_instruments）方向
    相反：那個濾掉「太安靜」（振幅太小、雜訊多、不值得分析）的商品，這個濾掉「太劇烈」
    的商品，兩個門檻搭配起來才是「波動要落在一個合理區間」的完整篩選——只設下限、
    不設上限的話，遇到單日暴漲暴跌 50% 的極端行情一樣會照常產生訊號，不是使用者想要的。

    max_amplitude_pct <= 0 代表關閉這道關卡；amplitude_pct 是 None（例如查不到資料）
    優雅放行、不誤攔截。

    回傳 {"active": bool, "reason": str|None}，跟另外兩道 portfolio-level 關卡同一種
    形狀，方便 brain.fuse() 統一套用。"""
    if max_amplitude_pct <= 0 or amplitude_pct is None:
        return {"active": False, "reason": None}
    if amplitude_pct >= max_amplitude_pct:
        return {
            "active": True,
            "reason": (
                f"24h 振幅達 {amplitude_pct}%（超過門檻 {max_amplitude_pct}%），波動過於劇烈，"
                "容易出現插針/滑價，本策略是為正常波動幅度設計驗證，建議謹慎評估、縮小部位或觀望。"
            ),
        }
    return {"active": False, "reason": None}


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

    # 15b) compute_pattern_hit_rates -- 同一個標籤累計、不同標籤各自分組，reliable 門檻正確套用
    pattern_rows = (
        [{"resolution": "hit_tp1", "detected_patterns": ["gap_breakout"]}] * 3
        + [{"resolution": "hit_sl", "detected_patterns": ["gap_breakout"]}] * 2  # gap_breakout 共 5 筆，3 勝 2 敗
        + [{"resolution": "hit_tp1", "detected_patterns": ["break_previous_high", "gap_breakout"]}]  # 同時掛兩個標籤，各自累計
        + [{"resolution": "hit_sl", "detected_patterns": []}]  # 沒有任何標籤 -> 不進任何一組
    )
    pattern_stats = compute_pattern_hit_rates(pattern_rows)
    gap_stats = next(p for p in pattern_stats if p["pattern_key"] == "gap_breakout")
    check("pattern hit rate: gap_breakout accumulates across all rows carrying that tag (5 wins across dual-tag row too)",
          (gap_stats["total"], gap_stats["wins"], gap_stats["losses"]), (6, 4, 2))
    check("pattern hit rate: gap_breakout reliable (6 >= 5 sample threshold)", gap_stats["reliable"], True)
    bph_stats = next(p for p in pattern_stats if p["pattern_key"] == "break_previous_high")
    check("pattern hit rate: break_previous_high only counted from the dual-tag row (1 sample)", bph_stats["total"], 1)
    check("pattern hit rate: break_previous_high unreliable (1 < 5 sample threshold)", bph_stats["reliable"], False)
    check("pattern hit rate: sorted by sample size descending (gap_breakout first)", pattern_stats[0]["pattern_key"], "gap_breakout")
    check("pattern hit rate: rows with no tags at all don't create a phantom group", len(pattern_stats), 2)

    # 15c) compute_pattern_hit_rates -- 完全沒有歷史紀錄 -> 空清單，不是報錯
    check("pattern hit rate: no resolved rows -> empty list", compute_pattern_hit_rates([]), [])

    # 15d) compute_decision_hit_rates -- 四組固定都要出現，就算某組完全沒有樣本
    decision_rows = [
        {"resolution": "hit_tp1", "user_decision": "approved"},
        {"resolution": "hit_tp1", "user_decision": "approved"},
        {"resolution": "hit_sl", "user_decision": "approved"},
        {"resolution": "hit_sl", "user_decision": "rejected"},
        {"resolution": "hit_tp1", "user_decision": None},  # 沒表態 -> 歸進 no_decision
    ]
    decision_stats = compute_decision_hit_rates(decision_rows)
    check("decision hit rate: all four groups always present", set(decision_stats.keys()), {"approved", "watching", "rejected", "no_decision"})
    check("decision hit rate: approved group tallies correctly (2 wins, 1 loss)",
          (decision_stats["approved"]["wins"], decision_stats["approved"]["losses"]), (2, 1))
    check("decision hit rate: untagged rows fall into no_decision", decision_stats["no_decision"]["total"], 1)
    check("decision hit rate: watching group has zero samples but is still present (not missing)", decision_stats["watching"]["total"], 0)
    check("decision hit rate: zero-sample group has win_rate_pct None (not a misleading 0%)", decision_stats["watching"]["win_rate_pct"], None)
    check("decision hit rate: zero-sample group is unreliable", decision_stats["watching"]["reliable"], False)

    # 15e) compute_decision_hit_rates -- 完全沒有歷史紀錄 -> 四組都是空的，不是報錯
    empty_decision_stats = compute_decision_hit_rates([])
    check("decision hit rate: no resolved rows -> all four groups still present with zero samples",
          all(g["total"] == 0 for g in empty_decision_stats.values()), True)

    # 16) compute_daily_circuit_breaker -- 今天連續 3 次停損（達到次數上限）-> 觸發
    losses_only = [
        {"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_sl", "resolution_price": 95.0},
        {"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_sl", "resolution_price": 95.0},
        {"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_sl", "resolution_price": 95.0},
    ]
    breaker = compute_daily_circuit_breaker(losses_only, max_loss_count=3, max_loss_r=-999.0)
    check("3 losses hits max_loss_count=3 -> active", breaker["active"], True)
    check("loss_count counted correctly", breaker["loss_count"], 3)
    check("total_r is -3.0 (three -1R losses)", breaker["total_r"], -3.0)

    # 17) 還沒到次數上限 -> 不觸發
    two_losses = losses_only[:2]
    check("2 losses below max_loss_count=3 -> inactive",
          compute_daily_circuit_breaker(two_losses, max_loss_count=3, max_loss_r=-999.0)["active"], False)

    # 18) 累積 R 倍數門檻：次數沒到但虧損倍數夠大一樣觸發（hit_sl 固定算 -1R，用累積
    # 多筆達到 R 門檻來模擬）
    accumulating_losses = [
        {"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_sl", "resolution_price": 95.0},
        {"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_sl", "resolution_price": 95.0},
    ]
    breaker_by_r = compute_daily_circuit_breaker(accumulating_losses, max_loss_count=999, max_loss_r=-1.5)
    check("R threshold triggers even though loss_count threshold not reached", breaker_by_r["active"], True)
    check("R threshold reason mentions total_r", "-2.0" in breaker_by_r["reason"], True)

    # 19) 有贏有輸，R倍數還在正常範圍內 -> 不觸發
    mixed_ok = [
        {"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_tp1", "resolution_price": 107.5},  # +1.5R
        {"entry_price": 100.0, "stop_loss": 95.0, "resolution": "hit_sl", "resolution_price": 95.0},     # -1R
    ]
    breaker_ok = compute_daily_circuit_breaker(mixed_ok, max_loss_count=3, max_loss_r=-5.0)
    check("healthy day (net positive R) -> inactive", breaker_ok["active"], False)
    check("total_r reflects net (+1.5 - 1 = 0.5)", breaker_ok["total_r"], 0.5)

    # 20) 兩項門檻都關閉（max_loss_count<=0, max_loss_r>=0）-> 永遠不觸發
    check("both thresholds disabled -> never active",
          compute_daily_circuit_breaker(losses_only, max_loss_count=0, max_loss_r=0.0)["active"], False)

    # 21) 今天完全沒有已結算訊號 -> 不觸發，數字歸零
    empty_day = compute_daily_circuit_breaker([], max_loss_count=3, max_loss_r=-5.0)
    check("no resolved trades today -> inactive", empty_day["active"], False)
    check("no resolved trades today -> total_r is 0.0", empty_day["total_r"], 0.0)

    # 22) categorize_failure_reason -- 各種失效原因字串反推出正確的分類代碼
    check(
        "fast reversal reason -> fake_breakout category",
        categorize_failure_reason(classify_failure_reason({"box_high": 105, "box_low": 100, "ema": 95, "entry_price": 106}, bars_to_sl=1)),
        ["fake_breakout"],
    )
    check(
        "narrow box reason -> narrow_consolidation category",
        categorize_failure_reason(classify_failure_reason({"box_high": 100.5, "box_low": 100, "ema": 90, "entry_price": 101}, bars_to_sl=10)),
        ["narrow_consolidation"],
    )
    check(
        "ema edge reason -> weak_trend_confirmation category",
        categorize_failure_reason("進場當下價格離 20 EMA 只有 0.10%，趨勢過濾條件在邊緣，訊號強度本來就偏弱。"),
        ["weak_trend_confirmation"],
    )
    check(
        "fallback reason -> unclear category",
        categorize_failure_reason("找不到明顯的結構性弱點，可能單純是短期雜訊或整體市場氣氛轉變，不代表策略邏輯本身有誤。"),
        ["unclear"],
    )
    check("None failure_reason -> empty list (nothing to recommend)", categorize_failure_reason(None), [])
    check("empty string failure_reason -> empty list", categorize_failure_reason(""), [])

    # 23) 同時符合多種型態的複合理由字串 -> 回傳多個分類代碼
    combo_reason = "突破後 1~2 根 K 線內就立刻反轉觸及停損，動能沒有延續，很可能是插針假突破。 盤整盒子過窄（僅 0.50%），突破後波動容易被放大，雜訊很容易就觸發停損。"
    check(
        "combined reason -> both categories present",
        categorize_failure_reason(combo_reason),
        ["fake_breakout", "narrow_consolidation"],
    )

    # 24) compute_portfolio_exposure -- 沒有任何未結算訊號
    check(
        "no open signals -> zeroed out, no warning",
        compute_portfolio_exposure([]),
        {"total_open": 0, "long_count": 0, "short_count": 0, "concentration_warning": None},
    )

    # 25) 只有 1 筆做多 -> 不觸發集中度警訊
    single_long = [{"signal_type": "long"}]
    result_single = compute_portfolio_exposure(single_long)
    check("single open long -> no concentration warning", result_single["concentration_warning"], None)
    check("single open long -> counts correct", (result_single["total_open"], result_single["long_count"]), (1, 0 + 1))

    # 26) 2 筆同方向（做多）-> 觸發集中度警訊
    two_longs = [{"signal_type": "long"}, {"signal_type": "long"}]
    result_two_long = compute_portfolio_exposure(two_longs)
    check("2 open longs -> concentration warning triggered", result_two_long["concentration_warning"] is not None, True)
    check("2 open longs -> warning mentions count", "2 筆做多" in result_two_long["concentration_warning"], True)

    # 27) 2 筆同方向（做空）-> 對稱情境也觸發
    two_shorts = [{"signal_type": "short"}, {"signal_type": "short"}]
    result_two_short = compute_portfolio_exposure(two_shorts)
    check("2 open shorts -> concentration warning triggered", "2 筆做空" in result_two_short["concentration_warning"], True)

    # 28) 1 做多 + 1 做空（互相對沖方向，各自都沒到 2）-> 不觸發，但 total_open 正確累加
    mixed_directions = [{"signal_type": "long"}, {"signal_type": "short"}]
    result_mixed_dir = compute_portfolio_exposure(mixed_directions)
    check("1 long + 1 short -> no concentration warning (neither direction hits 2)", result_mixed_dir["concentration_warning"], None)
    check("1 long + 1 short -> total_open is 2", result_mixed_dir["total_open"], 2)

    # 29) compute_exposure_gate -- 關閉這道關卡（<=0）永遠不觸發，不管 total_open 多大
    check("exposure gate disabled (max<=0) -> never active", compute_exposure_gate(999, 0)["active"], False)
    check("exposure gate disabled (negative max) -> never active", compute_exposure_gate(999, -1)["active"], False)

    # 30) compute_exposure_gate -- 還沒到上限
    check("exposure gate: below cap -> inactive", compute_exposure_gate(2, 5)["active"], False)

    # 31) compute_exposure_gate -- 剛好到達上限（>=，邊界含入）
    at_cap = compute_exposure_gate(5, 5)
    check("exposure gate: exactly at cap -> active (boundary inclusive)", at_cap["active"], True)
    check("exposure gate: reason mentions counts", "5" in at_cap["reason"], True)

    # 32) compute_exposure_gate -- 超過上限
    check("exposure gate: above cap -> active", compute_exposure_gate(8, 5)["active"], True)

    # 32b) compute_direction_concentration_gate -- 關閉這道關卡（<=0）永遠不觸發，不管
    # 同方向數量多大（跟 compute_exposure_gate 同樣的邊界慣例）
    check("direction gate disabled (max<=0) -> never active", compute_direction_concentration_gate(999, 0)["active"], False)
    check("direction gate disabled (negative max) -> never active", compute_direction_concentration_gate(999, -1)["active"], False)

    # 32c) compute_direction_concentration_gate -- 還沒到上限
    check("direction gate: below cap -> inactive", compute_direction_concentration_gate(1, 3)["active"], False)

    # 32d) compute_direction_concentration_gate -- 剛好到達上限（>=，邊界含入）
    dir_at_cap = compute_direction_concentration_gate(3, 3)
    check("direction gate: exactly at cap -> active (boundary inclusive)", dir_at_cap["active"], True)
    check("direction gate: reason mentions the count", "3" in dir_at_cap["reason"], True)

    # 32e) compute_direction_concentration_gate -- 超過上限
    check("direction gate: above cap -> active", compute_direction_concentration_gate(5, 3)["active"], True)

    # 32f) compute_direction_concentration_gate -- 長短兩個方向各自獨立算，不會互相汙染
    # （多方 3 筆達標觸發，空方 0 筆不該被連帶觸發——呼叫端會各自傳入各自的計數）
    check("direction gate: long-side count doesn't leak into short-side check", compute_direction_concentration_gate(0, 3)["active"], False)

    # 33) compute_volatility_gate -- 關閉這道關卡（<=0）永遠不觸發
    check("volatility gate disabled (max<=0) -> never active", compute_volatility_gate(50.0, 0)["active"], False)

    # 34) compute_volatility_gate -- 查不到振幅資料（None）優雅放行，不誤攔截
    check("volatility gate: amplitude_pct=None -> inactive (no false trigger)", compute_volatility_gate(None, 20.0)["active"], False)

    # 35) compute_volatility_gate -- 正常波動範圍內
    check("volatility gate: normal amplitude -> inactive", compute_volatility_gate(6.0, 20.0)["active"], False)

    # 36) compute_volatility_gate -- 剛好在門檻邊界（>=，邊界含入）
    at_vol_cap = compute_volatility_gate(20.0, 20.0)
    check("volatility gate: exactly at threshold -> active (boundary inclusive)", at_vol_cap["active"], True)
    check("volatility gate: reason mentions the amplitude value", "20.0" in at_vol_cap["reason"], True)

    # 37) compute_volatility_gate -- 明顯超過門檻
    check("volatility gate: far above threshold -> active", compute_volatility_gate(45.0, 20.0)["active"], True)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
