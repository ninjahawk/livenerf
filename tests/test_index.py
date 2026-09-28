import math

import numpy as np
import pytest

from livenerf.index import _frame, day_variance, drift, fast_day_variance, fast_drift, item_table


def _series(seed=0, days=20, k=30):
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.2, 0.9, k)
    y = (rng.random((1, days, k)) < p).astype(float)
    l = 0.5 * rng.standard_normal((1, days, k)) + rng.normal(6, 1, k)
    return y, l


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_fast_path_matches_the_log_path(seed):
    """The simulation's array estimators equal the ones that run on real logs."""
    y, l = _series(seed)
    b = 0.5
    base, win = _frame(y[0, :10], l[0, :10], 0), _frame(y[0, 10:], l[0, 10:], 10)
    d, f = drift(item_table(win, base), b), fast_drift(y[:, :10], l[:, :10], y[:, 10:], l[:, 10:], b)
    for key in ("dacc", "dacc_se", "dl", "dl_se", "rho", "rho_se"):
        assert d[key] == pytest.approx(float(f[key][0]), rel=1e-9, abs=1e-12), key
    dv, fv = day_variance(base, b), fast_day_variance(y[:, :10], l[:, :10], b)
    for key in ("s2_acc", "s2_dl", "s2_rho"):
        assert dv[key] == pytest.approx(float(fv[key][0]), rel=1e-9, abs=1e-12), key


def test_equation_splits_a_pure_thinking_change():
    """A token change that carries exactly b logits per e-fold leaves ρ at 0."""
    k, b = 40, 0.5
    y_b = ((np.arange(10)[:, None] + np.arange(k)[None, :]) % 2).astype(float)  # every item at p = 0.5
    l_b = np.zeros((10, k))
    base = _frame(y_b, l_b, 0)
    items = item_table(_frame(y_b, l_b + math.log(0.5), 10), base)
    w_bar = float((items["p"] * (1 - items["p"])).mean())
    items["dacc"] = b * math.log(0.5) * w_bar  # the accuracy change thinking half as much buys
    d = drift(items, b)
    assert d["dl"] == pytest.approx(math.log(0.5))
    assert d["rho"] == pytest.approx(0.0, abs=1e-12)
    assert d["effort_equivalent_pct"] == pytest.approx(-50.0)


def test_report_runs_on_log_shaped_data(monkeypatch):
    """The report path that meets the real logs: 25 days, so a baseline and one full window."""
    import livenerf.index as ix

    y, l = _series(seed=3, days=25, k=30)
    df = _frame(y[0], l[0], 0).assign(model="claudecode/claude-opus-5-5")
    monkeypatch.setattr(ix, "load_samples", lambda _: df)
    text = ix.report_logs("unused", "claudecode/claude-opus-5-5")
    assert "baseline: 10 days" in text and "| days 11-20 | 30 |" in text
    assert "| days 21-30 (5 days so far) |" in text  # a partial window says so
