"""Model registry: filesystem artifacts + reproducibility metadata.

A trained model is serialized to a configured, gitignored model directory as a joblib
artifact plus a JSON metadata sidecar. The metadata captures everything needed to
reproduce or audit the model (plan 3.2, §7): the feature/label spec, the training
window, the LightGBM hyperparameters, the seed and thread count, the decision
thresholds, the validation metrics, the artifact content hash, and the **code version
including dirty-tree state** — a bare git hash silently misrepresents a model trained
with uncommitted changes.

The artifact is self-describing (a ``TrainedModel`` round-trips to identical
predictions); the JSON makes a model auditable and queryable without loading it. M4
mirrors this metadata into a Postgres table the API queries.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib

from app.ml import features as _features
from app.ml import news_features as _news_features
from app.ml.features import FeatureLabelSpec
from app.ml.model import TrainedModel
from app.ml.training import TrainingConfig, TrainingResult

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class CodeVersion:
    git_hash: str
    dirty: bool
    diff_hash: str | None


def current_code_version() -> CodeVersion:
    """Best-effort git provenance. Returns ``unknown`` if git is unavailable.

    When the working tree is dirty, records a hash of the diff so two models trained
    from the same commit but different uncommitted changes are distinguishable.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        git_hash = head.stdout.strip() or "unknown"
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        dirty = bool(status.stdout.strip())
        diff_hash: str | None = None
        if dirty:
            diff = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            diff_hash = hashlib.sha256(diff.stdout.encode()).hexdigest()[:16]
        return CodeVersion(git_hash=git_hash, dirty=dirty, diff_hash=diff_hash)
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - env dependent
        return CodeVersion(git_hash="unknown", dirty=False, diff_hash=None)


@dataclass
class ModelMetadata:
    """Everything needed to reproduce and audit a registered model."""

    model_id: str
    feature_spec_version: str
    feature_columns: list[str]
    horizon: int
    deadband: float
    symbols: list[str]
    train_start: str
    train_end: str
    lgbm_params: dict[str, object]
    seed: int
    num_threads: int
    calibration: str
    calibrated: bool
    enter_threshold: float
    exit_threshold: float
    min_hold: int
    n_fit: int
    n_calib: int
    n_thresh: int
    effective_n: float
    # Every tuned knob behind threshold/hyperparameter selection, so M3's deflated-Sharpe
    # configuration count N is derivable from the model record alone (plan §8).
    selection_config: dict[str, object]
    validation_metrics: dict[str, float]
    code_git_hash: str
    code_dirty: bool
    code_diff_hash: str | None
    artifact_hash: str
    # Phase 5 provenance (§4). Defaulted so old price-only metadata JSON still loads
    # and a price-only model records None for all of them. A price-plus-news model
    # carries the news feature-spec version it was built under plus the annotation
    # model id and prompt version it consumed, so a result produced under a
    # superseded prompt is identifiable rather than conflated with a current one.
    news_feature_spec_version: str | None = None
    annotation_model_id: str | None = None
    annotation_prompt_version: str | None = None
    news_feature_config: dict[str, object] | None = None


def _artifact_path(model_dir: Path, model_id: str) -> Path:
    return model_dir / f"{model_id}.joblib"


def _metadata_path(model_dir: Path, model_id: str) -> Path:
    return model_dir / f"{model_id}.json"


def save_model(
    result: TrainingResult,
    *,
    symbols: list[str],
    config: TrainingConfig,
    model_dir: str | Path,
    code_version: CodeVersion | None = None,
    annotation_model_id: str | None = None,
    annotation_prompt_version: str | None = None,
    news_feature_config: dict[str, object] | None = None,
) -> ModelMetadata:
    """Serialize a trained model and write its metadata. Returns the metadata.

    The model id is the content hash of the serialized artifact, so an identical model
    serializes to the same id (idempotent). The model directory is created if needed.
    """
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    code_version = code_version or current_code_version()

    buffer = io.BytesIO()
    joblib.dump(result.model, buffer)
    payload = buffer.getvalue()
    artifact_hash = hashlib.sha256(payload).hexdigest()
    model_id = artifact_hash[:16]

    _artifact_path(model_dir, model_id).write_bytes(payload)

    metadata = ModelMetadata(
        model_id=model_id,
        feature_spec_version=result.model.spec.version,
        feature_columns=list(result.model.spec.feature_columns),
        horizon=result.model.spec.horizon,
        deadband=result.model.spec.deadband,
        news_feature_spec_version=result.model.spec.news_version,
        annotation_model_id=annotation_model_id,
        annotation_prompt_version=annotation_prompt_version,
        news_feature_config=dict(news_feature_config) if news_feature_config else None,
        symbols=list(symbols),
        train_start=str(result.train_start),
        train_end=str(result.train_end),
        lgbm_params=dict(config.lgbm_params),
        seed=config.seed,
        num_threads=config.num_threads,
        calibration=config.calibration,
        calibrated=result.model.calibrated,
        enter_threshold=result.model.enter_threshold,
        exit_threshold=result.model.exit_threshold,
        min_hold=result.model.min_hold,
        n_fit=result.n_fit,
        n_calib=result.n_calib,
        n_thresh=result.n_thresh,
        effective_n=result.effective_n,
        selection_config={
            "cost_bps": config.cost_bps,
            "hysteresis_gap": config.hysteresis_gap,
            "enter_grid_lo": config.enter_grid_lo,
            "enter_grid_hi": config.enter_grid_hi,
            "enter_grid_step": config.enter_grid_step,
            "min_selected": config.min_selected,
            "fit_fraction": config.fit_fraction,
            "calib_fraction": config.calib_fraction,
            "early_stopping_rounds": config.early_stopping_rounds,
        },
        validation_metrics=result.validation_metrics,
        code_git_hash=code_version.git_hash,
        code_dirty=code_version.dirty,
        code_diff_hash=code_version.diff_hash,
        artifact_hash=artifact_hash,
    )
    _metadata_path(model_dir, model_id).write_text(json.dumps(asdict(metadata), indent=2))
    return metadata


def load_model(model_id: str, model_dir: str | Path) -> TrainedModel:
    """Load a serialized model. Raises ``FileNotFoundError`` if it is not registered."""
    path = _artifact_path(Path(model_dir), model_id)
    if not path.exists():
        raise FileNotFoundError(f"No registered model artifact for id '{model_id}'.")
    model = joblib.load(path)
    if not isinstance(model, TrainedModel):  # pragma: no cover - corruption guard
        raise TypeError(f"Artifact '{model_id}' is not a TrainedModel.")
    return model


def load_metadata(model_id: str, model_dir: str | Path) -> ModelMetadata:
    """Load a model's metadata. Raises ``FileNotFoundError`` if it is not registered."""
    path = _metadata_path(Path(model_dir), model_id)
    if not path.exists():
        raise FileNotFoundError(f"No registered model metadata for id '{model_id}'.")
    return ModelMetadata(**json.loads(path.read_text()))


def list_models(model_dir: str | Path) -> list[ModelMetadata]:
    """All registered models' metadata, newest-first by train_end."""
    model_dir = Path(model_dir)
    if not model_dir.exists():
        return []
    metas = [
        ModelMetadata(**json.loads(p.read_text()))
        for p in sorted(model_dir.glob("*.json"))
    ]
    return sorted(metas, key=lambda m: m.train_end, reverse=True)


def live_feature_versions() -> dict[str, str]:
    """The live, code-resident version authority: {component-name -> version}.

    Read from the live module globals at call time (not the spec a model carries —
    self-validation would always pass and silently lose drift detection). A model
    is validated against THIS, component by component (Phase 5 §3).
    """
    return {
        "price": _features.FEATURE_SPEC_VERSION,
        "news": _news_features.NEWS_FEATURE_SPEC_VERSION,
    }


def model_component_versions(spec: FeatureLabelSpec) -> dict[str, str]:
    """The component feature-spec versions a model carries.

    A price-only model carries one ("price"); a price-plus-news model carries two
    ("price" and "news"). Each gates with equal force in ``assert_live_spec``.
    """
    versions = {"price": spec.version}
    if spec.news_version is not None:
        versions["news"] = spec.news_version
    return versions


def assert_live_spec(model: TrainedModel) -> None:
    """Refuse a model whose feature spec no longer matches the live code (plan §4, §3).

    Checks **every** component the model carries against the live version authority,
    never the spec the model carries. A silent feature-spec drift — including a
    changed news decay half-life, z-score window, or event taxonomy that didn't bump
    the news version — would feed the model inputs that mean something different from
    what it was trained on, with full confidence. The price-only check is byte-for-
    byte the Phase 4 behavior (a price-only model carries no news component).
    """
    live = live_feature_versions()
    for name, version in model_component_versions(model.spec).items():
        expected = live.get(name)
        if expected is None:  # pragma: no cover - guards an unknown component
            raise ValueError(
                f"Model carries an unknown feature component '{name}'; "
                "refusing to run a model the live code cannot validate."
            )
        if version != expected:
            raise ValueError(
                f"Model {name} feature-spec '{version}' does not match the live "
                f"spec '{expected}'; refusing to run a stale model."
            )
