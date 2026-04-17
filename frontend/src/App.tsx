import { Routes, Route, NavLink, useMatch } from "react-router-dom";
import TickerPage from "./pages/TickerPage";
import HomePage from "./pages/HomePage";
import ScreenerPage from "./pages/ScreenerPage";
import WatchlistPage from "./pages/WatchlistPage";
import ComparePage from "./pages/ComparePage";
import PortfolioPage from "./pages/PortfolioPage";
import SentimentPage from "./pages/SentimentPage";
import ErrorBoundary from "./components/ErrorBoundary";

const navCls = ({ isActive }: { isActive: boolean }) =>
  isActive ? "text-blue-400 text-sm" : "text-slate-400 hover:text-white text-sm";

export default function App() {
  const tickerMatch = useMatch("/ticker/:symbol");
  const activeSymbol = tickerMatch?.params.symbol;

  return (
    <div className="min-h-screen">
      <nav className="border-b border-slate-800 px-6 py-4 flex items-center gap-6 overflow-x-auto">
        <span className="text-lg font-semibold text-white tracking-tight shrink-0">
          Stock Analyzer
        </span>
        <NavLink to="/" className={navCls}>Home</NavLink>
        <NavLink to="/screener" className={navCls}>Screener</NavLink>
        <NavLink to="/sentiment" className={navCls}>Sentiment</NavLink>
        <NavLink to="/portfolio" className={navCls}>Portfolio</NavLink>
        <NavLink to="/compare" className={navCls}>Compare</NavLink>
        <NavLink to="/watchlist" className={navCls}>Watchlist</NavLink>
        {activeSymbol && (
          <NavLink to={`/ticker/${activeSymbol}`} className={navCls}>
            {activeSymbol} Tearsheet
          </NavLink>
        )}
      </nav>

      <main className="px-6 py-8 max-w-7xl mx-auto">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/screener" element={<ScreenerPage />} />
            <Route path="/sentiment" element={<SentimentPage />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/compare" element={<ComparePage />} />
            <Route path="/watchlist" element={<WatchlistPage />} />
            <Route path="/ticker/:symbol" element={<TickerPage />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
