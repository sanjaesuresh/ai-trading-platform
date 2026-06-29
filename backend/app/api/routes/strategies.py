"""Strategy discovery endpoint: list available strategies and their param schemas.

Read-only. This is the API half of the strategy selector; the frontend form that
consumes it is M7.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.strategy import StrategyInfo
from app.strategies.registry import list_strategies

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyInfo])
def list_available_strategies() -> list[StrategyInfo]:
    """Return registered strategies with their JSON parameter schemas."""
    return [StrategyInfo(**s) for s in list_strategies()]
