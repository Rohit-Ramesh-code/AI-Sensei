"""
agents/confidence_model.py — Random Forest confidence estimator for Project Sentinel.

Trains a RandomForestRegressor on synthetic data that encodes domain knowledge
about how data availability and signal quality map to prediction confidence.

Used as a fallback when the LLM analyst is unavailable, ensuring every flagged
color carries a non-zero, contextually appropriate confidence score rather than
returning None and leaving the Policy Guard with nothing to gate on.

The model trains once at import time (~50 ms) and is reused for every call.

Features (6):
    current_pct  — Current toner level (0–100 %)
    n            — Readings in the 7-day history window
    velocity     — Toner change rate in %/day; 0.0 when history is absent
    std_dev      — Standard deviation of readings; 0.0 when history is absent
    has_history  — 1 if n >= 2, else 0 (separates cold-start from genuinely stable)
    urgency      — 1 = CRITICAL, 0 = WARNING

Output: confidence score clamped to [0.15, 0.95].

Design notes:
- The synthetic target function (_base_confidence) encodes domain rules directly.
  Adding small Gaussian noise to training targets prevents the RF from perfectly
  memorising step boundaries and instead produces smooth interpolated outputs.
- has_history distinguishes std_dev=0.0 due to imputation (n=0) from std_dev=0.0
  because readings are genuinely stable (n=10). Without it the RF conflates the two.
- Bounds [0.15, 0.95]: confidence of 0.0 is epistemically wrong (we always know
  something), and 1.0 is overconfident. The LLM confidence threshold default is
  0.7, so RF scores for sparse data (typically 0.25–0.50) will usually be below
  threshold — alerts fire on deterministic urgency alone, as intended.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import RandomForestRegressor


# ---------------------------------------------------------------------------
# Synthetic target function
# ---------------------------------------------------------------------------

def _base_confidence(
    n: int,
    current_pct: float,
    velocity: float | None,
    std_dev: float | None,
    urgency: int,
) -> float:
    """Compute a synthetic target confidence for a given feature combination.

    Domain rules encoded:
      - More readings → higher base confidence (more evidence to act on)
      - Very low toner adds a small bump regardless of history depth
      - Low std_dev with sufficient history → stable signal → higher confidence
      - High std_dev → erratic readings → lower confidence
      - Fast negative velocity → clear declining trend → higher confidence
      - CRITICAL urgency at cold start: the toner level itself is informative
    """
    # Base from data volume (step function — RF will smooth between steps)
    if n == 0:
        base = 0.25
    elif n == 1:
        base = 0.33
    elif n < 5:
        base = 0.44
    elif n < 12:
        base = 0.54
    elif n < 24:
        base = 0.64
    elif n < 72:
        base = 0.74
    else:
        base = 0.84

    # Toner severity — very low level is informative even without history
    if current_pct <= 5.0:
        base += 0.07
    elif current_pct <= 10.0:
        base += 0.03

    # Signal quality — only meaningful when we actually have readings
    if std_dev is not None and n >= 2:
        if std_dev < 1.5:
            base += 0.06    # Stable readings → high-quality signal
        elif std_dev > 8.0:
            base -= 0.13    # Erratic readings → unreliable
        elif std_dev > 5.0:
            base -= 0.07

    # Velocity — clear decline reinforces confidence in the alert
    if velocity is not None and n >= 2:
        if velocity < -3.0:
            base += 0.05
        elif velocity < -1.0:
            base += 0.02

    # Cold-start CRITICAL: severity alone carries information
    if urgency == 1 and n <= 1:
        base += 0.07

    return round(max(0.15, min(0.95, base)), 3)


# ---------------------------------------------------------------------------
# Synthetic dataset
# ---------------------------------------------------------------------------

def _build_training_data() -> tuple[np.ndarray, np.ndarray]:
    """Generate the synthetic training dataset covering the feature space."""
    n_values     = [0, 1, 2, 3, 5, 7, 10, 12, 15, 18, 24, 36, 48, 72, 96, 120, 168]
    pct_values   = [1.0, 3.0, 5.0, 7.0, 9.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    vel_values   = [None, -5.0, -3.0, -2.0, -1.5, -1.0, -0.5, -0.2, -0.05, 0.0]
    std_values   = [None, 0.3, 0.8, 1.5, 2.5, 4.0, 6.0, 8.0, 10.0]

    rng = np.random.default_rng(42)   # fixed seed → reproducible model
    X, y = [], []

    for n in n_values:
        for pct in pct_values:
            for vel in vel_values:
                effective_vel = vel if n >= 2 else None
                for std in std_values:
                    effective_std = std if n >= 2 else None
                    for urgency in [0, 1]:
                        conf = _base_confidence(n, pct, effective_vel, effective_std, urgency)
                        # Small noise forces the RF to generalise between grid points
                        # rather than memorising hard step boundaries.
                        conf = float(np.clip(conf + rng.normal(0, 0.02), 0.15, 0.95))

                        vel_feat  = effective_vel if effective_vel is not None else 0.0
                        std_feat  = effective_std if effective_std is not None else 0.0
                        has_hist  = 1 if n >= 2 else 0

                        X.append([pct, n, vel_feat, std_feat, has_hist, urgency])
                        y.append(conf)

    return np.array(X, dtype=float), np.array(y, dtype=float)


# ---------------------------------------------------------------------------
# Model — trained once at import time
# ---------------------------------------------------------------------------

def _train() -> RandomForestRegressor:
    X, y = _build_training_data()
    model = RandomForestRegressor(
        n_estimators=100,
        max_depth=8,
        min_samples_leaf=3,
        random_state=42,
    )
    model.fit(X, y)
    return model


_MODEL: RandomForestRegressor = _train()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def predict_confidence(
    current_pct: float,
    n: int,
    velocity: float | None,
    std_dev: float | None,
    urgency: str,
) -> float:
    """Predict a confidence score using the trained Random Forest model.

    Args:
        current_pct: Current toner level in percent (0–100).
        n:           Number of historical readings in the 7-day window.
        velocity:    Rate of change in %/day; None when n < 2.
        std_dev:     Standard deviation of readings; None when n < 2.
        urgency:     'CRITICAL' or 'WARNING'.

    Returns:
        Confidence score in [0.15, 0.95]. Always non-zero: lower when data is
        sparse (n=0 → ~0.25–0.35), higher when history is rich and consistent
        (n=72+ with low std_dev → ~0.80–0.90).
    """
    urgency_enc = 1 if urgency == "CRITICAL" else 0
    has_hist    = 1 if n >= 2 else 0
    vel_feat    = velocity if velocity is not None else 0.0
    std_feat    = std_dev  if std_dev  is not None else 0.0

    features = np.array(
        [[current_pct, n, vel_feat, std_feat, has_hist, urgency_enc]],
        dtype=float,
    )
    raw = float(_MODEL.predict(features)[0])
    return round(max(0.15, min(0.95, raw)), 3)
