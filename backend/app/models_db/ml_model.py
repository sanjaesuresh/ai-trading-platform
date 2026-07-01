"""Postgres mirror of a registered ML model's metadata (Phase 4 M4).

One row per trained model, keyed by the content-hash model_id the filesystem
registry assigns. The columns mirror the scalar fields of ``registry.ModelMetadata``
(note: ``feature_columns`` is intentionally not stored — it is derivable from the
feature spec version). Alembic migration 0005_phase4_ml creates this table.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models_db.base import Base


class MLModel(Base):
    __tablename__ = "ml_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The content-hash id the registry assigns (first 16 hex chars of artifact SHA-256).
    model_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    feature_spec_version: Mapped[str] = mapped_column(String(32), nullable=False)
    # JSON list of str: the symbols the training pool included.
    symbols: Mapped[list] = mapped_column(JSON, nullable=False)
    train_start: Mapped[str] = mapped_column(String(64), nullable=False)
    train_end: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    deadband: Mapped[float] = mapped_column(Float, nullable=False)
    # JSON dict: the LightGBM hyperparameters used for this model.
    lgbm_params: Mapped[dict] = mapped_column(JSON, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    num_threads: Mapped[int] = mapped_column(Integer, nullable=False)
    calibration: Mapped[str] = mapped_column(String(32), nullable=False)
    calibrated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enter_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    exit_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    min_hold: Mapped[int] = mapped_column(Integer, nullable=False)
    n_fit: Mapped[int] = mapped_column(Integer, nullable=False)
    n_calib: Mapped[int] = mapped_column(Integer, nullable=False)
    n_thresh: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_n: Mapped[float] = mapped_column(Float, nullable=False)
    # JSON dict: the selection/threshold-tuning knobs (cost_bps, grids, etc.).
    selection_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    # JSON dict: validation metrics (auc, brier, etc.) from the threshold fold.
    validation_metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    code_git_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_dirty: Mapped[bool] = mapped_column(Boolean, nullable=False)
    code_diff_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    # Phase 5 provenance (§4) — nullable so price-only models record None.
    news_feature_spec_version: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    annotation_model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    annotation_prompt_version: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    news_feature_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
