# Backend — AI Trading Platform (Phase 1)

Simulated trend-following backtesting engine. FastAPI + SQLAlchemy + pandas.

**Simulated only.** Every result is a backtest over historical data. This is a
research and education tool. It is not financial advice and implies no
profitability.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Run the API

Requires a reachable Postgres (`DATABASE_URL`). With Docker Compose from the repo
root, `docker compose up` starts Postgres + backend together. Standalone:

```bash
export DATABASE_URL=postgresql+psycopg://trading_bot:trading_bot@localhost:5432/trading_bot
uvicorn app.main:app --reload --port 8000
```

## Tests, lint, types

The five core test modules are pure logic and need no database:

```bash
pytest            # core trading-logic tests
ruff check .      # lint
mypy app          # types (pragmatic on pandas-heavy code)
```

## A sample backtest

With the API running:

```bash
curl -X POST localhost:8000/backtests/run \
  -H 'content-type: application/json' \
  -d '{"symbol":"SYNTH","csv_path":"data/sample/sample_ohlcv.csv","initial_capital":100000,"fee_bps":5,"slippage_bps":5,"max_position_pct":0.95}'
```
