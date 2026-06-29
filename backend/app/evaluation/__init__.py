"""Out-of-sample, overfitting-aware evaluation layer (Phase 2 M5).

Pure-logic units — parameter-grid expansion, walk-forward splitting, and
distribution aggregation — plus a thin runner that drives the existing
backtesting engine and metrics. Nothing here reimplements the trade loop or the
metric math; it reuses ``app.backtesting`` and reports the *full distribution*
of results net of fees against the rule-based baseline.
"""
