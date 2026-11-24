import { useEffect, useRef } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { EmptyState } from "./components/Feedback";
import FacilityPage from "./pages/FacilityPage";
import SearchPage from "./pages/SearchPage";
import StatsPage from "./pages/StatsPage";
import { useDocumentTitle } from "./lib/useDocumentTitle";

export default function App() {
  const { pathname } = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  // On a route change, move focus to the new page so screen readers announce it.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus();
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="container site-header__inner">
          <Link to="/" className="brand">
            <svg aria-hidden="true" viewBox="0 0 32 32" width="28" height="28">
              <rect width="32" height="32" rx="7" fill="currentColor" />
              <path d="M13 7h6v6h6v6h-6v6h-6v-6H7v-6h6z" fill="var(--surface)" />
            </svg>
            Health Facility Finder
          </Link>
          <nav aria-label="Main">
            <ul className="nav">
              <li>
                <NavLink to="/" end>
                  Search
                </NavLink>
              </li>
              <li>
                <NavLink to="/stats">Coverage</NavLink>
              </li>
            </ul>
          </nav>
        </div>
      </header>

      <main id="main" ref={mainRef} tabIndex={-1} className="container">
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/facility/:facilityId" element={<FacilityPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>

      <footer className="site-footer">
        <div className="container">
          Data collected from the public{" "}
          <a href="https://nhpr.abdm.gov.in/nhpr/v4/search/facility" rel="noopener noreferrer">
            NHPR facility search
          </a>
          . Not an official source; check with the facility before you visit.
        </div>
      </footer>
    </>
  );
}

function NotFound() {
  useDocumentTitle("Page not found");
  return (
    <>
      <h1>Page not found</h1>
      <EmptyState title="There's nothing at this address.">
        <p>
          <Link to="/">Go to the search</Link>
        </p>
      </EmptyState>
    </>
  );
}
