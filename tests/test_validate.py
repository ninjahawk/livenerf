import random

import pandas as pd


def test_report_detects_a_token_drop_and_passes_a_clean_aa(tmp_path, monkeypatch):
    from livenerf import validate

    rng = random.Random(0)
    rows = []
    for i in range(40):
        p = rng.uniform(0.3, 0.8)
        for arm, tok, dp in (("high", 800, 0), ("medium", 600, 0), ("low", 300, -0.1), ("opus-5", 700, -0.2)):
            for r in range(4):
                rows.append({"id": f"gpqa-{i}", "effort": arm, "family": "gpqa", "cluster": f"gpqa-{i}",
                             "score": float(rng.random() < p + dp), "error": False,
                             "output_tokens": tok * rng.uniform(0.8, 1.2), "created": f"2026-09-23T0{r}:00:00"})
    monkeypatch.setattr(validate, "samples", lambda: pd.DataFrame(rows))
    monkeypatch.setattr(validate, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    text = validate.report()
    assert "**Result: PASS.**" in text and "Opus 5 (high)" in text and "distinguishable at 99%" in text
