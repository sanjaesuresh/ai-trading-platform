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
- **Redis** on `:6379` — the background-job broker (Phase 2 M6)
- **Backend** (FastAPI) on `:8000` — applies migrations, then serves
- **Worker** (ARQ) — runs background ingestion / evaluation jobs and the nightly
  incremental-ingest cron
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

## Parameter sweeps and walk-forward evaluation (Phase 2 M5)

Two endpoints, and the difference between them matters:

- `POST /evaluations/sweep` runs a strategy across a parameter grid over the
  whole series. Its numbers are **in-sample only** — they are *not* evidence a
  strategy works, just a map of the grid. The summary's `is_out_of_sample` flag
  is `false` for a sweep, and `pct_beating_baseline` is `null` (no baseline run).
- `POST /evaluations/walk-forward` is the honest test: parameters are chosen on
  an in-sample window and scored on a **strictly-later** out-of-sample window,
  net of fees, against the rule-based baseline. `is_out_of_sample` is `true`.

```bash
curl -X POST localhost:8000/evaluations/walk-forward \
  -H 'content-type: application/json' \
  -d '{"symbol":"SYNTH","csv_path":"data/sample/sample_ohlcv.csv","strategy_name":"trend_following","param_grid":{"rsi_buy_low":[40,45],"rsi_buy_high":[70,75]},"objective":"sharpe_ratio"}'
```

Both persist one aggregate row; read it back with `GET /evaluations` and `GET
/evaluations/{id}`. Results are reported as a distribution (best / median /
worst), with the in-sample-vs-out-of-sample gap, an overfit flag, the fraction of
combinations beating the baseline, the number of combinations tested
(`n_combinations`), and a `caveat` string carried in the payload. **A parameter
sweep can fool itself**: many combinations tested means some look good by luck —
so the overfit flag being `false` is not a green light, and only the
out-of-sample, net-of-fees view is evidence. Still simulated only — not financial
advice, and nothing here implies real or guaranteed returns.

## Background jobs and scheduling (Phase 2 M6)

The long-running work — data ingestion and the M5 sweeps / walk-forward runs —
runs off the HTTP request on an **ARQ** worker backed by **Redis** (`REDIS_URL`).
Routes never touch ARQ directly; they go through a one-file enqueue seam
(`app/jobs/queue.py`), so swapping the queue backend is contained.

- **Ingestion.** `POST /ingestion/run` with `{"mode":"incremental"}` (or
  `"backfill"`, plus an optional `symbols` list) enqueues a job and returns `202`
  with the job id and `status: "queued"`. Read the audit trail with
  `GET /ingestion` (newest first) and `GET /ingestion/{id}`. Ingestion is
  idempotent — the `(symbol, timestamp)` upsert means a retry never duplicates
  bars.
- **Evaluations are async by default.** `POST /evaluations/sweep` and
  `POST /evaluations/walk-forward` create the run row in `queued`, enqueue the
  job, and return `202`; poll `GET /evaluations/{id}` until `status` is
  `completed` or `failed`. The `/evaluations/sweep/sync` and
  `/evaluations/walk-forward/sync` sub-paths keep the M5 inline behavior (`201`,
  `completed`) for small grids. An oversized or invalid grid is still rejected
  with a clean `400` at enqueue time, before anything is queued.
- **Run lifecycle** reuses the existing `status` column on each run row:
  `queued → running → completed | failed` (no schema migration). A failure
  records the message on the row's `error` field.
- **Nightly cron.** The worker runs one scheduled job: an incremental ingest over
  the configured universe, at 06:00 UTC. No other scheduled work in Phase 2.
- **Running the worker** (Compose does this for you):

  ```bash
  cd backend
  arq app.jobs.worker.WorkerSettings   # needs Redis reachable at REDIS_URL
  ```

`REDIS_URL` comes from the environment with a safe dev default
(`redis://localhost:6379/0`); Compose points it at the `redis` service. No
secrets in source. Unit tests never need a live Redis — task functions are tested
by calling them directly; a live-Redis round trip is a manual integration step.

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
