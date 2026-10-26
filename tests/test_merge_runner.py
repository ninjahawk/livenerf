import json

from livenerf import merge_runner


def _setup(tmp_path, monkeypatch, host_lines=(), host_eval_days=()):
    src, logs = tmp_path / "vm", tmp_path / "logs"
    src.mkdir()
    logs.mkdir()
    (logs / "daily.jsonl").write_text("".join(json.dumps(e) + "\n" for e in host_lines))
    for day in ("2026-10-27", "2026-10-28"):
        (src / f"{day}.eval").write_text("x")
    (src / "daily.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [
        {"status": "refused", "day": "2026-10-26", "runner": "conductor-vm"},
        {"status": "ran", "day": "2026-10-27", "runner": "conductor-vm", "logs": ["2026-10-27.eval"]},
        {"status": "ran", "day": "2026-10-28", "runner": "conductor-vm", "logs": ["2026-10-28.eval"]},
    ]))
    monkeypatch.setattr(merge_runner, "check", lambda e, s, lock, l: None)  # real logs are checked in check()
    monkeypatch.setattr(merge_runner, "eval_days", lambda d: set(host_eval_days))
    return src, logs


def test_merge_adds_only_days_this_repo_does_not_have(tmp_path, monkeypatch):
    host = [{"status": "ran", "day": "2026-10-27", "runner": "host"}]
    src, logs = _setup(tmp_path, monkeypatch, host_lines=host)
    out = merge_runner.merge(src, logs=logs)
    assert [o[2].split(":")[0] for o in out] == ["refused", "merged"]  # 10-27: host was first
    assert not (logs / "2026-10-27.eval").exists() and (logs / "2026-10-28.eval").exists()
    ran = [json.loads(x) for x in (logs / "daily.jsonl").read_text().splitlines()]
    assert [(e["day"], e["runner"]) for e in ran] == [("2026-10-27", "host"), ("2026-10-28", "conductor-vm")]
    assert merge_runner.merge(src, logs=logs)[1][2].startswith("refused")  # merging twice adds nothing


def test_merge_refuses_a_day_with_host_logs_but_no_ran_line(tmp_path, monkeypatch):
    # e.g. a host run that failed part-way, or is still running: the day is not free
    src, logs = _setup(tmp_path, monkeypatch, host_eval_days={"2026-10-28"})
    out = merge_runner.merge(src, dry_run=True, logs=logs)
    assert [o[2] for o in out][1].startswith("refused") and out[0][2] == "would merge"
    assert list(logs.iterdir()) == [logs / "daily.jsonl"]  # dry run copies nothing
