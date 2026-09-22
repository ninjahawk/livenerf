"""Read Inspect .eval logs into a flat table and compare windows against the baseline.

The primary statistic follows Miller, "Adding Error Bars to Evals" (arXiv:2411.00640):
per-item paired differences (window mean - baseline mean), averaged over items, with standard
errors clustered by item template (items from one template are not independent).
"""

import math
from datetime import datetime, timedelta

import pandas as pd

BASELINE_HOURS = 72  # PREREGISTRATION.md: the first 72 hours after the first frozen-panel run


def load_samples(log_dir: str) -> pd.DataFrame:
    from inspect_ai.log import list_eval_logs, read_eval_log

    rows = []
    for info in list_eval_logs(log_dir):
        log = read_eval_log(info)
        created = pd.Timestamp(log.eval.created).tz_convert("UTC")
        for s in log.samples or []:
            score = next(iter(s.scores.values())) if s.scores else None
            usage = next(iter(s.model_usage.values())) if s.model_usage else None
            out_meta = (s.output.metadata or {}) if s.output else {}
            rows.append({
                "run_created": created,
                "task": log.eval.task,
                "task_version": log.eval.task_version,
                "model": log.eval.model,
                "harness_sha": (log.eval.metadata or {}).get("harness_sha"),
                "id": s.id,
                "epoch": s.epoch,
                "family": s.metadata.get("family"),
                "cluster": s.metadata.get("cluster"),
                "level": s.metadata.get("level"),
                "item_hash": s.metadata.get("item_hash"),
                "score": float(score.value) if score is not None and s.error is None else math.nan,
                "exact": bool((score.metadata or {}).get("exact")) if score is not None else False,
                "answered": bool((score.metadata or {}).get("answered")) if score is not None else False,
                "error": str(s.error.message)[:200] if s.error else None,
                "output_tokens": usage.output_tokens if usage else math.nan,
                "reasoning_tokens": usage.reasoning_tokens if usage and usage.reasoning_tokens is not None else math.nan,
                "input_tokens": usage.input_tokens if usage else math.nan,
                "cli_version": out_meta.get("cli_version"),
                "served_models": ",".join(out_meta.get("served_models") or []),
                "hour_utc": created.hour,
            })
    return pd.DataFrame(rows)


def clustered_mean(values: pd.Series, clusters: pd.Series) -> tuple[float, float]:
    """Mean and cluster-robust standard error (Miller 2024, eq. for clustered SE)."""
    v = values.to_numpy(dtype=float)
    n = len(v)
    if n == 0:
        return math.nan, math.nan
    mean = v.mean()
    resid = pd.Series(v - mean, index=values.index)
    per_cluster = resid.groupby(clusters.to_numpy()).sum()
    se = math.sqrt((per_cluster**2).sum()) / n if n > 1 else math.nan
    return mean, se


def paired_vs_baseline(df: pd.DataFrame, window: pd.DataFrame, baseline: pd.DataFrame) -> dict:
    base = baseline.groupby("item_hash").agg(base=("score", "mean"), cluster=("cluster", "first"))
    cur = window.groupby("item_hash").agg(cur=("score", "mean"))
    joined = base.join(cur, how="inner").dropna()
    diff = joined["cur"] - joined["base"]
    mean, se = clustered_mean(diff, joined["cluster"])
    return {"items": len(joined), "delta": mean, "se": se, "ci95": (mean - 1.96 * se, mean + 1.96 * se)}


def baseline_end_for(df: pd.DataFrame) -> datetime:
    return (df["run_created"].min() + timedelta(hours=BASELINE_HOURS)).to_pydatetime()


def summarize(df: pd.DataFrame, baseline_end: datetime | None = None, freq: str = "D") -> pd.DataFrame:
    baseline_end = baseline_end or baseline_end_for(df)
    ok = df[df["error"].isna()]
    baseline = ok[ok["run_created"] < pd.Timestamp(baseline_end)]
    rows = []
    periods = df["run_created"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period(freq)
    cutoff = pd.Timestamp(baseline_end).tz_convert("UTC").tz_localize(None)
    for period, window in df.groupby(periods):
        good = window[window["error"].isna()]
        score, score_se = clustered_mean(good["score"], good["cluster"])
        in_baseline = period.start_time < cutoff
        if in_baseline or not len(baseline):
            paired = {"items": 0, "delta": math.nan, "se": math.nan}  # rendered as "baseline"
        else:
            paired = paired_vs_baseline(df, good, baseline)
        rows.append({
            "window": str(period),
            "samples": len(window),
            "errors": int(window["error"].notna().sum()),
            "score": score,
            "score_se": score_se,
            "paired_items": paired["items"],
            "delta_vs_baseline": paired["delta"],
            "delta_se": paired["se"],
            "output_tokens_median": good["output_tokens"].median(),
            "reasoning_tokens_median": good["reasoning_tokens"].median(),
            "cli_versions": ",".join(sorted(set(good["cli_version"].dropna()))),
        })
    return pd.DataFrame(rows)


def markdown_table(summary: pd.DataFrame) -> str:
    lines = [
        "| window | samples | errors | score ± SE | Δ vs baseline ± SE (items) | output tok (median) | CLI |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in summary.itertuples():
        delta = "baseline" if math.isnan(r.delta_vs_baseline) else f"{r.delta_vs_baseline:+.3f} ± {r.delta_se:.3f} ({r.paired_items})"
        lines.append(
            f"| {r.window} | {r.samples} | {r.errors} | {r.score:.3f} ± {r.score_se:.3f} | {delta} | "
            f"{r.output_tokens_median:.0f} | {r.cli_versions} |"
        )
    return "\n".join(lines)
