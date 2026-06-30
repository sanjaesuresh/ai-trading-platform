# AI Trading Platform

A **simulated** AI-powered trading **research and paper-trading** platform. It
loads historical market data, runs strategies over it, backtests them with
realistic fees and slippage, computes performance metrics, persists results, and
visualizes them in a web UI.

> **Simulated only — not financial advice.** All results are simulated — either
> backtests over historical data or forward paper trading against Alpaca's paper
> endpoint. This is a research and education tool. It does not trade real
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
- **Worker** (ARQ) — runs background ingestion / evaluation jobs, the nightly
  incremental-ingest cron, and the daily paper-trading submit / reconcile crons
- **Frontend** (Vite) on `:5173`

Open http://localhost:5173, then use the dashboard to run the sample backtest.

The backend mounts the local `backend/` source and runs `uvicorn --reload`, so
editing backend code restarts the API automatically — no image rebuild. After
the first build, `docker compose up -d backend` is enough to pick up changes.
(The ARQ **worker** still bakes its code into the image; rebuild it with
`docker compose up -d --build worker` after changing job code. This live-mount +
reload setup is for local dev only.)

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

## Paper trading on a shared portfolio core (Phase 3)

Everything above runs *over history*. Phase 3 runs a strategy **forward** against
a broker, in pure simulation. A **deployment** binds a registered strategy to a
basket of symbols, a simulated capital pool, and portfolio risk limits; a daily
job pulls the latest bars, asks one shared **portfolio execution core** for target
orders, submits them to **Alpaca paper trading**, and reconciles the broker's
fills, positions, and cash back into the platform.

The load-bearing idea is **live must equal backtested**: the same pure core
(`backtesting/portfolio_core.py`) is driven by *both* a multi-symbol backtest and
the live runner, so what you see in paper is exactly what you can backtest. A
multi-symbol portfolio backtest is judged out-of-sample, net of fees, against both
the rule-based baseline **and** the allocator-off single-position basket — so the
cross-symbol allocator has to earn its added complexity.

**Paper only, structurally.** Orders go to Alpaca's *paper* endpoint only; the
base URL is hardcoded and guarded, the live (real-money) endpoint is unreachable,
and a test asserts it. Paper trading gets the **strongest** simulated-only
disclaimer treatment in the app — it trades no real money and implies no returns.

- **Set keys** (only needed for a real paper run): put `ALPACA_API_KEY` and
  `ALPACA_SECRET_KEY` in the root `.env` (free paper keys from alpaca.markets).
  Without them the tested `FakeBroker` is the default and the runner skips cleanly.
- **Create / manage** via `POST /paper/deployments` (validated strategy, basket,
  capital, and risk limits — leverage and negative costs are rejected), `GET
  /paper/deployments`, `PATCH …/{id}`, and `POST …/{id}/enable`. Enabling one
  deployment disables the rest (one shared paper account, no commingled cash).
- **Run** with `POST /paper/deployments/{id}/run` (enqueues the daily cycle). The
  worker also runs it on a schedule: a pre-open **submit** pass places
  opening-auction orders, and a next-morning **reconcile** pass records fills and
  attributes slippage against the backtest's modeled open once that bar is ingested.
- **Read** the dashboard with `GET /paper/deployments/{id}/portfolio` (equity
  curve, positions, orders, fills, reconciliation log, slippage distribution, kill
  status) and the **live-vs-backtest comparison** with
  `GET /paper/deployments/{id}/comparison`.
- **Kill switches.** A per-deployment enable flag, a portfolio max-drawdown kill
  (flatten + halt), and a global kill switch (`GET`/`POST /paper/kill-switch`) that
  halts all new orders.

The residual backtest↔paper gap is *measured, not hidden*: every fill stores the
realized price, the modeled open, and the cost-signed slippage delta, surfaced as
a distribution in the comparison view. The larger paper↔live gap (no dividends,
market impact, latency, or queue position in paper) is documented as known and
unmodeled. Still simulated only — not financial advice.

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

### Web UI flows (Phase 2 M7)

The nav exposes the full loop, and the simulated-only disclaimer renders on every
page (a site-wide banner plus an inline note on each results-bearing surface):

- **New Run** (`/new`) — pick a symbol and strategy, tune the strategy's
  parameters (the inputs render from each strategy's JSON parameter schema, so a
  new strategy needs no frontend change), set capital / fees / slippage / max
  position and the optional sizing + risk controls, then run. On submit it opens
  the new run's detail.
- **Evaluations** (`/evaluations`) — lists sweeps and walk-forward runs with a
  status badge, polling while any is `queued`/`running`. The detail view polls to
  completion, then shows the **honest distribution**: best / median / worst of the
  out-of-sample objective, an in-sample-vs-out-of-sample marker, the in/out gap,
  the overfit flag, the fraction of combinations beating the baseline, the count
  of combinations tested, and the multiple-testing caveat — never the single best
  cell on its own. A bare sweep is clearly marked in-sample only.
- **Ingestion** (`/ingestion`) — trigger a backfill or incremental ingest and
  watch the audit trail (provider, symbol, range, rows fetched/written, status,
  error), polling while any row is in flight.
- **Paper** (`/paper`) — create a deployment (strategy + basket + capital + risk
  limits), trip the global kill switch, and open a deployment's portfolio
  dashboard: the live paper equity curve, open positions, orders, fills with their
  slippage attribution, the reconciliation log, and the **live-vs-backtest
  comparison** (the backtested expectation beside the live results, with the
  measured fill-model gap and the known unmodeled biases stated inline). Every
  paper surface carries the strongest simulated-only / paper-only disclaimer.

## Layout

```
backend/   FastAPI + SQLAlchemy + pandas backtesting engine, Alembic migrations
frontend/  React + TypeScript + Vite + Tailwind + Recharts visualizer
data/       sample synthetic OHLCV
docs/       architecture, phase-1, risk-rules, plans, roadmap
docker-compose.yml
```
