"""The trained-model wrapper a strategy consults.

A ``TrainedModel`` bundles everything needed to turn a feature row into a long/flat
decision: the fitted (and usually calibrated) classifier, the exact feature/label
spec it was trained under, and the decision parameters (enter/exit thresholds and the
minimum holding period). It carries no training logic — the trainer (``app.ml.training``)
produces it and the registry (``app.ml.registry``) serializes it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.ml.features import FeatureLabelSpec

# The positive label: P(up) is the probability the model assigns to this class.
_POSITIVE_LABEL = 1


@dataclass
class TrainedModel:
    """A fitted classifier plus its spec and decision parameters."""

    classifier: object  # any sklearn-style estimator exposing predict_proba + classes_
    spec: FeatureLabelSpec
    enter_threshold: float
    exit_threshold: float
    min_hold: int
    calibrated: bool

    def predict_proba_up(self, features: pd.DataFrame | np.ndarray) -> np.ndarray:
        """Calibrated probability of the up class for each row.

        Accepts a frame carrying the spec's feature columns (column order is enforced)
        or a raw array already in feature-column order. Feature names are carried into
        the classifier so its feature-name safety check stays meaningful.
        """
        cols = list(self.spec.feature_columns)
        if isinstance(features, pd.DataFrame):
            frame = features[cols]
        else:
            frame = pd.DataFrame(np.asarray(features, dtype=float), columns=cols)
        proba = self.classifier.predict_proba(frame)  # type: ignore[attr-defined]
        classes = list(self.classifier.classes_)  # type: ignore[attr-defined]
        pos = classes.index(_POSITIVE_LABEL)
        return np.asarray(proba)[:, pos]
