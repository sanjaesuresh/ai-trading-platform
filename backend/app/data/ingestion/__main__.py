"""CLI entrypoint for ingestion commands.

Usage::

    python -m app.data.ingestion backfill [SYMBOL ...]
    python -m app.data.ingestion incremental [SYMBOL ...]

With no symbols the configured ``backfill_universe`` is used. The provider is
chosen from config (Tiingo when ``TIINGO_API_KEY`` is set, else offline).
"""

from __future__ import annotations

import argparse
import sys

from app.data.ingestion.commands import run_backfill, run_incremental


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.data.ingestion")
    parser.add_argument("mode", choices=["backfill", "incremental"])
    parser.add_argument("symbols", nargs="*", help="Symbols (default: configured universe)")
    args = parser.parse_args(argv)

    symbols = args.symbols or None
    runs = (run_backfill if args.mode == "backfill" else run_incremental)(symbols)

    failed = 0
    for run in runs:
        line = f"  {run.symbol}: {run.status} ({run.rows_written or 0} written)"
        if run.error:
            line += f" — {run.error}"
            failed += 1
        print(line)
    print(f"{args.mode}: {len(runs)} symbol(s), {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
