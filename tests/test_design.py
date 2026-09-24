import json


def test_tokens_per_point_counts_lagged_meter_movement(tmp_path, monkeypatch):
    from livenerf import design

    rows = [
        {"time": "2026-09-23T10:00:00+00:00", "output_tokens": 100_000, "before": {"weekly": 10}, "after": {"weekly": 11}},
        # the meter rose 1 point between two back-to-back chunks: calibration's own cost, counted
        {"time": "2026-09-23T10:01:00+00:00", "output_tokens": 100_000, "before": {"weekly": 12}, "after": {"weekly": 12}},
        # a 5-hour gap: movement in it may be other use of the plan, not counted
        {"time": "2026-09-23T15:00:00+00:00", "output_tokens": 100_000, "before": {"weekly": 20}, "after": {"weekly": 21}},
    ]
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "usage.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(design, "REPO_ROOT", tmp_path)
    tpp, info = design.tokens_per_point()
    assert info["weekly_points"] == 3 and info["lagged_points"] == 1 and tpp == 100_000


def test_claude_cli_prefers_env_then_pinned_copy(tmp_path, monkeypatch):
    from livenerf import common

    monkeypatch.setenv("LIVENERF_CLAUDE_CLI", "/x/claude")
    assert common.claude_cli() == "/x/claude"
    monkeypatch.delenv("LIVENERF_CLAUDE_CLI")
    monkeypatch.setattr(common.Path, "home", lambda: tmp_path)
    pin = (common.REPO_ROOT / "CLAUDE_CLI_VERSION").read_text().strip()
    assert common.claude_cli() == "claude"
    copy = tmp_path / ".local" / "share" / "livenerf" / f"claude-{pin}"
    copy.parent.mkdir(parents=True)
    copy.write_text("")
    assert common.claude_cli() == str(copy)


def test_screen_eligibility_is_uniform_and_excludes_classifier_items():
    from livenerf.benchmarks.calibrate import confirm_wanted, eligible, screen_wanted

    h = lambda scores, errors=0, events=0: {"scores": scores, "errors": errors, "events": events, "tokens": []}  # noqa: E731
    assert screen_wanted(h([1.0]))  # a first-try pass is still screened to 4, whatever the benchmark
    assert not screen_wanted(h([1.0] * 4)) and not screen_wanted(h([1.0], errors=2))
    assert eligible(h([1.0, 0.0, 1.0, 1.0])) and not eligible(h([1.0] * 4)) and not eligible(h([0.0] * 4))
    assert not eligible(h([1.0, 0.0, 1.0]))  # screen incomplete
    assert not eligible(h([1.0, 0.0, 1.0, 1.0], errors=1, events=1))  # classifier-touched
    assert confirm_wanted(h([1.0, 0.0, 1.0, 1.0]), h([1.0] * 7))
    assert not confirm_wanted(h([1.0, 0.0, 1.0, 1.0]), h([1.0] * 8))
    assert not confirm_wanted(h([1.0] * 4), h([]))


def test_panel_lock_detects_any_change(tmp_path, monkeypatch):
    from livenerf import design

    (tmp_path / "data").mkdir()
    panel = tmp_path / "data" / "standard_panel.json"
    panel.write_text('{"families": {}}')
    monkeypatch.setattr(design, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(design, "LOCK_FILE", tmp_path / "data" / "panel.lock")
    assert not design.lock_ok()[0]
    design.lock_panel()
    assert design.lock_ok()[0]
    panel.write_text('{"families": {"gpqa": {}}}')
    assert not design.lock_ok()[0]


def test_daily_runs_once_per_utc_day(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from livenerf import daily

    monkeypatch.setattr(daily, "LOG", tmp_path / "daily.jsonl")
    assert not daily.ran_today()
    daily.record({"status": "skipped", "reason": "usage above cap"})
    assert not daily.ran_today()  # a skipped attempt retries at the next hour
    daily.record({"status": "ran", "day": datetime.now(timezone.utc).date().isoformat()})
    assert daily.ran_today()
