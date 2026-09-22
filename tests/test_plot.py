from datetime import timedelta

from livenerf.plot import DAY0, render


def test_empty_frame_renders_without_points():
    svg = render([], DAY0, 0, "light")
    assert svg.startswith("<svg") and "No frozen-panel data yet" in svg and "<circle" not in svg


def test_points_render_in_both_themes():
    pts = [(DAY0 + timedelta(days=4 + i), 0.5 * i, 1.0) for i in range(5)]
    for theme in ("light", "dark"):
        svg = render(pts, DAY0, 500, theme)
        assert svg.count("<circle") == 1 and "+2.0" in svg
