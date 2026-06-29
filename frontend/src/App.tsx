import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Backtests from './pages/Backtests'
import BacktestDetail from './pages/BacktestDetail'
import NewRun from './pages/NewRun'
import Evaluations from './pages/Evaluations'
import EvaluationDetail from './pages/EvaluationDetail'
import Ingestion from './pages/Ingestion'

function NavBar() {
  const linkCls = ({ isActive }: { isActive: boolean }) =>
    `text-sm font-medium transition-colors ${
      isActive
        ? 'text-amber-400'
        : 'text-zinc-400 hover:text-zinc-50'
    }`

  return (
    <header className="bg-zinc-950 border-b border-zinc-800">
      <div className="max-w-6xl mx-auto px-6 h-12 flex items-center justify-between">
        <span className="font-mono text-sm font-semibold text-amber-400 tracking-widest select-none">
          RESEARCH TERMINAL
        </span>
        <nav aria-label="Main navigation">
          <ul className="flex items-center gap-8 list-none p-0 m-0">
            <li>
              <NavLink to="/" end className={linkCls}>
                Dashboard
              </NavLink>
            </li>
            <li>
              <NavLink to="/new" className={linkCls}>
                New Run
              </NavLink>
            </li>
            <li>
              <NavLink to="/backtests" className={linkCls}>
                Backtests
              </NavLink>
            </li>
            <li>
              <NavLink to="/evaluations" className={linkCls}>
                Evaluations
              </NavLink>
            </li>
            <li>
              <NavLink to="/ingestion" className={linkCls}>
                Ingestion
              </NavLink>
            </li>
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
      className="bg-amber-950/50 border-b border-amber-900/40 py-1.5 px-6"
    >
      <p className="text-xs text-amber-300/70 text-center max-w-6xl mx-auto">
        All results are{' '}
        <strong className="font-medium text-amber-300/90">
          simulated backtests on historical data
        </strong>
        . Not financial advice. Past performance does not guarantee future results.
      </p>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-zinc-950 text-zinc-50">
        <NavBar />
        <DisclaimerBanner />
        <main className="max-w-6xl mx-auto px-6 py-8">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/new" element={<NewRun />} />
            <Route path="/backtests" element={<Backtests />} />
            <Route path="/backtests/:id" element={<BacktestDetail />} />
            <Route path="/evaluations" element={<Evaluations />} />
            <Route path="/evaluations/:id" element={<EvaluationDetail />} />
            <Route path="/ingestion" element={<Ingestion />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
