"""News ingestion (Phase 5 M2).

Backfill + incremental ingest of news items, mirroring ``app.data.ingestion`` for
market data. Pure logic lives in ``logic.py``; the only SQLAlchemy I/O lives in
``db.py``.
"""
