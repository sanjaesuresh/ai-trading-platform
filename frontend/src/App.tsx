import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Backtests from './pages/Backtests'
import BacktestDetail from './pages/BacktestDetail'
import NewRun from './pages/NewRun'
import Evaluations from './pages/Evaluations'
import EvaluationDetail from './pages/EvaluationDetail'
import Ingestion from './pages/Ingestion'
import PaperTrading from './pages/PaperTrading'
import PaperDeploymentDetail from './pages/PaperDeploymentDetail'
import MLModels from './pages/MLModels'
import MLModelDetail from './pages/MLModelDetail'
import MLEvaluationDetail from './pages/MLEvaluationDetail'
import News from './pages/News'
import NewsAblationDetail from './pages/NewsAblationDetail'

// Friendly labels for the nav. Routes are unchanged; only the wording is
// softened so a first-time visitor can guess what each tab does.
const NAV_ITEMS: { to: string; label: string; end?: boolean }[] = [
  { to: '/', label: 'Home', end: true },
  { to: '/new', label: 'New Run' },
  { to: '/backtests', label: 'Backtests' },
  { to: '/evaluations', label: 'Evaluations' },
  { to: '/paper', label: 'Paper' },
  { to: '/ingestion', label: 'Data' },
  { to: '/ml', label: 'ML' },
  { to: '/news', label: 'News' },
]

function NavBar() {
  const linkCls = ({ isActive }: { isActive: boolean }) =>
    `relative text-sm font-medium transition-colors py-1 ${
      isActive
        ? 'text-accent'
        : 'text-ink-muted hover:text-ink'
    }`

  return (
    <header className="bg-canvas/95 supports-[backdrop-filter]:bg-canvas/80 backdrop-blur border-b border-hairline sticky top-0 z-20">
      <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between gap-6">
        <NavLink
          to="/"
          className="flex items-center gap-2.5 select-none shrink-0 group"
          aria-label="AI Trading Lab — home"
        >
          <span
            aria-hidden
            className="h-6 w-6 rounded-md bg-accent/15 border border-accent/40 grid place-items-center"
          >
            <span className="h-2 w-2 rounded-full bg-accent group-hover:bg-accent-bright transition-colors" />
          </span>
          <span className="flex flex-col leading-none">
            <span className="text-sm font-semibold text-ink tracking-tight">
              AI Trading Lab
            </span>
            <span className="text-[11px] uppercase tracking-widest text-ink-muted">
              Simulated research
            </span>
          </span>
        </NavLink>
        <nav aria-label="Main navigation" className="overflow-x-auto">
          <ul className="flex items-center gap-6 sm:gap-7 list-none p-0 m-0">
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.end} className={linkCls}>
                  {({ isActive }) => (
                    <>
                      {item.label}
                      <span
                        aria-hidden
                        className={`absolute -bottom-[7px] left-0 right-0 h-0.5 rounded-full transition-opacity ${
                          isActive ? 'bg-accent opacity-100' : 'opacity-0'
                        }`}
                      />
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  )
}

function DisclaimerBanner() {
  return (
    <div
      role="note"
      aria-label="Disclaimer"
      className="bg-caution/10 border-b border-caution/20 py-2 px-6"
    >
      <p className="text-xs text-caution/90 text-center max-w-7xl mx-auto leading-relaxed">
        <span aria-hidden className="mr-1.5">🧪</span>
        Everything here is{' '}
        <strong className="font-semibold">simulated</strong> — historical
        backtests, or forward paper trading on a practice account.{' '}
        <span className="text-caution/70">
          No real money. Not financial advice. Past results never guarantee
          future ones.
        </span>
      </p>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-canvas text-ink antialiased">
        <NavBar />
        <DisclaimerBanner />
        <main className="max-w-7xl mx-auto px-6 py-10">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/new" element={<NewRun />} />
            <Route path="/backtests" element={<Backtests />} />
            <Route path="/backtests/:id" element={<BacktestDetail />} />
            <Route path="/evaluations" element={<Evaluations />} />
            <Route path="/evaluations/:id" element={<EvaluationDetail />} />
            <Route path="/ingestion" element={<Ingestion />} />
            <Route path="/paper" element={<PaperTrading />} />
            <Route path="/paper/:id" element={<PaperDeploymentDetail />} />
            <Route path="/ml" element={<MLModels />} />
            <Route path="/ml/models/:id" element={<MLModelDetail />} />
            <Route path="/ml/evaluations/:id" element={<MLEvaluationDetail />} />
            <Route path="/news" element={<News />} />
            <Route path="/news/ablation/:id" element={<NewsAblationDetail />} />
          </Routes>
        </main>
        <footer className="border-t border-hairline mt-8">
          <div className="max-w-7xl mx-auto px-6 py-6 text-xs text-ink-subtle flex flex-wrap items-center justify-between gap-2">
            <span>AI Trading Lab — a research &amp; learning sandbox.</span>
            <span>Simulated only · No real money · Not financial advice.</span>
          </div>
        </footer>
      </div>
    </BrowserRouter>
  )
}
