import { useState, useEffect, useMemo, useCallback } from "react";
import { LineChart, Line, ResponsiveContainer, YAxis } from "recharts";
import { C, FONT_CSS, pct, num, Tag, TokenStamp, SectionHead } from "../shared.jsx";
import Nav from "../Nav.jsx";

const estTokens = (s) => Math.max(1, Math.ceil((s || "").length / 2.3));

/* ── 本地技術運算（0 token）── */
const sma = (arr, n) =>
  arr.length < n ? null : arr.slice(-n).reduce((a, b) => a + b, 0) / n;

const rsi = (closes, n = 14) => {
  if (closes.length < n + 1) return null;
  let g = 0, l = 0;
  for (let i = closes.length - n; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    d >= 0 ? (g += d) : (l -= d);
  }
  if (l === 0) return 100;
  return 100 - 100 / (1 + g / l);
};

const annVol = (closes) => {
  if (closes.length < 31) return null;
  const rets = [];
  const seg = closes.slice(-31);
  for (let i = 1; i < seg.length; i++) rets.push(Math.log(seg[i] / seg[i - 1]));
  const m = rets.reduce((a, b) => a + b, 0) / rets.length;
  const v = rets.reduce((a, b) => a + (b - m) ** 2, 0) / (rets.length - 1);
  return Math.sqrt(v) * Math.sqrt(365) * 100;
};

const maxDD = (closes) => {
  let peak = closes[0], dd = 0;
  for (const p of closes) {
    if (p > peak) peak = p;
    dd = Math.min(dd, (p - peak) / peak);
  }
  return dd * 100;
};

/* ── 示範資料（後端無資料時退場用，站點仍可完整運作）── */
const DEMO = {
  quotes: {
    bitcoin: { usd: 96500, usd_24h_change: -2.1 },
    ethereum: { usd: 3420, usd_24h_change: -3.4 },
    solana: { usd: 158, usd_24h_change: -4.8 },
    binancecoin: { usd: 612, usd_24h_change: -1.2 },
  },
  fng: { value: 34, label: "Fear" },
  closes: Array.from({ length: 91 }, (_, i) => {
    const t = i / 90;
    return 88000 + 14000 * Math.sin(t * 5.2) * (1 - t * 0.3) + 9000 * t + ((i * 37) % 13) * 180;
  }),
};

const COIN_META = [
  ["bitcoin", "BTC", "比特幣"],
  ["ethereum", "ETH", "以太幣"],
  ["solana", "SOL", "Solana"],
  ["binancecoin", "BNB", "幣安幣"],
];

/* 後端 symbol（BTC/ETH/SOL/BNB）↔ 前端沿用的 CoinGecko id 命名 */
const SYMBOL_TO_ID = { BTC: "bitcoin", ETH: "ethereum", SOL: "solana", BNB: "binancecoin" };
const quotesFromBackend = (backendQuotes) => {
  const q = {};
  for (const [sym, id] of Object.entries(SYMBOL_TO_ID)) {
    const v = backendQuotes?.[sym];
    if (v) q[id] = { usd: v.usd, usd_24h_change: v.chg24 };
  }
  return q;
};

/* ── 學習室：內建概念卡（0 token）── */
const CARDS = [
  {
    t: "RSI 相對強弱指標",
    def: "以最近 N 期（常用 14）漲幅與跌幅的比值衡量動能，區間 0–100。",
    use: "70 以上視為超買、30 以下視為超賣——但在強趨勢中 RSI 可長期鈍化，超買不等於做空訊號。",
    trap: "常見誤用：把單一 RSI 讀數當進出場依據，而不看它所處的市場結構。",
  },
  {
    t: "均線多空排列",
    def: "短均（如 MA20）在長均（如 MA60）之上為多頭排列，反之為空頭排列。",
    use: "描述趨勢狀態，不預測轉折；乖離幅度可衡量趨勢強度與回歸壓力。",
    trap: "常見誤用：在盤整區反覆被均線交叉來回打臉——均線策略天生付「盤整稅」。",
  },
  {
    t: "年化波動率",
    def: "日報酬標準差 × √365，把日內起伏換算成年尺度，便於跨資產比較。",
    use: "波動率決定倉位大小：同樣的資金風險，高波動資產應配更小的部位。",
    trap: "常見誤用：把低波動當低風險——波動率壓縮往往是劇烈行情的前奏。",
  },
  {
    t: "最大回撤 (MDD)",
    def: "區間內從峰值到谷底的最大跌幅，衡量策略或資產最痛的一段。",
    use: "回本需要的漲幅是非線性的：-50% 需要 +100% 才能回本。控制回撤優先於追求報酬。",
    trap: "常見誤用：只看歷史 MDD 而不設事前的資金管理規則——未來的回撤可以更深。",
  },
  {
    t: "恐懼貪婪指數",
    def: "綜合波動、動能、社群熱度等因子的情緒量表，0（極度恐懼）到 100（極度貪婪）。",
    use: "極端讀數是反向思考的提示，不是自動反向指令；配合結構與資金面才有意義。",
    trap: "常見誤用：情緒指標領先性有限，極端狀態可以持續數週。",
  },
];

/* ── AI 呼叫（單次、壓縮輸入、強制 JSON）── */
async function callAI(system, user) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "claude-sonnet-4-6",
      max_tokens: 1000,
      system,
      messages: [{ role: "user", content: user }],
    }),
  });
  const data = await res.json();
  const text = (data.content || [])
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join("\n");
  return { text, inTok: estTokens(system + user), outTok: estTokens(text) };
}

const parseJSON = (raw) => {
  try {
    return JSON.parse(raw.replace(/```json|```/g, "").trim());
  } catch {
    const m = raw.match(/\{[\s\S]*\}/);
    if (m) {
      try { return JSON.parse(m[0]); } catch { return null; }
    }
    return null;
  }
};

/* ═════════════ 主程式 ═════════════ */
export default function CryptoPage({ path, navigate }) {
  const [quotes, setQuotes] = useState(null);
  const [fng, setFng] = useState(null);
  const [closes, setCloses] = useState(null);
  const [live, setLive] = useState(null); // true=即時 false=示範
  const [loading, setLoading] = useState(true);
  const [wsConnected, setWsConnected] = useState(false);
  const [markets, setMarkets] = useState(null); // 台股／美股／大宗商品期貨
  const [smcData, setSmcData] = useState(null); // M6 選配：SMC 市場結構分析
  const [tradePlan, setTradePlan] = useState(null); // 規則式（非AI）交易計畫合成

  const [gateOn, setGateOn] = useState(true);
  const [gate, setGate] = useState({ absChange: 3, rsiHi: 70, rsiLo: 30, fngLo: 25, fngHi: 75 });

  const [steps, setSteps] = useState([]);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState(null);
  const [ai, setAi] = useState(null);
  const [gateSkipped, setGateSkipped] = useState(false);

  const [ledger, setLedger] = useState([]);
  const BUDGET = 8000;
  const totalTk = ledger.reduce((a, r) => a + r.inTok + r.outTok, 0);

  const [openCard, setOpenCard] = useState(null);
  const [quiz, setQuiz] = useState(null);
  const [quizBusy, setQuizBusy] = useState(false);
  const [showAns, setShowAns] = useState(false);

  /* ── 抓取市場數據（0 token，來自本機後端）── */
  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 9000);
      const [latestRes, klinesRes] = await Promise.all([
        fetch("/api/latest", { signal: ctrl.signal }),
        fetch("/api/klines?symbol=BTC&days=100", { signal: ctrl.signal }),
      ]);
      clearTimeout(timer);
      if (!latestRes.ok || !klinesRes.ok) throw new Error("bad status");
      const latest = await latestRes.json();
      const klineRows = await klinesRes.json();
      if (!latest.quotes) throw new Error("backend has no data yet");
      setQuotes(quotesFromBackend(latest.quotes));
      setFng(latest.fng);
      setCloses(klineRows.map((k) => k.close));
      setMarkets(latest.markets || null);
      setSmcData(latest.smc || null);
      setTradePlan(latest.trade_plan || null);
      setLive(true);
    } catch {
      setQuotes(DEMO.quotes);
      setFng(DEMO.fng);
      setCloses(DEMO.closes);
      setLive(false);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  /* ── WS 訂閱：後端每次快照更新即推播，斷線自動退回 30 秒輪詢 ── */
  useEffect(() => {
    let cancelled = false;
    let retryTimer = null;
    let ws = null;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${window.location.host}/ws`);
      ws.onopen = () => { if (!cancelled) setWsConnected(true); };
      ws.onmessage = (evt) => {
        let data;
        try { data = JSON.parse(evt.data); } catch { return; }
        if (data.type === "heartbeat") return;
        if (data.type === "tick") {
          // M6：OKX 秒級 tick，只更新該幣種的價格／24h 變化，其餘欄位維持上次快照的值
          const id = SYMBOL_TO_ID[data.symbol];
          if (!id) return;
          setQuotes((prev) => ({ ...(prev || {}), [id]: { usd: data.usd, usd_24h_change: data.chg24 } }));
          setLive(true);
          setLoading(false);
          return;
        }
        if (data.quotes) {
          setQuotes(quotesFromBackend(data.quotes));
          setFng(data.fng);
          setMarkets(data.markets || null);
          setSmcData(data.smc || null);
          setTradePlan(data.trade_plan || null);
          setLive(true);
          setLoading(false);
        }
      };
      ws.onclose = () => {
        if (cancelled) return;
        setWsConnected(false);
        retryTimer = setTimeout(connect, 5000);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);

  /* 斷線時退回 30 秒輪詢 /api/latest（含 klines，涵蓋 WS 不推的每小時 K 線更新）*/
  useEffect(() => {
    if (wsConnected) return;
    const id = setInterval(fetchAll, 30000);
    return () => clearInterval(id);
  }, [wsConnected, fetchAll]);

  /* ── 本地指標（隨數據自動計算，0 token）── */
  const metrics = useMemo(() => {
    if (!closes || !quotes) return null;
    const px = closes[closes.length - 1];
    const ma20 = sma(closes, 20);
    const ma60 = sma(closes, 60);
    return {
      px,
      chg24: quotes.bitcoin?.usd_24h_change ?? null,
      chg7: closes.length > 8 ? ((px / closes[closes.length - 8]) - 1) * 100 : null,
      rsi14: rsi(closes),
      ma20, ma60,
      maBias: ma20 && ma60 ? ((ma20 - ma60) / ma60) * 100 : null,
      vol: annVol(closes),
      mdd: maxDD(closes.slice(-90)),
    };
  }, [closes, quotes]);

  /* ── 條件閘門 ── */
  const triggers = useMemo(() => {
    if (!metrics || !fng) return [];
    const t = [];
    if (metrics.chg24 != null && Math.abs(metrics.chg24) >= gate.absChange)
      t.push(`24h 波動 ${pct(metrics.chg24)} ≥ 門檻 ${gate.absChange}%`);
    if (metrics.rsi14 != null && metrics.rsi14 >= gate.rsiHi)
      t.push(`RSI ${metrics.rsi14.toFixed(0)} 進入超買區（≥${gate.rsiHi}）`);
    if (metrics.rsi14 != null && metrics.rsi14 <= gate.rsiLo)
      t.push(`RSI ${metrics.rsi14.toFixed(0)} 進入超賣區（≤${gate.rsiLo}）`);
    if (fng.value <= gate.fngLo) t.push(`情緒指數 ${fng.value} 進入恐懼極端（≤${gate.fngLo}）`);
    if (fng.value >= gate.fngHi) t.push(`情緒指數 ${fng.value} 進入貪婪極端（≥${gate.fngHi}）`);
    return t;
  }, [metrics, fng, gate]);

  /* ── 自動化管線 ── */
  const runPipeline = async () => {
    if (running || !metrics || !fng) return;
    setRunning(true);
    setReport(null);
    setAi(null);
    setGateSkipped(false);

    const base = [
      { id: 1, label: "抓取市場數據", note: "本機後端 /api/latest，純 HTTP", tk: 0 },
      { id: 2, label: "本地技術運算", note: "RSI・均線・波動率・回撤，全在瀏覽器計算", tk: 0 },
      { id: 3, label: "條件閘門判定", note: gateOn ? "無觸發即省略 AI" : "閘門已關閉，一律呼叫", tk: 0 },
      { id: 4, label: "AI 綜合研判", note: "單次呼叫・壓縮輸入・JSON 輸出", tk: null },
      { id: 5, label: "產出晨報", note: "本地排版", tk: 0 },
    ];
    setSteps(base.map((s) => ({ ...s, status: "wait" })));
    const setStep = (id, patch) =>
      setSteps((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));

    setStep(1, { status: "run" });
    await wait(450);
    setStep(1, { status: "done" });

    setStep(2, { status: "run" });
    await wait(550);
    setStep(2, { status: "done" });

    setStep(3, { status: "run" });
    await wait(500);
    const fire = triggers.length > 0 || !gateOn;
    setStep(3, { status: "done", note: fire ? `觸發 ${gateOn ? triggers.length : "—"} 項條件 → 放行` : "無觸發 → 攔下 AI 呼叫" });

    let aiResult = null;
    if (fire) {
      setStep(4, { status: "run" });
      const system =
        "你是嚴謹的市場研究助理。僅輸出 JSON，不要 markdown 圍欄。格式：" +
        '{"summary":"80字內市況綜評","signals":[{"n":"指標名","v":"偏多/偏空/中性","r":"20字內理由"}](最多3項),' +
        '"risk":"40字內當前最大風險","lesson":"針對今日市況的學習重點60字內","quiz":{"q":"一題情境判斷題","a":"40字內解答"}}。' +
        "繁體中文。教育性分析，不構成投資建議，不喊單。";
      const user =
        `BTC 本地計算結果（原始數據已處理完畢，直接研判）：` +
        `價格 $${num(metrics.px)}，24h ${pct(metrics.chg24)}，7d ${pct(metrics.chg7)}；` +
        `RSI14=${metrics.rsi14?.toFixed(0)}；MA20 對 MA60 乖離 ${pct(metrics.maBias, 2)}` +
        `（${metrics.maBias >= 0 ? "多頭排列" : "空頭排列"}）；年化波動率 ${metrics.vol?.toFixed(0)}%；` +
        `90日最大回撤 ${metrics.mdd?.toFixed(1)}%；恐懼貪婪指數 ${fng.value}（${fng.label}）。` +
        `其他 24h：ETH ${pct(quotes.ethereum?.usd_24h_change)}、SOL ${pct(quotes.solana?.usd_24h_change)}、BNB ${pct(quotes.binancecoin?.usd_24h_change)}。` +
        (triggers.length ? `觸發條件：${triggers.join("；")}。` : "（閘門關閉，例行研判。）");
      try {
        const r = await callAI(system, user);
        const parsed = parseJSON(r.text);
        aiResult = parsed || { summary: r.text.slice(0, 200), signals: [], risk: "", lesson: "", quiz: null };
        setLedger((prev) => [...prev, { label: "管線・AI 綜合研判", inTok: r.inTok, outTok: r.outTok, t: new Date() }]);
        setStep(4, { status: "done", tk: r.inTok + r.outTok });
      } catch {
        aiResult = { error: "AI 呼叫失敗，本次僅產出本地報告。" };
        setStep(4, { status: "fail", tk: 0 });
      }
    } else {
      setGateSkipped(true);
      setStep(4, { status: "skip", tk: 0, note: "閘門攔截——今日免費" });
    }

    setStep(5, { status: "run" });
    await wait(400);
    setStep(5, { status: "done" });

    setAi(aiResult);
    setReport({ at: new Date(), triggers: [...triggers], fired: fire });
    setRunning(false);
  };

  /* ── 學習室 AI 出題（單次）── */
  const makeQuiz = async () => {
    if (quizBusy || !metrics || !fng) return;
    setQuizBusy(true);
    setShowAns(false);
    const system =
      '僅輸出 JSON：{"q":"一題情境判斷題（含具體數字情境）","a":"60字內解析"}。繁體中文，教育用途，不給投資建議。';
    const user =
      `以此市況出題：BTC 24h ${pct(metrics.chg24)}、RSI ${metrics.rsi14?.toFixed(0)}、` +
      `均線乖離 ${pct(metrics.maBias, 1)}、情緒 ${fng.value}。考「指標解讀的常見誤用」。`;
    try {
      const r = await callAI(system, user);
      const parsed = parseJSON(r.text);
      setQuiz(parsed || { q: r.text.slice(0, 160), a: "（解析格式異常）" });
      setLedger((prev) => [...prev, { label: "學習室・AI 情境題", inTok: r.inTok, outTok: r.outTok, t: new Date() }]);
    } catch {
      setQuiz({ q: "AI 出題失敗——先用左側 0 token 概念卡複習。", a: "" });
    }
    setQuizBusy(false);
  };

  /* ── 天真做法對照（估算）── */
  const naive = 5 * (4500 + 700); // 每步都丟 90 日原始 K 線 JSON、拆 5 次呼叫
  const saved = totalTk > 0 ? Math.round((1 - totalTk / naive) * 100) : null;

  const gaugePct = Math.min(100, (totalTk / BUDGET) * 100);
  const chartData = useMemo(
    () => (closes ? closes.slice(-60).map((v, i) => ({ i, v })) : []),
    [closes]
  );

  const stStyle = {
    wait: { c: C.faint, s: "待命" },
    run: { c: C.blue, s: "執行中" },
    done: { c: C.up, s: "完成" },
    skip: { c: C.gold, s: "已省略" },
    fail: { c: C.down, s: "失敗" },
  };

  return (
    <div className="body-tc min-h-screen" style={{ background: C.ink, color: C.paper }}>
      <style>{FONT_CSS}</style>
      <Nav path={path} navigate={navigate} />

      {/* ── 報頭 ── */}
      <header className="px-5 pt-8 pb-6 max-w-5xl mx-auto">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="mono text-xs mb-2" style={{ color: C.goldDim }}>
              DAILY・{new Date().toLocaleDateString("zh-TW", { year: "numeric", month: "long", day: "numeric" })}
            </div>
            <h1 className="serif font-black leading-none" style={{ fontSize: "clamp(2.4rem,8vw,3.6rem)", color: C.paper }}>
              節流晨報
            </h1>
            <p className="mt-2 text-sm" style={{ color: C.dim }}>
              市場自動分析與學習・AI 只在最後一哩<span style={{ color: C.gold }}>，且要先過閘門</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Tag color={live == null ? C.faint : live ? C.up : C.gold}>
              {loading ? "載入中" : live ? "● 即時數據" : "◦ 示範數據"}
            </Tag>
            <Tag color={wsConnected ? C.blue : C.faint}>
              {wsConnected ? "⚡ WS 即時" : "◦ 輪詢中"}
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

        {/* 招牌：墨水油表 */}
        <div className="mt-6 p-4 rounded-md" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
          <div className="flex items-baseline justify-between flex-wrap gap-2">
            <span className="mono text-xs" style={{ color: C.dim }}>本場次墨水（AI token 估算）</span>
            <span className="mono text-sm" style={{ color: totalTk > 0 ? C.gold : C.dim }}>
              {num(totalTk)} <span style={{ color: C.faint }}>/ {num(BUDGET)} 預算</span>
            </span>
          </div>
          <div className="mt-2 h-2 rounded-full overflow-hidden" style={{ background: C.surface2 }}>
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{ width: `${gaugePct}%`, background: `linear-gradient(90deg, ${C.goldDim}, ${C.gold})`, minWidth: totalTk > 0 ? 6 : 0 }}
            />
          </div>
          <div className="mt-2 flex justify-between mono text-xs" style={{ color: C.faint }}>
            <span>數據抓取與指標運算：永遠 0 tk</span>
            {saved != null && <span style={{ color: C.up }}>較「每步丟原始資料」省 {saved}%</span>}
          </div>
        </div>
      </header>

      <main className="px-5 pb-16 max-w-5xl mx-auto space-y-10">
        {/* ── 01 市場快照 ── */}
        <section>
          <SectionHead no="01" title="市場快照" sub="本區全程 0 token" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {COIN_META.map(([id, sym, name]) => {
              const q = quotes?.[id];
              const chg = q?.usd_24h_change;
              return (
                <div key={id} className="p-3 rounded-md" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
                  <div className="flex items-baseline justify-between">
                    <span className="mono text-xs font-semibold" style={{ color: C.blue }}>{sym}</span>
                    <span className="text-xs" style={{ color: C.faint }}>{name}</span>
                  </div>
                  <div className="mono text-lg mt-1">${q ? num(q.usd, q.usd < 10 ? 2 : 0) : "—"}</div>
                  <div className="mono text-xs" style={{ color: chg == null ? C.faint : chg >= 0 ? C.up : C.down }}>
                    {pct(chg)} <span style={{ color: C.faint }}>24h</span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-3 grid md:grid-cols-3 gap-3">
            <div className="md:col-span-2 p-3 rounded-md" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
              <div className="flex items-baseline justify-between mb-1">
                <span className="mono text-xs" style={{ color: C.dim }}>BTC 近 60 日</span>
                <span className="mono text-xs" style={{ color: C.faint }}>本地繪製</span>
              </div>
              <div style={{ height: 72 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData}>
                    <YAxis hide domain={["dataMin", "dataMax"]} />
                    <Line type="monotone" dataKey="v" stroke={C.blue} strokeWidth={1.5} dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {metrics && (
                <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 mono text-xs">
                  <div><span style={{ color: C.faint }}>RSI14 </span><span style={{ color: metrics.rsi14 >= 70 || metrics.rsi14 <= 30 ? C.gold : C.paper }}>{metrics.rsi14?.toFixed(0)}</span></div>
                  <div><span style={{ color: C.faint }}>均線乖離 </span><span style={{ color: metrics.maBias >= 0 ? C.up : C.down }}>{pct(metrics.maBias, 2)}</span></div>
                  <div><span style={{ color: C.faint }}>年化波動 </span>{metrics.vol?.toFixed(0)}%</div>
                  <div><span style={{ color: C.faint }}>90日回撤 </span><span style={{ color: C.down }}>{metrics.mdd?.toFixed(1)}%</span></div>
                </div>
              )}
            </div>
            <div className="p-3 rounded-md flex flex-col justify-between" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
              <span className="mono text-xs" style={{ color: C.dim }}>恐懼與貪婪</span>
              <div className="serif font-black text-4xl" style={{ color: fng && (fng.value <= 25 || fng.value >= 75) ? C.gold : C.paper }}>
                {fng?.value ?? "—"}
              </div>
              <div className="text-xs" style={{ color: C.dim }}>{fng?.label ?? ""}</div>
              <div className="mt-2 h-1.5 rounded-full" style={{ background: C.surface2 }}>
                <div className="h-full rounded-full" style={{ width: `${fng?.value ?? 0}%`, background: C.blue }} />
              </div>
            </div>
          </div>
        </section>

        {/* ── 02 自動化管線 ── */}
        <section>
          <SectionHead no="02" title="自動化管線" sub="一鍵完成當日分析" />
          <div className="grid md:grid-cols-5 gap-4">
            {/* 管線 rail */}
            <div className="md:col-span-2 p-4 rounded-md" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
              <button
                onClick={runPipeline}
                disabled={running || loading}
                className="w-full serif font-bold text-base py-2.5 rounded-md transition-opacity"
                style={{
                  background: running ? C.surface2 : C.gold,
                  color: running ? C.dim : C.ink,
                  opacity: loading ? 0.5 : 1,
                }}
              >
                {running ? "管線執行中…" : "執行今日分析流程"}
              </button>

              {/* 閘門設定 */}
              <div className="mt-4 pt-3" style={{ borderTop: `1px dashed ${C.line}` }}>
                <div className="flex items-center justify-between">
                  <span className="mono text-xs" style={{ color: C.dim }}>條件閘門</span>
                  <button
                    onClick={() => setGateOn(!gateOn)}
                    className="mono text-xs px-2 py-0.5 rounded-full"
                    style={{
                      border: `1px solid ${gateOn ? C.goldDim : C.line}`,
                      color: gateOn ? C.gold : C.faint,
                      background: gateOn ? "rgba(217,169,78,.10)" : "transparent",
                    }}
                  >
                    {gateOn ? "啟用中" : "已關閉"}
                  </button>
                </div>
                <p className="text-xs mt-1.5 leading-relaxed" style={{ color: C.faint }}>
                  無觸發條件時攔下 AI 呼叫，晨報只出本地版——平靜的日子不花墨水。
                </p>
                <div className="mt-3 space-y-2">
                  {[
                    ["absChange", "24h 波動門檻 (%)", 1, 10, 0.5],
                    ["fngLo", "情緒恐懼線 (≤)", 5, 45, 5],
                    ["fngHi", "情緒貪婪線 (≥)", 55, 95, 5],
                  ].map(([k, label, min, max, step]) => (
                    <div key={k}>
                      <div className="flex justify-between mono text-xs" style={{ color: C.dim }}>
                        <span>{label}</span>
                        <span style={{ color: C.paper }}>{gate[k]}</span>
                      </div>
                      <input
                        type="range" min={min} max={max} step={step}
                        value={gate[k]}
                        onChange={(e) => setGate({ ...gate, [k]: Number(e.target.value) })}
                        className="w-full"
                        style={{ accentColor: C.gold }}
                      />
                    </div>
                  ))}
                  <div className="mono text-xs" style={{ color: C.faint }}>
                    目前觸發：{triggers.length ? triggers.length + " 項" : "無"}{" "}
                    {triggers.length === 0 && gateOn && <span style={{ color: C.up }}>→ 執行將免 AI 費用</span>}
                  </div>
                </div>
              </div>

              {/* 步驟列 */}
              {steps.length > 0 && (
                <ol className="mt-4 space-y-0">
                  {steps.map((s, i) => {
                    const st = stStyle[s.status];
                    return (
                      <li key={s.id} className="relative pl-5 pb-3">
                        {i < steps.length - 1 && (
                          <span className="absolute left-1.5 top-4 bottom-0 w-px" style={{ background: C.line }} />
                        )}
                        <span
                          className="absolute left-0 top-1.5 w-3 h-3 rounded-full"
                          style={{
                            background: s.status === "run" ? st.c : "transparent",
                            border: `2px solid ${st.c}`,
                            animation: s.status === "run" ? "pulseDot 1s infinite" : "none",
                          }}
                        />
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm" style={{ color: s.status === "wait" ? C.faint : C.paper }}>
                            {s.label}
                          </span>
                          {s.tk != null && (s.status === "done" || s.status === "skip") && (
                            <TokenStamp n={s.tk} hot={s.tk > 0} />
                          )}
                        </div>
                        <div className="mono text-xs mt-0.5" style={{ color: st.c }}>
                          {st.s}<span style={{ color: C.faint }}>・{s.note}</span>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              )}
            </div>

            {/* 晨報輸出 */}
            <div className="md:col-span-3 p-5 rounded-md" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
              {!report ? (
                <div className="h-full flex flex-col items-center justify-center text-center py-12">
                  <div className="serif text-xl font-bold" style={{ color: C.dim }}>晨報尚未付印</div>
                  <p className="text-xs mt-2 max-w-xs leading-relaxed" style={{ color: C.faint }}>
                    按下「執行今日分析流程」。抓數據、算指標都不花墨水，AI 只在閘門放行時被叫進來寫一段。
                  </p>
                </div>
              ) : (
                <article>
                  <div className="flex items-baseline justify-between flex-wrap gap-2 pb-3" style={{ borderBottom: `2px solid ${C.line}` }}>
                    <h3 className="serif text-xl font-black">今日晨報</h3>
                    <span className="mono text-xs" style={{ color: C.faint }}>
                      付印 {report.at.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>

                  {/* 本地版（永遠有）*/}
                  <div className="mt-4">
                    <div className="mono text-xs mb-2" style={{ color: C.blue }}>本地觀測（0 tk）</div>
                    <p className="text-sm leading-relaxed" style={{ color: C.paper }}>
                      BTC 報 ${num(metrics.px)}，24 小時 {pct(metrics.chg24)}、近 7 日 {pct(metrics.chg7)}。
                      RSI14 為 {metrics.rsi14?.toFixed(0)}，MA20 對 MA60 乖離 {pct(metrics.maBias, 2)}
                      （{metrics.maBias >= 0 ? "多頭排列" : "空頭排列"}）；年化波動率 {metrics.vol?.toFixed(0)}%，
                      90 日最大回撤 {metrics.mdd?.toFixed(1)}%。市場情緒 {fng.value}（{fng.label}）。
                    </p>
                    {report.triggers.length > 0 && (
                      <ul className="mt-2 space-y-1">
                        {report.triggers.map((t, i) => (
                          <li key={i} className="mono text-xs" style={{ color: C.gold }}>▲ {t}</li>
                        ))}
                      </ul>
                    )}
                  </div>

                  {/* AI 版 */}
                  <div className="mt-5 pt-4" style={{ borderTop: `1px dashed ${C.line}` }}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="mono text-xs" style={{ color: C.gold }}>AI 研判</span>
                      {gateSkipped && <TokenStamp n={0} hot={false} />}
                    </div>
                    {gateSkipped ? (
                      <p className="text-sm leading-relaxed" style={{ color: C.dim }}>
                        閘門判定今日無異常條件，AI 呼叫已省略。這正是設計本意：
                        <span style={{ color: C.paper }}>平靜的市場不值得花 token 請 AI 覆述一次「今天很平靜」。</span>
                        想強制研判，可暫時關閉閘門再執行。
                      </p>
                    ) : ai?.error ? (
                      <p className="text-sm" style={{ color: C.down }}>{ai.error}</p>
                    ) : ai ? (
                      <div className="space-y-3">
                        <p className="text-sm leading-relaxed">{ai.summary}</p>
                        {ai.signals?.length > 0 && (
                          <div className="grid sm:grid-cols-3 gap-2">
                            {ai.signals.map((s, i) => (
                              <div key={i} className="p-2 rounded-sm" style={{ background: C.surface2, border: `1px solid ${C.line}` }}>
                                <div className="flex justify-between mono text-xs">
                                  <span style={{ color: C.blue }}>{s.n}</span>
                                  <span style={{ color: s.v?.includes("多") ? C.up : s.v?.includes("空") ? C.down : C.dim }}>{s.v}</span>
                                </div>
                                <div className="text-xs mt-1" style={{ color: C.dim }}>{s.r}</div>
                              </div>
                            ))}
                          </div>
                        )}
                        {ai.risk && (
                          <p className="text-xs leading-relaxed" style={{ color: C.down }}>風險提示：{ai.risk}</p>
                        )}
                        {ai.lesson && (
                          <div className="p-3 rounded-sm" style={{ background: "rgba(217,169,78,.07)", border: `1px solid ${C.goldDim}` }}>
                            <div className="mono text-xs mb-1" style={{ color: C.gold }}>今日一課</div>
                            <p className="text-sm leading-relaxed">{ai.lesson}</p>
                            {ai.quiz?.q && (
                              <details className="mt-2">
                                <summary className="text-xs cursor-pointer" style={{ color: C.dim }}>自測：{ai.quiz.q}</summary>
                                <p className="text-xs mt-1" style={{ color: C.blue }}>{ai.quiz.a}</p>
                              </details>
                            )}
                          </div>
                        )}
                      </div>
                    ) : null}
                    <p className="mono text-xs mt-4" style={{ color: C.faint }}>
                      教育性分析・非投資建議
                    </p>
                  </div>
                </article>
              )}
            </div>
          </div>
        </section>

        {/* ── 03 學習室 ── */}
        <section>
          <SectionHead no="03" title="學習室" sub="概念卡免費，出題才動用 AI" />
          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              {CARDS.map((c, i) => (
                <div key={i} className="rounded-md overflow-hidden" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
                  <button
                    onClick={() => setOpenCard(openCard === i ? null : i)}
                    className="w-full flex items-center justify-between px-4 py-3 text-left"
                  >
                    <span className="text-sm font-medium">{c.t}</span>
                    <span className="mono text-xs" style={{ color: C.faint }}>{openCard === i ? "收合" : "0 tk"}</span>
                  </button>
                  {openCard === i && (
                    <div className="px-4 pb-4 space-y-2 text-sm leading-relaxed" style={{ borderTop: `1px dashed ${C.line}` }}>
                      <p className="pt-3"><span className="mono text-xs" style={{ color: C.blue }}>定義　</span>{c.def}</p>
                      <p><span className="mono text-xs" style={{ color: C.up }}>用法　</span>{c.use}</p>
                      <p><span className="mono text-xs" style={{ color: C.down }}>陷阱　</span>{c.trap}</p>
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="p-4 rounded-md h-fit" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
              <div className="flex items-center justify-between">
                <span className="serif font-bold">AI 情境題</span>
                <button
                  onClick={makeQuiz}
                  disabled={quizBusy || loading}
                  className="mono text-xs px-3 py-1.5 rounded-md"
                  style={{ background: quizBusy ? C.surface2 : "rgba(217,169,78,.12)", border: `1px solid ${C.goldDim}`, color: C.gold }}
                >
                  {quizBusy ? "出題中…" : "依今日市況出一題（1 次呼叫）"}
                </button>
              </div>
              {quiz ? (
                <div className="mt-3">
                  <p className="text-sm leading-relaxed">{quiz.q}</p>
                  {quiz.a && (
                    <div className="mt-3">
                      {showAns ? (
                        <p className="text-sm leading-relaxed p-3 rounded-sm" style={{ background: C.surface2, color: C.blue }}>{quiz.a}</p>
                      ) : (
                        <button onClick={() => setShowAns(true)} className="mono text-xs px-3 py-1 rounded-sm" style={{ border: `1px solid ${C.line}`, color: C.dim }}>
                          先想過再看解析
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-xs mt-3 leading-relaxed" style={{ color: C.faint }}>
                  題目會綁定今天的真實數字，不出教科書式的抽象題。一次呼叫產一題含解析。
                </p>
              )}
            </div>
          </div>
        </section>

        {/* ── 04 墨水帳本 ── */}
        <section>
          <SectionHead no="04" title="墨水帳本" sub="每一滴 token 都記帳" />
          <div className="p-4 rounded-md" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
            {ledger.length === 0 ? (
              <p className="text-sm" style={{ color: C.faint }}>本場次尚未動用任何 AI token。</p>
            ) : (
              <div className="space-y-1.5">
                {ledger.map((r, i) => (
                  <div key={i} className="flex items-center justify-between mono text-xs flex-wrap gap-1">
                    <span style={{ color: C.dim }}>
                      {r.t.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" })}・{r.label}
                    </span>
                    <span>
                      <span style={{ color: C.blue }}>入 {r.inTok}</span>
                      <span style={{ color: C.faint }}> ／ </span>
                      <span style={{ color: C.gold }}>出 {r.outTok}</span>
                    </span>
                  </div>
                ))}
                <div className="pt-2 mt-2 flex items-center justify-between mono text-xs" style={{ borderTop: `1px solid ${C.line}` }}>
                  <span style={{ color: C.paper }}>合計 {num(totalTk)} tk（估算）</span>
                  <span style={{ color: C.up }}>天真做法約 {num(naive)} tk → 省 {saved}%</span>
                </div>
              </div>
            )}
            <p className="text-xs mt-3 leading-relaxed" style={{ color: C.faint }}>
              省法拆解：①原始 K 線在本地算完，只把「結論數字」餵給 AI（輸入約 300 字，而非上萬字 JSON）；
              ②一次呼叫同時要到綜評、訊號、風險、課程與題目（合併輸出）；③強制 JSON 砍掉客套話；
              ④條件閘門讓平靜日直接 0 呼叫。
            </p>
          </div>
        </section>

        {/* ── 05 全球市場（台股／美股／大宗商品）── */}
        {markets && (
          <section>
            <SectionHead no="05" title="全球市場" sub="本區全程 0 token・預設觀察清單" />
            <div className="grid md:grid-cols-3 gap-4">
              {[
                ["台股", markets.tw_stocks],
                ["美股", markets.us_stocks],
                ["大宗商品", markets.commodities],
              ].map(([label, group]) => (
                <div key={label} className="p-3 rounded-md" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
                  <div className="mono text-xs mb-2" style={{ color: C.dim }}>{label}</div>
                  <div className="space-y-1.5">
                    {group && Object.keys(group).length > 0 ? (
                      Object.entries(group).map(([code, m]) => (
                        <div key={code} className="flex items-center justify-between text-sm">
                          <span style={{ color: C.paper }}>{m.name}</span>
                          <span className="mono text-xs">
                            {num(m.price, m.price < 10 ? 2 : 1)}{" "}
                            <span style={{ color: m.chg_pct == null ? C.faint : m.chg_pct >= 0 ? C.up : C.down }}>
                              {pct(m.chg_pct)}
                            </span>
                          </span>
                        </div>
                      ))
                    ) : (
                      <p className="text-xs" style={{ color: C.faint }}>載入中或暫無資料</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── 06 SMC 市場結構與交易計畫（規則式合成，非AI）── */}
        {(smcData || tradePlan) && (
          <section>
            <SectionHead no="06" title="SMC 交易計畫" sub="BTC・規則式本地合成，非 AI、非投資建議" />
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
        )}

        <footer className="pt-2 mono text-xs text-center" style={{ color: C.faint }}>
          節流晨報・獨立作業・token 為估算值・所有內容僅供教育用途
        </footer>
      </main>
    </div>
  );
}
