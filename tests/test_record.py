import math

import pandas as pd

from livenerf.common import REPO_ROOT
from livenerf.record import COLUMNS, daily_record
from livenerf.schedule import harness_content_hash


def test_harness_matches_the_series_lock():
    # the daily run refuses on a mismatch; this catches a sample-shaping edit before it is pushed
    assert harness_content_hash() == (REPO_ROOT / "data" / "harness.lock").read_text().strip()


def test_daily_record_has_one_row_per_day_model_and_family():
    t = pd.Timestamp
    df = pd.DataFrame({
        "run_created": [t("2026-09-24 22:10", tz="UTC")] * 3 + [t("2026-09-26 00:07", tz="UTC")],
        "model": ["m"] * 4, "arm": ["measured"] * 4, "family": ["gpqa", "gpqa", "aime", "gpqa"],
        "score": [1.0, 0.0, math.nan, 1.0], "error": [None, None, "[retried]", None],
        "error_kind": [None, None, "retried", None], "output_tokens": [10, 20, math.nan, 30],
        "cli_version": ["2.1.280"] * 4, "harness_content": ["h"] * 4, "funding_source": [None] * 4,
    })
    rec = daily_record(df)
    assert list(rec.columns) == COLUMNS
    day1 = rec[(rec["series_day"] == 1) & (rec["family"] == "all")].iloc[0]
    assert (day1["samples"], day1["scored"], day1["classifier_events"], day1["score"]) == (3, 2, 1, 0.5)
    assert day1["funding_source"] == "max"
    assert day1["runner"] == "host"  # logs without a runner label came from this PC
    assert sorted(rec["series_day"].unique()) == [1, 3]  # a missed day keeps its number
