"""Phase 4 machine-learning package.

Point-in-time feature/label construction, the leakage-safe training pipeline,
and the prediction wrapper a strategy consults. Pure logic where possible; the
trainer is the only part that touches the model directory and the registry.

Nothing here reaches back into the engine, the Phase 3 portfolio core, or the
broker layer — a trained model enters the system only as a ``BaseStrategy``.
"""
