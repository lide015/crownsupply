import { C } from "./shared.jsx";
import { NavLink } from "./router.jsx";

const PAGES = [
  { to: "/", label: "加密貨幣" },
  { to: "/tw", label: "台股" },
  { to: "/us", label: "美股" },
  { to: "/commodities", label: "大宗商品" },
];

export default function Nav({ path, navigate }) {
  return (
    <nav className="px-5 pt-4 max-w-5xl mx-auto flex items-center gap-1 flex-wrap">
      {PAGES.map((p) => (
        <NavLink
          key={p.to}
          to={p.to}
          path={path}
          navigate={navigate}
          className="mono text-xs px-3 py-1.5 rounded-sm transition-colors"
          activeClassName="nav-active"
        >
          <span
            style={{
              color: path === p.to ? C.gold : C.dim,
              borderBottom: path === p.to ? `2px solid ${C.gold}` : "2px solid transparent",
              paddingBottom: 2,
            }}
          >
            {p.label}
          </span>
        </NavLink>
      ))}
    </nav>
  );
}
