import { useEffect, useState, useCallback } from "react";

/* 極簡客戶端路由：4 個靜態頁面不需要完整路由庫（且目前所有已發布的 react-router-dom
   版本都落在已知 CVE 區間內，那些漏洞都跟我們沒用到的 SSR/RSC/loader-redirect 有關，
   但既然用不到功能，乾脆不裝，用 history API 自己寫）。 */

export function useRoute() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((to) => {
    if (to !== window.location.pathname) {
      window.history.pushState({}, "", to);
      setPath(to);
    }
  }, []);

  return [path, navigate];
}

export function NavLink({ to, path, navigate, children, className, activeClassName }) {
  const isActive = path === to;
  return (
    <a
      href={to}
      onClick={(e) => {
        e.preventDefault();
        navigate(to);
      }}
      className={`${className || ""} ${isActive ? activeClassName || "" : ""}`.trim()}
    >
      {children}
    </a>
  );
}
