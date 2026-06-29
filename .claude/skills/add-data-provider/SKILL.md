---
name: add-data-provider
description: Add a market-data provider (Tiingo, Alpaca, Polygon, etc.) behind the platform's provider-agnostic interface — with backfill + incremental ingest, the existing data-quality checks as the ingest gate, corporate-actions/adjusted-price handling, and a licensing/redistribution review. Use when the user says "add a data provider", "ingest real market data", "wire up Tiingo / Alpaca / Polygon", "backfill history", or starts Phase 2 data sourcing. Project-scoped to ai-trading-platform; forward-looking (Phase 2 of the roadmap).
---

# Add a market-data provider (Phase 2)

This is the Phase-2 procedure from `docs/roadmap.md` §2. It replaces "read a CSV"
with "ingest licensed market data from a vendor," without letting the rest of the
system learn which vendor it is. Forward-looking: the provider interface below
does not exist in Phase 1 — the first invocation creates it. Planning gate
applies: write the ingestion plan as prose and get approval before code.

## The two rules that shape everything

1. **One interface, swappable implementations.** Nothing above the data-access
   layer may import a vendor SDK or know a vendor's name. The backtester, the
   service, and the API see a single provider interface. Swapping Tiingo for
   Alpaca must touch only the implementation and the config that selects it.
2. **Licensing is an architectural constraint, not a footnote.** Most market-data
   licenses restrict redistribution and display. Storing data and showing it to
   one user is usually fine; exposing raw vendor data through a public API or to
   many users often is not. Check the vendor's terms **before** building, because
   the answer changes what the API may return and whether the project can be
   deployed publicly. yfinance and other unofficial/free sources are prototyping
   only — no SLA, no redistribution rights, can break without notice.

## Before you touch code

1. **Confirm the vendor and tier.** The roadmap recommendation is to start on
   **daily (EOD) data from one affordable, licensed provider** (Tiingo or
   Alpaca), and to pair the data vendor with the execution broker if possible
   (Alpaca data + Alpaca paper trading). Re-verify current pricing, rate limits,
   and history depth — vendor terms change. If the user hasn't picked, surface
   the trade-offs (cost, coverage, history depth, licensing, websocket support)
   and let them choose.

2. **Read what exists** so the new layer reuses it instead of forking it:
   - `backend/app/data/data_quality.py` — this is the ingest gate. Every fetched
     batch runs through the **same** quality report a CSV does. Do not write a
     second, weaker validator for vendor data.
   - `backend/app/data/market_data_loader.py` — the normalized OHLCV frame shape
     (timestamp, open, high, low, close, volume) the rest of the system expects.
     A provider must return frames in this exact shape.
   - `backend/app/models_db/market_data.py` — the existing optional `MarketData`
     table for stored OHLCV; extend it for persisted ingests.
   - `backend/app/core/config.py` — where the vendor selection and API key are
     read from environment (never hardcoded).

3. **Decide the spec as prose and get it approved**: which provider, daily vs
   intraday, backfill range, incremental schedule, adjusted vs raw prices, where
   data is stored, and the licensing conclusion. No code until approved.

## What the provider interface must cover

- A `MarketDataProvider` protocol/ABC with at least: fetch a symbol's OHLCV over
  a date range at a given resolution, returning the normalized frame shape.
- **Backfill** (one-time history pull) and **incremental** (e.g. nightly EOD)
  paths. Incremental must be idempotent — re-running a day must not duplicate
  rows.
- **Corporate actions / adjusted prices.** Splits and dividends must be applied
  so prices are adjusted consistently; getting this wrong silently corrupts every
  backtest. Decide explicitly whether you store adjusted, raw, or both, and which
  the backtester consumes. This is the single most error-prone part — treat it as
  such.
- **Rate-limit and error handling** appropriate to the vendor (retries with
  backoff, partial-batch handling).
- An **ingestion-run audit record** — what was fetched, when, row counts, and
  errors — so data problems are diagnosable after the fact (roadmap §2.4).

## Correctness rules

- **The data-quality report is the gate.** Reuse `data_quality.py`. A batch that
  fails blocking checks (nulls, duplicate/non-monotonic timestamps, negative or
  zero prices, high < low, OHLC out of range) must not be persisted or fed to a
  backtest. Same gate as CSVs, no exceptions for "trusted" vendors.
- **No secrets in code.** Vendor keys come from environment / a secret manager,
  with a documented (non-real) example in `.env.example`. Never commit a key.
- **No look-ahead from adjustments.** Point-in-time correctness matters: a
  backtest as of date D must use the prices/adjustments knowable at D, not
  later-restated values, or results are leaked. Flag this explicitly when storing
  adjusted history.
- **Provider isolation holds.** If you find yourself importing the vendor SDK
  outside the implementation module, stop — the abstraction has leaked.

## Storage and scale

- Postgres at daily resolution is fine to start. Consider a time-series extension
  (e.g. TimescaleDB) **only** when intraday volume actually demands it — not
  speculatively.
- Backfilling large histories or many symbols can be slow; this is where the
  Phase-2 background-job model (roadmap §5) belongs, not inside an HTTP request.

## Verify before declaring done

- A backfill of one symbol persists rows that pass the data-quality gate.
- An incremental re-run is idempotent (no duplicate rows).
- The backtester runs against ingested data with no code change above the
  provider layer (proving the abstraction holds).
- `ruff`, `mypy`, and `pytest` clean, including new ingestion tests.
- A written, dated note records the vendor's redistribution/display terms and the
  conclusion for this deployment.

Hand the result to the `backtest-integrity-reviewer` (point-in-time / adjustment
leakage) and `trading-disclaimer-reviewer` (data licensing & display) agents
before merging.
