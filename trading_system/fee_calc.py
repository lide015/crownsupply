"""當沖手續費試算：把 strategy.py 算出來的「風報比」（reward : risk）換算成扣掉「來回
手續費」之後才是真正到手的「淨盈虧比」。

為什麼需要這個：策略的停損固定設在盤整盒子中線，盒子本身可能很窄（尤其振幅剛好卡在
篩選門檻邊緣的商品），這種情況下「停利1 = 停損距離 x 1.5」算出來的風報比數字雖然
好看，但當沖進出場通常都用市價單（Taker）搶時間，一來一回的手續費是固定的百分比，
盒子越窄，手續費佔目標獲利的比例就越可觀——極端情況下甚至可能吃光了停利1那段的
全部利潤，變成「看對方向也賺不到錢」。這裡把手續費算進去，回傳「淨」盈虧比，讓使用者
知道這筆訊號真正到手的風報比是多少，而不是只看帳面上乾淨的技術面數字。

假設進出場都用 Taker（市價單）：當沖搶進搶出最常見的下單方式，比全部用 Maker（限價單）
更保守估計，不會低估手續費成本。round_trip = 開倉 + 平倉兩趟 Taker 費率。
"""

ROUND_TRIP_LEGS = 2  # 開倉 + 平倉


def compute_fee_adjusted_rr(entry_price: float, stop_loss: float, take_profit: float, taker_fee_pct: float) -> dict | None:
    """entry_price/stop_loss/take_profit 皆為正數價格；taker_fee_pct 是單邊 Taker 手續費率
    （%），例如 OKX 永續合約預設約 0.05 代表 0.05%。

    手續費用「來回兩趟都吃 Taker」估計：
    - 停利那段：目標獲利（gross_reward_pct）扣掉來回手續費才是淨獲利（net_reward_pct）。
    - 停損那段：就算方向看錯出場，來回手續費一樣要付，所以真正承受的虧損
      （net_risk_pct）是「停損距離 + 來回手續費」，不是只有停損距離本身。

    net_rr = net_reward_pct / net_risk_pct——這才是這筆交易真正到手的盈虧比，不是帳面上
    乾淨的技術面風報比。

    entry_price <= 0 是防呆（理論上不該發生，商品報價一定是正數），回傳 None。
    """
    if entry_price <= 0:
        return None

    round_trip_fee_pct = taker_fee_pct * ROUND_TRIP_LEGS
    gross_reward_pct = abs(take_profit - entry_price) / entry_price * 100.0
    gross_risk_pct = abs(entry_price - stop_loss) / entry_price * 100.0

    net_reward_pct = gross_reward_pct - round_trip_fee_pct
    net_risk_pct = gross_risk_pct + round_trip_fee_pct
    net_rr = round(net_reward_pct / net_risk_pct, 2) if net_risk_pct > 0 else None
    fee_eats_pct = round(min(round_trip_fee_pct / gross_reward_pct * 100.0, 999.0), 1) if gross_reward_pct > 0 else None

    return {
        "gross_reward_pct": round(gross_reward_pct, 3),
        "gross_risk_pct": round(gross_risk_pct, 3),
        "round_trip_fee_pct": round(round_trip_fee_pct, 3),
        "net_reward_pct": round(net_reward_pct, 3),
        "net_risk_pct": round(net_risk_pct, 3),
        "net_rr": net_rr,
        "fee_eats_pct": fee_eats_pct,
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

    # 1) 一般情境：entry=100, stop=95（risk 5%）, tp1=107.5（reward 7.5%）, taker=0.05%
    # round_trip = 0.1%；net_reward = 7.5-0.1=7.4；net_risk = 5+0.1=5.1；net_rr = 7.4/5.1 ≈ 1.45
    r = compute_fee_adjusted_rr(100.0, 95.0, 107.5, 0.05)
    check("gross_reward_pct", r["gross_reward_pct"], 7.5)
    check("gross_risk_pct", r["gross_risk_pct"], 5.0)
    check("round_trip_fee_pct", r["round_trip_fee_pct"], 0.1)
    check("net_reward_pct", r["net_reward_pct"], 7.4)
    check("net_risk_pct", r["net_risk_pct"], 5.1)
    check("net_rr ~1.45", r["net_rr"], round(7.4 / 5.1, 2))
    check("fee_eats_pct ~1.3%", r["fee_eats_pct"], round(0.1 / 7.5 * 100.0, 1))

    # 2) 做空同理（方向無關，用絕對距離）
    r_short = compute_fee_adjusted_rr(100.0, 105.0, 92.5, 0.05)
    check("short gross_reward_pct", r_short["gross_reward_pct"], 7.5)
    check("short gross_risk_pct", r_short["gross_risk_pct"], 5.0)

    # 3) 盒子極窄的退化情境：reward 只有 0.15%，來回手續費 0.1% 幾乎吃光獲利
    thin = compute_fee_adjusted_rr(100.0, 99.9, 100.15, 0.05)
    check("thin setup net_reward barely positive", thin["net_reward_pct"], round(0.15 - 0.1, 3))
    check("thin setup fee_eats most of reward", thin["fee_eats_pct"] > 60.0, True)

    # 4) 手續費吃光全部獲利甚至倒虧：reward 0.05% < 來回手續費 0.1% -> net_reward 為負
    trap = compute_fee_adjusted_rr(100.0, 99.9, 100.05, 0.05)
    check("fee trap -> negative net_reward", trap["net_reward_pct"] < 0, True)
    check("fee trap -> net_rr also negative", trap["net_rr"] < 0, True)

    # 5) entry_price <= 0 防呆
    check("entry_price <= 0 -> None", compute_fee_adjusted_rr(0.0, 1.0, 2.0, 0.05), None)

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
