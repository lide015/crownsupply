"""倉位計算機：根據帳戶資金、單筆風險%、進場價、停損價，算出這筆交易該用多大部位，
把「輸家先設好停損金額」的紀律，變成下單前就能算出來的具體數字，而不是憑感覺下單。

純函式、零網路呼叫——跟 strategy.py／brain.py 同樣的設計。前端呼叫 POST /api/v1/position-size
（見 app.py）取得計算結果，公式只寫一份在這裡，避免前後端各寫一份公式、日後改一邊忘記改
另一邊而兜不起來。
"""


def calc_position_size(
    account_balance: float,
    risk_pct: float,
    entry_price: float,
    stop_loss_price: float,
    leverage_cap: float | None = None,
) -> dict | None:
    """回傳 None 代表輸入不合理（資金/風險%/價格 <= 0，或進場價等於停損價無法算風險）。

    position_size：這筆交易該買/賣多少「單位」的標的（例如多少顆 BTC），不是合約張數。
    position_notional：這個部位的美元（USDT）市值 = position_size * entry_price。
    required_margin_at_max_leverage：如果用 leverage_cap 倍槓桿，需要準備多少保證金
      才撐得起這個部位（沒給 leverage_cap 就不算這欄）。
    """
    if account_balance <= 0 or risk_pct <= 0 or entry_price <= 0 or stop_loss_price <= 0:
        return None
    price_diff = abs(entry_price - stop_loss_price)
    if price_diff == 0:
        return None

    risk_amount = account_balance * risk_pct / 100.0
    position_size = risk_amount / price_diff
    position_notional = position_size * entry_price

    result = {
        "risk_amount": round(risk_amount, 2),
        "position_size": position_size,
        "position_notional": round(position_notional, 2),
        "stop_distance_pct": round(price_diff / entry_price * 100.0, 4),
    }
    if leverage_cap and leverage_cap > 0:
        result["required_margin_at_max_leverage"] = round(position_notional / leverage_cap, 2)
        result["implied_leverage"] = round(position_notional / risk_amount, 2) if risk_amount else None
    return result


def calc_reward_at_target(position_size: float, entry_price: float, target_price: float) -> float:
    """算這個部位在到達某個目標價（例如 TP1/TP2）時的獲利金額（USDT）。"""
    return round(position_size * abs(target_price - entry_price), 2)


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

    # 1) 基本公式：帳戶 10000 USDT、風險 1%、進場 100、停損 95 -> 風險金額 100、部位 20 單位
    r = calc_position_size(10000, 1.0, 100.0, 95.0)
    check("risk_amount = balance * risk_pct%", r["risk_amount"], 100.0)
    check("position_size = risk_amount / price_diff", r["position_size"], 20.0)
    check("position_notional = position_size * entry_price", r["position_notional"], 2000.0)
    check("stop_distance_pct", r["stop_distance_pct"], 5.0)

    # 2) 放空方向（停損在進場價之上）算法相同，用絕對值差
    r_short = calc_position_size(10000, 1.0, 100.0, 105.0)
    check("short direction uses abs price diff", r_short["position_size"], 20.0)

    # 3) 給 leverage_cap 才會多算保證金與隱含槓桿
    r_lev = calc_position_size(10000, 1.0, 100.0, 95.0, leverage_cap=10)
    check("required_margin_at_max_leverage", r_lev["required_margin_at_max_leverage"], 200.0)
    check("implied_leverage = notional / risk_amount", r_lev["implied_leverage"], 20.0)
    check("no leverage_cap -> key absent", "required_margin_at_max_leverage" in r, False)

    # 4) 不合理輸入一律回傳 None，不讓前端拿到誤導性的數字
    check("zero balance -> None", calc_position_size(0, 1.0, 100.0, 95.0), None)
    check("zero risk_pct -> None", calc_position_size(10000, 0, 100.0, 95.0), None)
    check("entry == stop_loss -> None (無法算風險)", calc_position_size(10000, 1.0, 100.0, 100.0), None)
    check("negative entry_price -> None", calc_position_size(10000, 1.0, -100.0, 95.0), None)

    # 5) 目標價獲利試算
    check("calc_reward_at_target", calc_reward_at_target(20.0, 100.0, 110.0), 200.0)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
