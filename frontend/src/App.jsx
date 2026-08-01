import { useRoute } from "./router.jsx";
import CryptoPage from "./pages/CryptoPage.jsx";
import AnalysisPage from "./pages/AnalysisPage.jsx";

const ROUTES = {
  "/tw": { symbol: "TWII", title: "台股", subtitle: "加權指數（TAIEX）獨立分析・本地規則式合成" },
  "/us": { symbol: "SPY", title: "美股", subtitle: "S&P 500 ETF（SPY）獨立分析・本地規則式合成" },
  "/commodities": { symbol: "GC", title: "大宗商品", subtitle: "黃金期貨（GC）獨立分析・本地規則式合成" },
};

export default function App() {
  const [path, navigate] = useRoute();
  const route = ROUTES[path];

  if (route) {
    return (
      <AnalysisPage path={path} navigate={navigate} symbol={route.symbol} title={route.title} subtitle={route.subtitle} />
    );
  }
  return <CryptoPage path={path} navigate={navigate} />;
}
