"""Parameter-grid expansion for sweeps (pure logic).

Turns a grid of ``{param_name: [values]}`` into the full Cartesian product of
parameter dicts, each validated against the strategy's own param model via the
registry — so a bad combination is a clean client error, never a mid-sweep 500.
``count_combinations`` gives the product size without materialising the list, so
the size guard can reject an oversized sweep before any work is done.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from app.strategies.registry import resolve_strategy


def count_combinations(grid: dict[str, list]) -> int:
    """Number of combinations the grid expands to (1 for an empty grid).

    Pure arithmetic over the per-key list lengths — does not build the product,
    so the sweep size guard can reject early. An empty value list makes the
    product 0 (no combinations).
    """
    return math.prod((len(values) for values in grid.values()), start=1)


def expand_param_grid(strategy_name: str, grid: dict[str, list]) -> list[dict[str, Any]]:
    """Expand *grid* to the validated Cartesian product of parameter dicts.

    Iterates over keys in sorted order for a deterministic combination order.
    Each combination is validated by constructing the strategy through the
    registry (the returned strategy is discarded — we want only the validation).
    An empty grid yields ``[{}]`` (a single combo that uses the strategy's own
    defaults).

    Propagates the registry's exceptions unchanged: ``UnknownStrategyError`` for
    an unregistered name, ``StrategyParamError`` for a combination that fails the
    strategy's param model.
    """
    keys = sorted(grid)
    value_lists = [grid[key] for key in keys]
    combos: list[dict[str, Any]] = []
    for values in itertools.product(*value_lists):
        combo = dict(zip(keys, values, strict=True))
        resolve_strategy(strategy_name, combo)  # validate; discard the strategy
        combos.append(combo)
    return combos
