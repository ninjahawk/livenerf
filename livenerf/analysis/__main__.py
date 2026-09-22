"""python -m livenerf.analysis [--log-dir logs] [--freq D|W] [--csv out.csv]"""

import argparse

import pandas as pd

from ..common import REPO_ROOT
from . import load_samples, markdown_table, summarize


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", default=str(REPO_ROOT / "logs"))
    ap.add_argument("--freq", default="D", help="window size: D (day) or W (week)")
    ap.add_argument("--baseline-end", default=None, help="default: 72h after the first run in the logs")
    ap.add_argument("--csv", help="also write the flat per-sample table here")
    args = ap.parse_args()

    df = load_samples(args.log_dir)
    if df.empty:
        print(f"no samples in {args.log_dir}")
        return
    if args.csv:
        df.to_csv(args.csv, index=False)
    end = pd.Timestamp(args.baseline_end).to_pydatetime() if args.baseline_end else None
    summary = summarize(df, end, args.freq)
    print(markdown_table(summary))
    per_family = df[df["error"].isna()].groupby("family").agg(
        samples=("score", "size"), score=("score", "mean"), exact=("exact", "mean"),
        answered=("answered", "mean"), output_tokens_median=("output_tokens", "median"),
    )
    print("\nper family (all windows):")
    print(per_family.round(3).to_string())


if __name__ == "__main__":
    main()
