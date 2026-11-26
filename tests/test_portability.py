"""Non-Windows checkouts: the panel lock across line endings, the macOS Keychain login, an empty report."""

import json
import subprocess

import pandas as pd


def test_panel_lock_survives_line_endings(tmp_path, monkeypatch):
    from livenerf import design

    (tmp_path / "data").mkdir()
    panel = tmp_path / "data" / "standard_panel.json"
    monkeypatch.setattr(design, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(design, "LOCK_FILE", tmp_path / "data" / "panel.lock")
    panel.write_bytes(b'{\r\n  "families": {}\r\n}\r\n')  # a Windows checkout locks the CRLF bytes
    design.lock_panel()
    panel.write_bytes(b'{\n  "families": {}\n}\n')  # the same panel on a macOS/Linux checkout
    assert design.lock_ok()[0]
    panel.write_bytes(b'{\n  "families": {"gpqa": {}}\n}\n')
    assert not design.lock_ok()[0]


def test_meter_token_falls_back_to_macos_keychain(tmp_path, monkeypatch):
    from livenerf import usage

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))  # no .credentials.json here
    monkeypatch.setattr(usage.sys, "platform", "darwin")
    secret = json.dumps({"claudeAiOauth": {"accessToken": "tok-from-keychain"}})

    def fake_run(cmd, **kw):
        # Claude Code files its login under the OS user; other items can share the service name
        assert cmd[:2] == ["security", "find-generic-password"] and cmd[cmd.index("-a") + 1] == "someone"
        return subprocess.CompletedProcess(cmd, 0, stdout=secret + "\n", stderr="")

    monkeypatch.setattr(usage.subprocess, "run", fake_run)
    monkeypatch.setattr(usage.getpass, "getuser", lambda: "someone")
    assert usage._token() == "tok-from-keychain"


def test_meter_token_file_wins_and_keychain_failure_is_none(tmp_path, monkeypatch):
    from livenerf import usage

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(usage.sys, "platform", "darwin")
    monkeypatch.setattr(usage.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 44, stdout="", stderr="not found"))
    assert usage._token() is None
    (tmp_path / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-file"}}))
    assert usage._token() == "tok-file"


def test_validate_report_with_no_samples_is_incomplete(tmp_path, monkeypatch):
    from livenerf import validate

    monkeypatch.setattr(validate, "samples", lambda: pd.DataFrame([]))
    monkeypatch.setattr(validate, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    assert "INCOMPLETE" in validate.report()


def test_meter_reads_weekly_when_five_hour_is_null(tmp_path, monkeypatch):
    import io

    from livenerf import usage

    body = {"five_hour": None, "seven_day": {"utilization": 11.0, "resets_at": "2026-11-11T14:59:59Z"}}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(usage, "_token", lambda: "tok")
    monkeypatch.setattr(usage.urllib.request, "urlopen", lambda req, timeout: Resp(json.dumps(body).encode()))
    got = usage._read()
    assert got["weekly"] == 11.0 and got["five_hour"] == 0.0  # no 5-hour limit on the plan: nothing to cap
    body["seven_day"] = None
    assert usage._read() is None


def test_empty_validate_report_leaves_the_published_doc_alone(tmp_path, monkeypatch):
    import sys

    from livenerf import validate

    monkeypatch.setattr(validate, "samples", lambda: pd.DataFrame([]))
    monkeypatch.setattr(validate, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "docs").mkdir()
    doc = tmp_path / "docs" / "VALIDATION.md"
    doc.write_text("**Result: PASS.**")
    monkeypatch.setattr(sys, "argv", ["validate", "report"])
    validate.main()
    assert doc.read_text() == "**Result: PASS.**"
