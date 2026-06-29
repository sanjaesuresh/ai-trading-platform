# AI Trading Platform

A **simulated** AI-powered trading **research and paper-trading** platform. It
loads historical market data, runs strategies over it, backtests them with
realistic fees and slippage, computes performance metrics, persists results, and
visualizes them in a web UI.

> **Simulated only — not financial advice.** Every result is a backtest over
> historical data. This is a research and education tool. It does not trade real
> money in its current scope, and **nothing here implies real or guaranteed
> returns.** The name says "AI," but that is the destination, not the start: the
> honest path is to prove the data + backtesting + execution plumbing with simple
> rule-based strategies first, then earn the right to add ML and news/LLM signals.

## Phase 1 (this slice)

CSV historical data → validate data quality → generate technical indicators → run
a trend-following backtest → calculate metrics → persist run + trades → expose via
FastAPI → display in React.

**In Phase 1:** CSV OHLCV loading, data-quality validation, technical indicators,
a rule-based long-only trend-following strategy, a backtesting engine with fees,
slippage, and next-bar-open execution, metrics, PostgreSQL persistence, a FastAPI
API, a minimal React visualizer, core trading-logic tests, and Docker Compose.

**Not in Phase 1** (each deferred to its own planned phase): machine learning,
paper trading / broker integration, live or vendor market data, LLM / news /
sentiment, authentication, multi-asset or portfolio backtests, shorting / margin /
leverage, intraday microstructure, parameter optimization, background jobs.

See `docs/phase-1.md`, `docs/architecture.md`, and `docs/risk-rules.md`.

## Run the full stack (Docker Compose)

```bash
cp .env.example .env        # safe dev defaults; no real secrets
docker compose up --build
```

This starts:
- **Postgres** on `:5432`
- **Backend** (FastAPI) on `:8000` — applies migrations, then serves
- **Frontend** (Vite) on `:5173`

Open http://localhost:5173, then use the dashboard to run the sample backtest.

## Run a sample backtest (API)

```bash
curl -X POST localhost:8000/backtests/run \
  -H 'content-type: application/json' \
  -d '{"symbol":"SYNTH","csv_path":"data/sample/sample_ohlcv.csv","initial_capital":100000,"fee_bps":5,"slippage_bps":5,"max_position_pct":0.95}'
```

Then `GET /backtests` for the list and `GET /backtests/{id}` for full detail.
The sample CSV (`data/sample/sample_ohlcv.csv`) is **synthetic** and labeled as
such; the loader accepts any real OHLCV CSV with `timestamp,open,high,low,close,volume`
columns placed under the `data/` directory.

## Backend tests (no database needed)

The five core test modules are pure logic:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest            # core trading-logic tests
ruff check .      # lint
mypy app          # types
```

## Frontend (standalone dev)

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
```

The frontend reads the API base URL from `VITE_API_BASE_URL` (default
`http://localhost:8000`).

## Layout

```
backend/   FastAPI + SQLAlchemy + pandas backtesting engine, Alembic migrations
frontend/  React + TypeScript + Vite + Tailwind + Recharts visualizer
data/       sample synthetic OHLCV
docs/       architecture, phase-1, risk-rules, plans, roadmap
docker-compose.yml
```
