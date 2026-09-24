"""Read Inspect .eval logs into a flat table and compare windows against the baseline.

The primary statistic follows Miller, "Adding Error Bars to Evals" (arXiv:2411.00640):
per-item paired differences (window mean - baseline mean), averaged over items, with standard
errors clustered by item template (items from one template are not independent).
"""

import math
from datetime import datetime, timedelta

import pandas as pd

BASELINE_HOURS = 336  # PREREGISTRATION.md: the first 14 days after the first series run (two whole weekly cycles)
WINDOW_DAYS = {"D": 1, "W": 7, "F": 14}  # F (fortnight) is the pre-registered decision window
MEASURED_MODEL = "claudecode/claude-opus-5-5"
PRIMARY_FAMILIES = ("gpqa", "mmlupro", "comps", "aime")  # the calibrated standard panel (livenerf.benchmarks.data.FAMILIES)

# pre-registered decision rule (PREREGISTRATION.md)
Z_DECISION = 2.576
MIN_EFFECT = 0.03
MAX_ERROR_RATE = 0.05


def error_kind(message: str | None) -> str | None:
    """Bucket sample errors. Classifier events (refusal/retried/fallback) are a secondary metric."""
    if not message:
        return None
    for tag in ("fallback", "retried", "refusal", "context"):
        if f"[{tag}]" in message:
            return tag
    if "respond to this message" in message:  # Claude Code's classifier refusal, e.g. "Details: `[bio]`"
        return "refusal"
    if "timed out" in message:
        return "timeout"
    return "other"


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
                "arm": (log.eval.metadata or {}).get("arm", "measured"),
                "harness_sha": (log.eval.metadata or {}).get("harness_sha"),
                "harness_content": ((log.eval.metadata or {}).get("harness_sha") or "").partition("+")[2] or None,
                "id": s.id,
                "epoch": s.epoch,
                "family": s.metadata.get("family"),
                "cluster": s.metadata.get("cluster"),
                "level": s.metadata.get("level"),
                "chance": float(s.metadata.get("chance") or 0.0),
                "item_hash": s.metadata.get("item_hash"),
                "score": float(score.value) if score is not None and s.error is None else math.nan,
                "exact": bool((score.metadata or {}).get("exact")) if score is not None else False,
                "answered": bool((score.metadata or {}).get("answered")) if score is not None else False,
                "error": str(s.error.message)[-300:] if s.error else None,
                "error_kind": error_kind(str(s.error.message)) if s.error else None,
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
    g = len(per_cluster)
    # the standard G/(G-1) small-sample correction for a cluster-robust variance
    se = math.sqrt((per_cluster**2).sum() * g / (g - 1)) / n if n > 1 and g > 1 else math.nan
    return mean, se


def paired_vs_baseline(df: pd.DataFrame, window: pd.DataFrame, baseline: pd.DataFrame) -> dict:
    base = baseline.groupby("item_hash").agg(base=("score", "mean"), cluster=("cluster", "first"))
    cur = window.groupby("item_hash").agg(cur=("score", "mean"))
    joined = base.join(cur, how="inner").dropna()
    diff = joined["cur"] - joined["base"]
    mean, se = clustered_mean(diff, joined["cluster"])
    return {"items": len(joined), "delta": mean, "se": se, "ci95": (mean - 1.96 * se, mean + 1.96 * se)}


def paired_tokens_vs_baseline(window: pd.DataFrame, baseline: pd.DataFrame) -> dict:
    """Secondary analysis 1: per-item log ratio of mean output tokens, window vs baseline, item-clustered."""
    base = baseline.groupby("item_hash").agg(base=("output_tokens", "mean"), cluster=("cluster", "first"))
    cur = window.groupby("item_hash").agg(cur=("output_tokens", "mean"))
    joined = base.join(cur, how="inner").dropna()
    joined = joined[(joined["base"] > 0) & (joined["cur"] > 0)]
    if joined.empty:
        return {"items": 0, "change_pct": math.nan, "ci99_pct": (math.nan, math.nan)}
    lr = (joined["cur"] / joined["base"]).map(math.log)
    m, se = clustered_mean(lr, joined["cluster"])
    pct = lambda v: 100 * (math.exp(v) - 1)  # noqa: E731
    return {"items": len(joined), "change_pct": pct(m), "ci99_pct": (pct(m - Z_DECISION * se), pct(m + Z_DECISION * se))}


def baseline_end_for(df: pd.DataFrame) -> datetime:
    return (df["run_created"].min() + timedelta(hours=BASELINE_HOURS)).to_pydatetime()


def primary(df: pd.DataFrame) -> pd.DataFrame:
    """The primary metric's samples: the measured model on the calibrated standard panel."""
    return df[(df["model"] == MEASURED_MODEL) & df["family"].isin(PRIMARY_FAMILIES)]


def synthetic(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["model"] == MEASURED_MODEL) & ~df["family"].isin(PRIMARY_FAMILIES)]


def control(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["model"] != MEASURED_MODEL]


def decision(summary: pd.DataFrame) -> list[dict]:
    """Apply the pre-registered rule to 2-week windows: a change is declared only when two consecutive
    windows both exclude 0 from the 99% CI, both have |delta| >= 3 points in the same direction, both have
    an error rate below 5%, and the harness (CLI version and sample-shaping code hash) matches the baseline's."""
    weeks = summary[~summary["delta_vs_baseline"].isna()].reset_index(drop=True)
    base_cli = summary["cli_versions"].iloc[0] if len(summary) else ""
    base_harness = summary["harness_hashes"].iloc[0] if len(summary) and "harness_hashes" in summary else ""
    out = []
    for i, r in weeks.iterrows():
        sig = abs(r.delta_vs_baseline) > Z_DECISION * r.delta_se and abs(r.delta_vs_baseline) >= MIN_EFFECT
        ok = (r.errors / max(r.samples, 1) < MAX_ERROR_RATE and r.cli_versions == base_cli
              and getattr(r, "harness_hashes", "") == base_harness)
        prev = out[-1] if out else None
        change = bool(sig and ok and prev and prev["qualifies"]
                      and (r.delta_vs_baseline > 0) == (prev["delta"] > 0))
        out.append({"window": r.window, "delta": r.delta_vs_baseline, "se": r.delta_se, "qualifies": bool(sig and ok),
                    "change_declared": change})
    return out


def realized_mde(baseline: pd.DataFrame) -> dict:
    """The weekly MDE implied by baseline data alone (pre-registered: computed before any comparison).

    Each item's variance is its baseline p(1-p). A 2-week window is assumed to sample each item as
    often as the (2-week) baseline did, and the baseline mean has its own sampling error, so
    Var(delta) = (1/K^2) * sum_i p_i(1-p_i) * (1/m_window_i + 1/m_base_i)."""
    ok = baseline[baseline["error"].isna()]
    if ok.empty:
        return {"items": 0, "se_points": math.nan, "mde_points": math.nan}
    days = max((ok["run_created"].max() - ok["run_created"].min()).total_seconds() / 86400, 1.0)
    g = ok.groupby("item_hash")["score"].agg(["mean", "size"])
    m_window = g["size"] * WINDOW_DAYS["F"] / days
    var = (g["mean"] * (1 - g["mean"]) * (1 / m_window + 1 / g["size"])).sum() / len(g) ** 2
    se = math.sqrt(var)
    return {"items": len(g), "se_points": 100 * se, "mde_points": 100 * (Z_DECISION + 0.842) * se}


def summarize(df: pd.DataFrame, baseline_end: datetime | None = None, freq: str = "D") -> pd.DataFrame:
    baseline_end = baseline_end or baseline_end_for(df)
    ok = df[df["error"].isna()]
    baseline = ok[ok["run_created"] < pd.Timestamp(baseline_end)]
    rows = []
    # windows are anchored at the series start (days at UTC midnight), so the baseline is a whole
    # number of windows and every window has the same length
    ts = df["run_created"].dt.tz_convert("UTC").dt.tz_localize(None)
    days = WINDOW_DAYS[freq.upper()]
    origin = ts.min().floor("D")
    starts = origin + ((ts - origin) // pd.Timedelta(days=days)) * pd.Timedelta(days=days)
    cutoff = pd.Timestamp(baseline_end).tz_convert("UTC").tz_localize(None)
    for start, window in df.groupby(starts):
        good = window[window["error"].isna()]
        score, score_se = clustered_mean(good["score"], good["cluster"])
        in_baseline = start < cutoff
        if in_baseline or not len(baseline):
            paired = {"items": 0, "delta": math.nan, "se": math.nan}  # rendered as "baseline"
            tokens = {"change_pct": math.nan, "ci99_pct": (math.nan, math.nan)}
        else:
            paired = paired_vs_baseline(df, good, baseline)
            tokens = paired_tokens_vs_baseline(good, baseline)
        rows.append({
            "window": f"{start:%Y-%m-%d}" + (f" +{days}d" if days > 1 else ""),
            "samples": len(window),
            "errors": int(window["error"].notna().sum()),
            "classifier_events": int(window["error_kind"].isin(["refusal", "retried", "fallback"]).sum()),
            "score": score,
            "score_se": score_se,
            "paired_items": paired["items"],
            "delta_vs_baseline": paired["delta"],
            "delta_se": paired["se"],
            "output_tokens_median": good["output_tokens"].median(),
            "reasoning_tokens_median": good["reasoning_tokens"].median(),
            "tokens_change_pct": tokens["change_pct"],
            "tokens_ci99_pct": tokens["ci99_pct"],
            "cli_versions": ",".join(sorted(set(good["cli_version"].dropna()))),
            "harness_hashes": ",".join(sorted(set(good["harness_content"].dropna()))) if "harness_content" in good else "",
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
