import math

import pandas as pd
import pytest

from livenerf.analysis import clustered_mean, paired_vs_baseline


def test_clustered_se_matches_naive_when_clusters_are_singletons():
    v = pd.Series([0.0, 1.0, 1.0, 0.0, 1.0])
    mean, se = clustered_mean(v, pd.Series(range(5)))
    naive = v.std(ddof=0) / math.sqrt(len(v))
    assert mean == pytest.approx(0.6)
    assert se == pytest.approx(naive)


def test_clustered_se_grows_with_correlated_clusters():
    v = pd.Series([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
    _, se_single = clustered_mean(v, pd.Series(range(6)))
    _, se_clustered = clustered_mean(v, pd.Series(["a", "a", "a", "b", "b", "b"]))
    assert se_clustered > se_single


def test_paired_difference():
    base = pd.DataFrame({"item_hash": ["x", "x", "y", "y"], "score": [1.0, 0.8, 0.4, 0.6], "cluster": ["c1", "c1", "c2", "c2"]})
    cur = pd.DataFrame({"item_hash": ["x", "y", "z"], "score": [0.7, 0.5, 1.0], "cluster": ["c1", "c2", "c3"]})
    out = paired_vs_baseline(None, cur, base)
    assert out["items"] == 2  # z has no baseline, so it is not paired
    assert out["delta"] == pytest.approx(((0.7 - 0.9) + (0.5 - 0.5)) / 2)
