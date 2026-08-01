import { useState, useEffect, useCallback, useMemo } from "react";
import { LineChart, Line, ResponsiveContainer, YAxis } from "recharts";
import { C, FONT_CSS, pct, num, Tag, SectionHead } from "../shared.jsx";
import Nav from "../Nav.jsx";

/* 通用資產分析頁（台股／美股／大宗商品共用）：抓 /api/analysis + /api/klines，
   跟 CryptoPage 用同一套 RSI/SMC/交易計畫顯示邏輯，只是資料來源換成代表性標的。 */
export default function AnalysisPage({ path, navigate, symbol, title, subtitle }) {
  const [data, setData] = useState(null);
  const [closes, setCloses] = useState(null);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 9000);
      const [analysisRes, klinesRes] = await Promise.all([
        fetch(`/api/analysis?symbol=${symbol}`, { signal: ctrl.signal }),
        fetch(`/api/klines?symbol=${symbol}&days=100`, { signal: ctrl.signal }),
      ]);
      clearTimeout(timer);
      if (!analysisRes.ok || !klinesRes.ok) throw new Error("bad status");
      const analysis = await analysisRes.json();
      const klineRows = await klinesRes.json();
      if (analysis.price == null) throw new Error("no data yet");
      setData(analysis);
      setCloses(klineRows.map((k) => k.close));
      setLive(true);
    } catch {
      setLive(false);
    }
    setLoading(false);
  }, [symbol]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  useEffect(() => {
    const id = setInterval(fetchAll, 60000);
    return () => clearInterval(id);
  }, [fetchAll]);

  const chartData = useMemo(
    () => (closes ? closes.slice(-60).map((v, i) => ({ i, v })) : []),
    [closes]
  );

  const ind = data?.indicators;
  const smcData = data?.smc;
  const tradePlan = data?.trade_plan;

  return (
    <div className="body-tc min-h-screen" style={{ background: C.ink, color: C.paper }}>
      <style>{FONT_CSS}</style>
      <Nav path={path} navigate={navigate} />

      <header className="px-5 pt-8 pb-6 max-w-5xl mx-auto">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="mono text-xs mb-2" style={{ color: C.goldDim }}>
              DAILY・{new Date().toLocaleDateString("zh-TW", { year: "numeric", month: "long", day: "numeric" })}
            </div>
            <h1 className="serif font-black leading-none" style={{ fontSize: "clamp(2.4rem,8vw,3.6rem)", color: C.paper }}>
              {title}
            </h1>
            <p className="mt-2 text-sm" style={{ color: C.dim }}>{subtitle}</p>
          </div>
          <div className="flex items-center gap-2">
            <Tag color={live == null ? C.faint : live ? C.up : C.gold}>
              {loading ? "載入中" : live ? "● 即時數據" : "◦ 尚無資料"}
            </Tag>
            <button
              onClick={fetchAll}
              className="mono text-xs px-2 py-0.5 rounded-sm"
              style={{ border: `1px solid ${C.line}`, color: C.dim }}
            >
              重抓
            </button>
          </div>
        </div>
      </header>

      <main className="px-5 pb-16 max-w-5xl mx-auto space-y-10">
        {/* ── 01 價格走勢 ── */}
        <section>
          <SectionHead no="01" title="價格走勢" sub="本區全程 0 token" />
          <div className="p-3 rounded-md" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
            <div className="flex items-baseline justify-between mb-1">
              <span className="mono text-2xl">
                {data?.price != null ? num(data.price, data.price < 10 ? 2 : 1) : "—"}
              </span>
              <span className="mono text-xs" style={{ color: C.faint }}>近 60 日・本地繪製</span>
            </div>
            <div style={{ height: 100 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <YAxis hide domain={["dataMin", "dataMax"]} />
                  <Line type="monotone" dataKey="v" stroke={C.blue} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            {ind && (
              <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 mono text-xs">
                <div>
                  <span style={{ color: C.faint }}>RSI14 </span>
                  <span style={{ color: ind.rsi14 >= 70 || ind.rsi14 <= 30 ? C.gold : C.paper }}>
                    {ind.rsi14?.toFixed(0) ?? "—"}
                  </span>
                </div>
                <div>
                  <span style={{ color: C.faint }}>均線乖離 </span>
                  <span style={{ color: (ind.ma_bias_pct ?? 0) >= 0 ? C.up : C.down }}>{pct(ind.ma_bias_pct, 2)}</span>
                </div>
                <div><span style={{ color: C.faint }}>年化波動 </span>{ind.ann_vol_pct != null ? `${ind.ann_vol_pct.toFixed(0)}%` : "—"}</div>
                <div>
                  <span style={{ color: C.faint }}>90日回撤 </span>
                  <span style={{ color: C.down }}>{ind.mdd90_pct != null ? `${ind.mdd90_pct.toFixed(1)}%` : "—"}</span>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* ── 02 SMC 市場結構與交易計畫 ── */}
        <section>
          <SectionHead no="02" title="SMC 交易計畫" sub="規則式本地合成，非 AI、非投資建議" />
          <div className="grid md:grid-cols-2 gap-4">
            <div className="p-4 rounded-md" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
              <div className="flex items-center justify-between mb-3">
                <span className="mono text-xs" style={{ color: C.dim }}>市場結構</span>
                <Tag color={smcData?.structure === "bullish" ? C.up : smcData?.structure === "bearish" ? C.down : C.faint}>
                  {smcData?.structure ?? "—"}
                </Tag>
              </div>
              {smcData?.last_event ? (
                <p className="text-sm" style={{ color: C.paper }}>
                  最新 {smcData.last_event.type}：
                  <span style={{ color: smcData.last_event.direction === "bullish" ? C.up : C.down }}>
                    {" "}{smcData.last_event.direction} 突破 {num(smcData.last_event.level, 1)}
                  </span>
                </p>
              ) : (
                <p className="text-xs" style={{ color: C.faint }}>目前無 BOS／CHoCH 事件</p>
              )}
              {smcData?.fvgs?.length > 0 && (
                <div className="mt-3 pt-3 space-y-1" style={{ borderTop: `1px dashed ${C.line}` }}>
                  <div className="mono text-xs mb-1" style={{ color: C.dim }}>近期 FVG（公允價值缺口）</div>
                  {smcData.fvgs.map((f, i) => (
                    <div key={i} className="mono text-xs flex justify-between">
                      <span style={{ color: C.faint }}>{f.day}</span>
                      <span style={{ color: f.direction === "bullish" ? C.up : C.down }}>
                        {f.direction} {num(f.bottom, 1)}–{num(f.top, 1)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="p-4 rounded-md" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
              {!tradePlan?.available ? (
                <p className="text-xs" style={{ color: C.faint }}>資料不足，尚無法產生交易計畫</p>
              ) : (
                <>
                  <div className="flex items-center justify-between mb-2">
                    <Tag color={tradePlan.bias === "bullish" ? C.up : tradePlan.bias === "bearish" ? C.down : C.faint}>
                      {tradePlan.bias}
                    </Tag>
                    <span className="mono text-xs" style={{ color: C.dim }}>
                      評分 {tradePlan.plan_score}/100・預估勝率 {tradePlan.win_rate_pct}%
                    </span>
                  </div>
                  {tradePlan.levels && (
                    <div className="grid grid-cols-3 gap-2 mono text-xs mb-3">
                      <div className="p-2 rounded-sm text-center" style={{ background: C.surface2 }}>
                        <div style={{ color: C.faint }}>SL</div>
                        <div style={{ color: C.down }}>{num(tradePlan.levels.sl, 1)}</div>
                      </div>
                      <div className="p-2 rounded-sm text-center" style={{ background: C.surface2 }}>
                        <div style={{ color: C.faint }}>TP1 (1:1)</div>
                        <div style={{ color: C.up }}>{num(tradePlan.levels.tp1, 1)}</div>
                      </div>
                      <div className="p-2 rounded-sm text-center" style={{ background: C.surface2 }}>
                        <div style={{ color: C.faint }}>TP2 (1:1.5)</div>
                        <div style={{ color: C.up }}>{num(tradePlan.levels.tp2, 1)}</div>
                      </div>
                    </div>
                  )}
                  <ul className="space-y-1 mb-2">
                    {tradePlan.reasons?.map((r, i) => (
                      <li key={i} className="text-xs" style={{ color: C.dim }}>▲ {r}</li>
                    ))}
                  </ul>
                  <p className="mono text-xs" style={{ color: C.faint }}>{tradePlan.disclaimer}</p>
                </>
              )}
            </div>
          </div>
        </section>

        <footer className="pt-2 mono text-xs text-center" style={{ color: C.faint }}>
          節流晨報・{title}・token 為估算值・所有內容僅供教育用途
        </footer>
      </main>
    </div>
  );
}
