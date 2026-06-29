"""Shared test setup.

Provide a dummy ``DATABASE_URL`` so the service/API layers — which construct
``Settings`` (and a lazy SQLAlchemy engine) at import time — can be imported in
the no-DB unit suite. The engine is never connected to in these tests: pure-logic
paths and 4xx validation paths return before any query runs. A real env var (set
for the manual integration step) takes precedence via ``setdefault``.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test_unused"
)
