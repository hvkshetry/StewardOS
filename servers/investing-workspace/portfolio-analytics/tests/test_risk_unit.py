from __future__ import annotations

import numpy as np
import pandas as pd

from risk import _detect_vol_regime


def test_regime_detection_unit() -> None:
    rng = np.random.default_rng(42)
    returns = pd.Series(rng.normal(0.0005, 0.01, 252))

    regime = _detect_vol_regime(returns)

    assert regime["current_regime"] in ("low", "normal", "elevated")
    assert regime["vol_ratio"] > 0


def test_regime_crisis_detection() -> None:
    rng = np.random.default_rng(42)
    calm = rng.normal(0.0005, 0.005, 252)
    crisis = rng.normal(-0.005, 0.06, 21)
    returns = pd.Series(np.concatenate([calm, crisis]))

    regime = _detect_vol_regime(returns)

    assert regime["vol_ratio"] > 1.3


def test_regime_days_in_regime_uses_trailing_windows() -> None:
    returns = pd.Series([1.0, -1.0, 1.0, -1.0, 0.1, -0.1])

    regime = _detect_vol_regime(returns, short_window=2, long_window=4)

    assert regime["current_regime"] == "low"
    assert regime["days_in_regime"] == 1
