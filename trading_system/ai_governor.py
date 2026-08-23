"""背景排程模式下的 AI 用量治理：規則大腦（technical，見 strategy.py／brain.py）每一輪
排程都跑，零額外成本；AI 新聞情緒（見 news_client.py）則不是每輪都問，靠這個模組決定
「這一輪要不要呼叫 AI」，把「自動化」跟「省 token、靠自己大腦分析」這兩個要求同時滿足。

純函式，不碰資料庫／網路／時間——呼叫端（scheduler.py）負責讀寫 db.get_param/set_param
存放跨重啟的每日累計呼叫次數，STATE 存放單次執行期間的連續失敗計數與「上一輪有沒有新
技術訊號」。

只在「背景排程」模式下生效：使用者手動按「立即分析」一律照舊每次都問 AI（見
background.refresh_cycle 的 skip_ai_reason 預設值 None）——那本來就是主動點擊觸發的
單次呼叫，用量已經被點擊次數天然節流，不需要再疊加這裡的限制。
"""

DAY_MS = 86_400_000


def compute_day_bucket(now_ms: int) -> int:
    """回傳「第幾天」（UTC 日曆日，從 epoch 起算的整數天數），當作每日用量計數的分桶鍵。"""
    return now_ms // DAY_MS


def current_daily_count(stored_day: int | None, stored_count: int, now_ms: int) -> int:
    """只讀、不遞增：查「今天」已經呼叫過幾次 AI（還沒真的要呼叫，先查剩餘額度給狀態面板
    用）。存的日期不是今天，代表還沒有任何一次算進今天，回傳 0（不是回傳舊天的計數）。"""
    if stored_day == compute_day_bucket(now_ms):
        return stored_count
    return 0


def next_daily_count(stored_day: int | None, stored_count: int, now_ms: int) -> tuple[int, int]:
    """算出「這次呼叫算進去之後」的 (day_bucket, count)。存的日期跟今天不同代表跨天了，
    計數從 1 重新起算（這次呼叫本身也要算進去）；同一天就是舊計數 +1。"""
    today = compute_day_bucket(now_ms)
    if stored_day != today:
        return today, 1
    return today, stored_count + 1


def should_skip_ai_this_cycle(
    cycle_count: int,
    refresh_every_n_cycles: int,
    has_new_technical_signal: bool,
    calls_today: int,
    daily_cap: int,
    consecutive_failures: int,
    failure_threshold: int,
) -> str | None:
    """回傳這一輪跳過 AI 呼叫的原因字串（人看得懂、可以直接顯示在狀態面板上），或 None
    代表這一輪可以呼叫 AI。判斷順序（前面的條件優先，任一觸發就不再往下看）：

    1. 每日呼叫上限（daily_cap<=0 代表不限制）——最高優先，避免失控燒錢。
    2. AI 連續失敗斷路器（failure_threshold<=0 代表不啟用）——避免對著故障的 API 一直重試。
    3. 這一輪（或見 scheduler.py：其實是「上一輪」）有新技術訊號 -> 一律允許問 AI，
       新訊號的新聞情緒判讀對使用者最有價值，不該被固定週期卡住。
    4. 週期節流：每 N 輪才問一次（N<=1 代表每輪都問，等同於沒有這道節流）。
    """
    if daily_cap > 0 and calls_today >= daily_cap:
        return f"已達每日 AI 呼叫上限（{calls_today}/{daily_cap}），今天剩餘週期只跑規則大腦，不再呼叫 AI"
    if failure_threshold > 0 and consecutive_failures >= failure_threshold:
        return f"AI 連續失敗 {consecutive_failures} 次（達門檻 {failure_threshold}），暫停呼叫，等下一次手動「立即分析」會重置"
    if has_new_technical_signal:
        return None
    if refresh_every_n_cycles <= 1:
        return None
    if cycle_count % refresh_every_n_cycles != 0:
        return (
            f"省 token 週期：規則大腦每輪都跑，AI 新聞情緒每 {refresh_every_n_cycles} 輪才問一次"
            f"（這是第 {cycle_count} 輪，非新訊號、非到期輪）"
        )
    return None


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

    DAY0 = 0
    DAY1 = 1 * DAY_MS

    # 1) compute_day_bucket
    check("compute_day_bucket day 0", compute_day_bucket(0), 0)
    check("compute_day_bucket day 1 start", compute_day_bucket(DAY_MS), 1)
    check("compute_day_bucket mid-day still same bucket", compute_day_bucket(DAY_MS + 3600_000), 1)

    # 2) current_daily_count：只讀，不因為呼叫就遞增
    check("current_daily_count same day returns stored value", current_daily_count(0, 5, 3600_000), 5)
    check("current_daily_count different day returns 0 (not stale count)", current_daily_count(0, 5, DAY_MS + 1000), 0)
    check("current_daily_count no prior record (None) returns 0", current_daily_count(None, 0, 1000), 0)

    # 3) next_daily_count：同一天遞增，跨天歸 1
    check("next_daily_count same day increments", next_daily_count(0, 5, 3600_000), (0, 6))
    check("next_daily_count new day resets to 1 (this call counted)", next_daily_count(0, 47, DAY_MS + 1000), (1, 1))
    check("next_daily_count first-ever call (stored_day=None)", next_daily_count(None, 0, 1000), (0, 1))

    # 4) should_skip_ai_this_cycle：每日上限最高優先
    check(
        "daily cap reached -> skip with cap reason",
        should_skip_ai_this_cycle(3, 3, False, calls_today=48, daily_cap=48, consecutive_failures=0, failure_threshold=3),
        "已達每日 AI 呼叫上限（48/48），今天剩餘週期只跑規則大腦，不再呼叫 AI",
    )
    check(
        "daily_cap=0 disables the cap check",
        should_skip_ai_this_cycle(3, 3, False, calls_today=999, daily_cap=0, consecutive_failures=0, failure_threshold=3),
        None,
    )

    # 5) 連續失敗斷路器
    check(
        "consecutive failures at threshold -> skip",
        should_skip_ai_this_cycle(3, 3, False, calls_today=0, daily_cap=0, consecutive_failures=3, failure_threshold=3),
        "AI 連續失敗 3 次（達門檻 3），暫停呼叫，等下一次手動「立即分析」會重置",
    )
    check(
        "consecutive failures below threshold -> not skipped by this rule",
        should_skip_ai_this_cycle(3, 3, False, calls_today=0, daily_cap=0, consecutive_failures=2, failure_threshold=3),
        None,
    )
    check(
        "failure_threshold=0 disables the circuit breaker",
        should_skip_ai_this_cycle(3, 3, False, calls_today=0, daily_cap=0, consecutive_failures=999, failure_threshold=0),
        None,
    )

    # 6) 新技術訊號一律優先允許，即使還沒到週期節流的整除輪次
    check(
        "new technical signal bypasses the N-cycle throttle",
        should_skip_ai_this_cycle(1, 3, True, calls_today=0, daily_cap=0, consecutive_failures=0, failure_threshold=0),
        None,
    )

    # 7) 週期節流：非整除輪次跳過，整除輪次允許
    check(
        "not-yet-due cycle -> skip with throttle reason",
        should_skip_ai_this_cycle(1, 3, False, calls_today=0, daily_cap=0, consecutive_failures=0, failure_threshold=0),
        "省 token 週期：規則大腦每輪都跑，AI 新聞情緒每 3 輪才問一次（這是第 1 輪，非新訊號、非到期輪）",
    )
    check(
        "due cycle (multiple of N) -> allowed",
        should_skip_ai_this_cycle(3, 3, False, calls_today=0, daily_cap=0, consecutive_failures=0, failure_threshold=0),
        None,
    )
    check(
        "refresh_every_n_cycles<=1 disables the throttle entirely",
        should_skip_ai_this_cycle(1, 1, False, calls_today=0, daily_cap=0, consecutive_failures=0, failure_threshold=0),
        None,
    )
    check(
        "refresh_every_n_cycles=0 also disables the throttle",
        should_skip_ai_this_cycle(5, 0, False, calls_today=0, daily_cap=0, consecutive_failures=0, failure_threshold=0),
        None,
    )

    # 8) 優先順序驗證：每日上限比新訊號優先（就算有新訊號，上限到了一樣要擋）
    check(
        "daily cap overrides even a new technical signal",
        should_skip_ai_this_cycle(3, 3, True, calls_today=48, daily_cap=48, consecutive_failures=0, failure_threshold=3),
        "已達每日 AI 呼叫上限（48/48），今天剩餘週期只跑規則大腦，不再呼叫 AI",
    )
    # 斷路器也比新訊號優先
    check(
        "circuit breaker overrides even a new technical signal",
        should_skip_ai_this_cycle(3, 3, True, calls_today=0, daily_cap=0, consecutive_failures=3, failure_threshold=3),
        "AI 連續失敗 3 次（達門檻 3），暫停呼叫，等下一次手動「立即分析」會重置",
    )

    print(f"\n{_passed}/{_total} tests passed")
    if _passed == _total:
        print("PASS")
    else:
        raise SystemExit(1)
