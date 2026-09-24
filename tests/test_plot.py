from datetime import timedelta

from livenerf.plot import DAY0, render


def test_empty_frame_renders_without_points():
    svg = render([], DAY0, 0, "light")
    assert svg.startswith("<svg") and "No data yet" in svg and "<circle" not in svg


def test_points_render_in_both_themes():
    pts = [(DAY0 + timedelta(days=4 + i), 0.5 * i, 1.0) for i in range(5)]
    for theme in ("light", "dark"):
        svg = render(pts, DAY0, 500, theme)
        assert svg.count("<circle") == 1 and "+2.0" in svg


def test_family_panels_render():
    from livenerf.plot import render_families

    series = {
        "gpqa": {"baseline": 0.6, "chance": 0.25, "base_tokens": 400.0,
                 "days": [(DAY0 + timedelta(days=4 + i), -1.0 * i, 2.0, -5.0 * i) for i in range(4)]},
        "compute": {"baseline": float("nan"), "chance": 0.0, "base_tokens": float("nan"), "days": []},
    }
    for theme in ("light", "dark"):
        svg = render_families(series, DAY0, theme)
        assert svg.startswith("<svg") and "GPQA Diamond" in svg and "47% above chance" in svg
        assert "tokens -15%" in svg and "baseline collecting" in svg
    assert "No data yet" in render_families({}, DAY0, "light")


def test_prebaseline_charts_render():
    from livenerf.plot_prebaseline import render_control, render_yield

    rows = [{"family": "mmlupro", "right": 90, "mixed": 5, "wrong": 5, "errored": 0, "items": 100},
            {"family": "gpqa", "right": 8, "mixed": 1, "wrong": 0, "errored": 1, "items": 10}]
    ctrl = [{"label": "All panel items", "items": 6, "acc_hi": 50.0, "acc_md": 48.0, "d": -2.0, "se": 3.0,
             "tok": -25.0, "tok_lo": -35.0, "tok_hi": -15.0},
            {"label": "GPQA Diamond", "items": 1, "acc_hi": 100.0, "acc_md": 100.0, "d": 0.0, "se": float("nan"),
             "tok": -40.0, "tok_lo": float("nan"), "tok_hi": float("nan")}]
    for theme in ("light", "dark"):
        y = render_yield(rows, theme)
        assert y.startswith("<svg") and "6 of 110 questions can show a change" in y and "stroke-dasharray" in y
        c = render_control(ctrl, theme)
        assert c.startswith("<svg") and "-2.0" in c and "-25%" in c and c.count("<circle") == 4


def test_plot_survives_a_log_dir_with_no_eval_logs(tmp_path):
    from livenerf.plot import _points

    (tmp_path / "daily.jsonl").write_text("")
    pts, _, n = _points(str(tmp_path))
    assert pts == [] and n == 0
