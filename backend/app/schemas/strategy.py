"""Response contract for strategy discovery."""

from __future__ import annotations

from pydantic import BaseModel


class StrategyInfo(BaseModel):
    """One registered strategy and its JSON parameter schema."""

    name: str
    params_schema: dict
