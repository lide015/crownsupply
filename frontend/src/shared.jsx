/* 跨頁共用：配色、字型、格式化函式、小元件。CryptoPage 與 AnalysisPage 都吃這份。 */

export const C = {
  ink: "#0C1017",
  surface: "#131826",
  surface2: "#181F30",
  line: "#242D40",
  paper: "#E9E4D6",
  dim: "#8B92A3",
  faint: "#5A6275",
  gold: "#D9A94E",
  goldDim: "#8A6E36",
  blue: "#8FB4C6",
  up: "#63A97F",
  down: "#C56A5B",
};

export const FONT_CSS = `
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@600;700;900&family=Noto+Sans+TC:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
.serif { font-family: 'Noto Serif TC', serif; }
.mono { font-family: 'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums; }
.body-tc { font-family: 'Noto Sans TC', sans-serif; }
@keyframes pulseDot { 0%,100%{opacity:.35} 50%{opacity:1} }
@keyframes stampIn { 0%{transform:scale(1.6);opacity:0} 100%{transform:scale(1);opacity:1} }
.stamp-in { animation: stampIn .35s ease-out both; }
@media (prefers-reduced-motion: reduce) { .stamp-in { animation: none; } }
`;

export const pct = (v, d = 1) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`;
export const num = (v, d = 0) =>
  v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });

export const Tag = ({ children, color = C.faint }) => (
  <span
    className="mono text-xs px-2 py-0.5 rounded-sm"
    style={{ border: `1px solid ${color}`, color }}
  >
    {children}
  </span>
);

export const TokenStamp = ({ n, hot }) => (
  <span
    className="mono stamp-in text-xs px-2 py-0.5 rounded-full whitespace-nowrap"
    style={{
      background: hot ? "rgba(217,169,78,.14)" : "rgba(90,98,117,.14)",
      color: hot ? C.gold : C.dim,
      border: `1px solid ${hot ? C.goldDim : C.line}`,
    }}
  >
    {n === 0 ? "0 tk" : `≈${n} tk`}
  </span>
);

export const SectionHead = ({ no, title, sub }) => (
  <div className="flex items-baseline gap-3 mb-4">
    <span className="mono text-xs" style={{ color: C.goldDim }}>{no}</span>
    <h2 className="serif text-lg font-bold" style={{ color: C.paper }}>{title}</h2>
    {sub && <span className="body-tc text-xs" style={{ color: C.faint }}>{sub}</span>}
  </div>
);
