import json
import os
import stat
import sys

import pytest
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig

from livenerf.providers.claudecode import ClaudeCodeAPI, ClaudeCodeError

FAKE = r'''#!{python}
import json, os, sys
if sys.argv[1:] == ["--version"]:
    print("9.9.9 (Claude Code)"); sys.exit(0)
prompt = sys.stdin.read()
argv = sys.argv[1:]
record = {{"argv": argv, "cwd": os.getcwd(), "env_claudecode": os.environ.get("CLAUDECODE"),
          "env_effort": os.environ.get("CLAUDE_EFFORT"), "env_key": os.environ.get("ANTHROPIC_API_KEY"),
          "cwd_files": os.listdir(".")}}
open(os.environ["FAKE_RECORD"], "w").write(json.dumps(record))
if "FALLBACK" in prompt:
    print(json.dumps({{"type": "result", "is_error": False, "result": "x", "num_turns": 2, "stop_reason": "end_turn",
        "usage": {{}}, "modelUsage": {{"claude-opus-5-5": {{}}, "claude-opus-4-8": {{}}}}}})); sys.exit(0)
if "RETRY" in prompt:
    print(json.dumps({{"type": "result", "is_error": False, "result": "x", "num_turns": 2, "usage": {{}},
        "modelUsage": {{"claude-opus-5-5": {{}}}}}})); sys.exit(0)
if "FAIL" in prompt:
    print(json.dumps({{"type": "result", "is_error": True, "result": "usage limit reached"}})); sys.exit(1)
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "<answer>" + prompt[::-1] + "</answer>",
    "usage": {{"input_tokens": 11, "output_tokens": 222, "cache_read_input_tokens": 3, "output_tokens_details": {{"thinking_tokens": 200}}}},
    "modelUsage": {{"claude-opus-5-5": {{"outputTokens": 222}}}}, "duration_ms": 1234, "num_turns": 1, "session_id": "s1"}}))
'''


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    path = tmp_path / "claude"
    path.write_text(FAKE.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    record = tmp_path / "record.json"
    monkeypatch.setenv("FAKE_RECORD", str(record))
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_EFFORT", "low")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    return str(path), record


def _messages(text):
    return [ChatMessageSystem(content="SYS"), ChatMessageUser(content=text)]


async def test_hermetic_call_and_parsing(fake_cli):
    cli, record = fake_cli
    api = ClaudeCodeAPI("claude-opus-5-5", cli=cli)
    out, call = await api.generate(_messages("abc"), [], "none", GenerateConfig(effort="high"))
    assert out.completion == "<answer>cba</answer>"
    assert out.usage.output_tokens == 222 and out.usage.input_tokens == 11
    assert out.usage.reasoning_tokens == 200
    assert out.model == "claude-opus-5-5"
    assert out.metadata["cli_version"] == "9.9.9 (Claude Code)"
    rec = json.loads(record.read_text())
    argv = rec["argv"]
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert argv[argv.index("--effort") + 1] == "high"
    assert argv[argv.index("--system-prompt") + 1] == "SYS"
    assert argv[argv.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert rec["env_claudecode"] is None and rec["env_effort"] is None and rec["env_key"] is None
    assert rec["cwd_files"] == [] and "livenerf-" in rec["cwd"]
    assert call.response["session_id"] == "s1"


async def test_effort_must_be_explicit(fake_cli):
    api = ClaudeCodeAPI("claude-opus-5-5", cli=fake_cli[0])
    with pytest.raises(ClaudeCodeError, match="effort must be explicit"):
        await api.generate(_messages("abc"), [], "none", GenerateConfig())
    api_b = ClaudeCodeAPI("claude-opus-5-5", cli=fake_cli[0], allow_default_effort="true")
    out, _ = await api_b.generate(_messages("abc"), [], "none", GenerateConfig())
    assert "--effort" not in json.loads(fake_cli[1].read_text())["argv"]


async def test_cli_errors_become_sample_errors(fake_cli):
    api = ClaudeCodeAPI("claude-opus-5-5", cli=fake_cli[0])
    out, call = await api.generate(_messages("FAIL"), [], "none", GenerateConfig(effort="high"))
    assert isinstance(out, ClaudeCodeError) and "usage limit" in str(out)
    assert api.should_retry(out) is False


def test_cli_version_pin(fake_cli):
    ClaudeCodeAPI("claude-opus-5-5", cli=fake_cli[0], expect_cli_version="9.9.9")
    with pytest.raises(ClaudeCodeError, match="pinned"):
        ClaudeCodeAPI("claude-opus-5-5", cli=fake_cli[0], expect_cli_version="2.1.280")


@pytest.mark.parametrize("prompt,tag", [("FALLBACK", "[fallback]"), ("RETRY", "[retried]")])
async def test_classifier_retries_and_fallbacks_are_never_scored(fake_cli, prompt, tag):
    api = ClaudeCodeAPI("claude-opus-5-5", cli=fake_cli[0])
    out, call = await api.generate(_messages(prompt), [], "none", GenerateConfig(effort="high"))
    assert isinstance(out, ClaudeCodeError) and tag in str(out)
    assert call.response["num_turns"] == 2  # the raw result is still logged for the refusal-rate metric
