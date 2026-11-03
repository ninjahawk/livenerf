"""Generate the r/ClaudeAI wiki page (Reddit markdown) for livenerf from the repo's published data.

  python scripts/reddit_wiki.py <livenerf repo dir> [--out wiki.md] [--html preview.html]

Single source of truth = what is on GitHub: results/daily.csv (every day) and the README Results table (the
pre-registered window verdicts, computed by `python -m livenerf.analysis`). Nothing is computed differently here.
Designed to run in a GitHub Action after each data push, then posted with Reddit's wiki edit API; --html renders
the markdown with Reddit's own renderer (snudown, wiki mode) inside a new-Reddit-style page for local testing.
"""
import argparse, csv, pathlib, re, statistics as S, subprocess, sys

BARS = "▁▂▃▄▅▆▇█"
RAW = "https://raw.githubusercontent.com/ninjahawk/livenerf/main"
GH = "https://github.com/ninjahawk/livenerf"


def daily(repo):
    days = {}
    for r in csv.DictReader(open(repo / "results/daily.csv", encoding="utf-8")):
        if r["arm"] != "measured":
            continue
        d = days.setdefault(int(r["series_day"]), {"date": r["date_utc"], "w": 0.0, "n": 0, "tok": []})
        n = int(r["scored"] or 0)
        if r["family"] == "all":
            d["all"] = (float(r["score"] or 0), n, float(r["output_tokens_median"] or 0))
        else:
            d["w"] += float(r["score"] or 0) * n; d["n"] += n
    out = []
    for k in sorted(days):
        d = days[k]
        s, n, tok = d.get("all", (d["w"] / d["n"] if d["n"] else 0, d["n"], 0))
        out.append({"day": k, "date": d["date"], "score": s, "n": n, "tok": tok})
    return out


def windows(repo):
    """The published Results table in README.md (pre-registered verdicts)."""
    rows, txt = [], (repo / "README.md").read_text(encoding="utf-8")
    for line in txt.splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|\s*days ([\d–-]+)[^|]*\|\s*(\d+)\s*\|\s*([\d.]+) ± ([\d.]+)\s*\|\s*([^|]+)\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|", line)
        if m:
            rows.append({"i": int(m[1]), "days": m[2].replace("–", "-"), "score": float(m[4]), "se": float(m[5]),
                         "delta": m[6].strip(), "tok": int(m[7]), "control": m[8].strip(), "decision": m[10].strip()})
    return rows


def _unused_spark(vals, lo=None, hi=None):
    lo = min(vals) if lo is None else lo; hi = max(vals) if hi is None else hi
    return "".join(BARS[min(7, max(0, int((v - lo) / (hi - lo + 1e-9) * 8)))] for v in vals)


def pts(delta):
    m = re.match(r"([+\-−]?[\d.]+) ± ([\d.]+)", delta.replace("−", "-"))
    return f"{float(m[1]) * 100:+.1f} ± {float(m[2]) * 100:.1f}" if m else delta


def build(repo):
    D, W = daily(repo), windows(repo)
    last = D[-1]
    base = [d["score"] for d in D if d["day"] <= 10]
    done = [w for w in W if w["decision"] != "baseline"]
    lastw = done[-1] if done else None
    verdict_all = all(w["decision"] == "no change" for w in done)
    head = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%h %cs"], capture_output=True, text=True).stdout.split()
    day_total = 45
    cur_w = (last["day"] - 1) // 10  # 0 = baseline
    in_w = [d for d in D if (d["day"] - 1) // 10 == cur_w]
    L = []
    a = L.append
    a("# LiveNerf: is Claude getting worse?\n")
    if lastw:
        a(f"> **Latest ({last['date']}, day {last['day']}):** "
          + ("**no measurable change.** " if verdict_all else "**see the latest window below.** ")
          + f"Claude Opus 5.5 has been tested every day since launch week on the same frozen questions. "
          + f"{len(done)} full 10-day window{'s' if len(done) != 1 else ''} after launch week, "
          + ("all within noise of launch week. " if verdict_all else "")
          + f"Latest window (days {lastw['days']}): **{pts(lastw['delta'])} points** vs launch week.\n>\n"
          + f"> This page updates automatically from [the LiveNerf repo]({GH}) every time new data is published.\n")
    a(f"![LiveNerf daily chart]({RAW}/media/livenerf-dark.svg)\n")
    a(f"^(Daily score with 95% error bars; dashed line = launch-week average.) [Full-size chart]({RAW}/media/livenerf-dark.svg)\n")
    a("**Contents:** [Checkpoints](#wiki_checkpoints) · [Latest days](#wiki_latest_days) · "
      "[How it works](#wiki_how_it_works) · [How to read it](#wiki_how_to_read_it) · "
      "[What it can and can't tell you](#wiki_what_it_can_and_can.27t_tell_you) · "
      "[Reporting a suspected nerf](#wiki_reporting_a_suspected_nerf) · [FAQ](#wiki_faq)\n")
    a("---\n")
    a("## Checkpoints\n")
    a("Every 10 days the new window is compared with launch week, on the same questions. A change is only declared "
      "when it is significant at 99% **and** at least 3 points **in two windows in a row**, on an unchanged harness.\n")
    a("| Checkpoint | Days | Score | Change vs launch (pts) | Answer length | Verdict |")
    a("|:--|:--|--:|--:|--:|:--|")
    for w in W:
        name = "Launch week" if w["decision"] == "baseline" else f"Window {w['i']}"
        a(f"| {name} | {w['days']} | {w['score'] * 100:.1f}% | {'baseline' if w['decision'] == 'baseline' else pts(w['delta'])} "
          f"| {w['tok']} | {'**' + w['decision'] + '**' if w['decision'] != 'baseline' else 'baseline'} |")
    nxt_end = (cur_w + 1) * 10
    if cur_w > len(W) - 1:
        a(f"| Window {cur_w} | {cur_w * 10 + 1}-{nxt_end} | | | | {len(in_w)}/10 days in |")
    a("")
    a("## Latest days\n")
    a("Daily score on the frozen panel (78 questions). Single days swing by several points; that is sampling noise, "
      "the checkpoints above are what count.\n")
    sc = [d["score"] for d in D]
    a(f"Launch-week average {S.mean(base) * 100:.1f}%; range so far {min(sc) * 100:.0f}-{max(sc) * 100:.0f}%.\n")
    a("| Day | Date | Score | Answer length (median tokens) |")
    a("|:--|:--|--:|--:|")
    for d in D[-5:][::-1]:
        a(f"| {d['day']} | {d['date']} | {d['score'] * 100:.1f}% | {d['tok']:.0f} |")
    a("")
    a(f"Per-question-family chart: "
      f"[families]({RAW}/media/livenerf-families-dark.svg) · raw data: [daily.csv]({GH}/blob/main/results/daily.csv)\n")
    a("## How it works\n")
    a(f"- **Started at launch.** Day 1 was {D[0]['date']}, two days after Claude Opus 5.5 was released. The series ran "
      f"{day_total} pre-registered days and keeps going daily after that.")
    a("- **Same questions every day:** 78 hard questions (graduate science, professional knowledge, competition math) "
      "for the main model, plus 12 for an older control model, chosen and validated before the series began.")
    a("- **Everything but the model is frozen:** the prompts, the Claude Code version (2.1.280, pinned), the graders "
      "and the harness code (its hash is checked before every run). If the score moves, the model moved.")
    a("- **Run through Claude Code on a Max plan**, the way most people here use it, not through a special API.")
    a("- **Every raw log is public**, and the analysis plan was [pre-registered](" + GH + "/blob/main/PREREGISTRATION.md) "
      "before the data came in, so the rules can't be bent after the fact.")
    a("- Built on the UK AI Security Institute's open-source eval framework (Inspect); the statistics follow "
      "Anthropic's own *Adding Error Bars to Evals* paper.\n")
    a("## How to read it\n")
    a("- **Score:** share of questions answered correctly. The questions are hard on purpose, so ~60% is normal.")
    a("- **Change vs launch week:** the difference on the *same* questions, with its standard error (±).")
    a("- **Answer length:** the early-warning signal. A model that starts \"thinking less\" usually gives shorter answers "
      "before its accuracy visibly drops.")
    a("- **Sensitivity:** a 10-day window can detect a drop of roughly 6-7 points. Smaller real changes could go unnoticed.\n")
    a("## What it can and can't tell you\n")
    a("**It can tell you** whether Claude Opus 5.5, used through Claude Code, still answers a fixed set of hard questions "
      "as well as it did at launch.\n")
    a("**It can't tell you** about other models (Sonnet, Haiku), the claude.ai app (its own system prompt and features), "
      "usage limits, speed, outages, long agentic coding sessions or tool use, or changes smaller than the panel can see.\n")
    a("If Claude *feels* worse, common non-model causes are a new Claude Code version, different project or system "
      "instructions, a very long conversation, a lower effort/thinking setting, or a harder task than usual.\n")
    a("## Reporting a suspected nerf\n")
    a("Useful reports get investigated; vague ones don't. In incident threads please include:\n")
    a("1. **When:** date and time with timezone, and whether it's ongoing.")
    a("2. **Where:** claude.ai, Claude Code (`claude --version`) or the API, and which model.")
    a("3. **What changed:** the same prompt or task before vs now, ideally with both outputs.")
    a("4. **Settings:** effort/thinking level, project or system instructions, conversation length.\n")
    a("Then compare with the latest day above: if the score and answer length are in their usual range, the core model "
      "is very likely unchanged.\n")
    a("## FAQ\n")
    a("**Who runs this?** An independent open-source project by u/TheOnlyVibemaster, not affiliated with Anthropic.\n")
    a("**Why only Opus 5.5?** The method needs a launch-day baseline; Opus 5.5 is the model it started with.\n")
    a(f"**Can I check it myself?** Yes: every log, grader and the analysis are in [the repo]({GH}), and you can run it "
      "yourself with Claude Code.\n")
    a("**Don't answers vary every time?** Yes, which is why it uses many questions, paired comparisons and error bars, "
      "not single answers.\n")
    a("---\n")
    a(f"^(Auto-updated from GitHub {('commit ' + head[0] + ', ' + head[1]) if head else ''} · day {last['day']} · "
      f"[Discord](https://discord.gg/JRGCUg2pyX) · [repo]({GH}))")
    return "\n".join(L) + "\n"


SHELL = pathlib.Path(__file__).with_name("livenerf_wiki_shell.html")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("repo"); ap.add_argument("--out"); ap.add_argument("--html")
    a = ap.parse_args()
    md = build(pathlib.Path(a.repo))
    if a.out:
        pathlib.Path(a.out).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    if a.html:
        import snudown
        body = snudown.markdown(md, renderer=snudown.RENDERER_WIKI)
        body = re.sub(r"<h([12])>(.*?)</h\1>", lambda m: f'<h{m[1]} id="wiki_{re.sub(r"[^a-z0-9]+", "_", re.sub("<[^>]+>", "", m[2]).lower()).strip("_")}">{m[2]}</h{m[1]}>', body)
        pathlib.Path(a.html).write_text(SHELL.read_text(encoding="utf-8").replace("{{BODY}}", body), encoding="utf-8")


if __name__ == "__main__":
    main()
