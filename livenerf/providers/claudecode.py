"""Inspect model provider that serves a model through headless Claude Code (`claude -p`).

    inspect eval livenerf/tasks --model claudecode/claude-opus-5-5 --effort high

Each generate() call runs one hermetic, single-turn `claude -p` process:
- the task's system prompt replaces Claude Code's (--system-prompt)
- no tools, no MCP servers, no skills or slash commands, no session persistence
- an empty working directory with a fixed path (the path is shown to the model, so it must not
  vary between calls), and no settings files: --setting-sources project finds none there
- the global ~/.claude/CLAUDE.md, auto-memory and the advisor tool are switched off (HERMETIC_ENV)
- env vars that would override model/effort/auth are removed
The full JSON result is kept in the log as the ModelCall response.

Model args (-M key=value):
    cli=<pinned copy>         path to the claude binary (default: livenerf.common.claude_cli())
    timeout=900               seconds per call
    expect_cli_version=       fail if `claude --version` differs (pins the harness)
    allow_default_effort=false  arm B only: permit running without --effort
    setting_sources=project   passed to --setting-sources ("" is not accepted by the CLI). "user"
                              would load ~/.claude/settings.json, including its hooks
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    GenerateConfig,
    ModelAPI,
    ModelCall,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.tool import ToolChoice, ToolInfo

from ..common import claude_cli

# Removed from the child environment: they would silently change model, effort, or billing,
# or make the child think it is nested inside another Claude Code session.
SCRUB_ENV = {
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_EFFORT",
    "CLAUDE_CODE_EFFORT_LEVEL",
    "MAX_THINKING_TOKENS",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "ANTHROPIC_API_KEY",  # the Max-plan series must never silently switch to API billing
}
# Any other inherited CLAUDE_CODE_* var is also dropped (session ids, messaging sockets and
# feature flags from a parent session), except the ones that only carry a login.
KEEP_CLAUDE_CODE_ENV = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR"}

# Set in the child. Without these, `claude -p` still injects the user's global ~/.claude/CLAUDE.md
# (--setting-sources does not cover it) and attaches a server-side advisor tool, even with
# --tools "". Measured on the series machine (CLI 2.1.280): 11.2k context tokens per call with
# them unset, 0.55k with them set, which matches the remote pilots.
HERMETIC_ENV = {
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_ADVISOR_TOOL": "1",
}


# Context-size guard. A hermetic call's context is the system prompt + the item + a fixed harness
# overhead (an environment block, measured at ~0.5k tokens on CLI 2.1.280). Anything much larger
# means something was injected (a CLAUDE.md, memory, tool definitions), and the sample would not
# measure what it claims to, so it is rejected as a [context] error. The item itself is bounded by
# one token per character: prose is ~4 characters a token, but sequence data (GPQA has DNA and
# protein sequences) tokenizes at close to 1, so anything tighter rejects real items.
CONTEXT_OVERHEAD_LIMIT = 2500


def context_limit(system: str, prompt: str) -> int:
    return len(system) + len(prompt) + CONTEXT_OVERHEAD_LIMIT


class ClaudeCodeError(RuntimeError):
    pass


def _empty_cwd() -> str:
    """The working directory for every call. Claude Code shows it to the model in an environment
    block, so a random temp name per call would put noise in the input; this path never changes."""
    path = os.path.join(tempfile.gettempdir(), "livenerf-cwd")
    os.makedirs(path, exist_ok=True)
    if os.listdir(path):
        raise ClaudeCodeError(f"{path} is not empty; something wrote into the hermetic working directory")
    return path


def _text(message: ChatMessage) -> str:
    return message.text if isinstance(message.content, list) else str(message.content)


class ClaudeCodeAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_vars: list[str] = [],
        config: GenerateConfig = GenerateConfig(),
        cli: str | None = None,
        timeout: int = 900,
        expect_cli_version: str | None = None,
        allow_default_effort: bool | str = False,
        setting_sources: str = "project",
        keep_api_key: bool | str = False,
        **model_args: Any,
    ) -> None:
        super().__init__(model_name, base_url, api_key, api_key_vars, config)
        cli = cli or claude_cli()
        self.cli = shutil.which(cli) or cli
        self.timeout = int(timeout)
        self.allow_default_effort = str(allow_default_effort).lower() == "true"
        self.setting_sources = setting_sources
        self.keep_api_key = str(keep_api_key).lower() == "true"
        self.cli_version = subprocess.run(
            [self.cli, "--version"], capture_output=True, text=True, timeout=60
        ).stdout.strip()
        if expect_cli_version and expect_cli_version not in self.cli_version:
            raise ClaudeCodeError(
                f"claude CLI is {self.cli_version!r}, expected {expect_cli_version!r}. "
                "The harness is pinned: upgrade deliberately and log it, never silently."
            )

    def max_connections(self) -> int:
        return 2  # subscription limits, not throughput, are the constraint

    def should_retry(self, ex: BaseException) -> bool:
        return False  # never hammer a usage cap; errored samples are logged and reported separately

    def _env(self) -> dict[str, str]:
        def keep(k: str) -> bool:
            if k == "ANTHROPIC_API_KEY":
                return self.keep_api_key
            if k.startswith("CLAUDE_CODE_"):
                return k in KEEP_CLAUDE_CODE_ENV
            return k not in SCRUB_ENV

        env = {k: v for k, v in os.environ.items() if keep(k)}
        env.update(HERMETIC_ENV)
        return env

    def _command(self, system: str, config: GenerateConfig) -> list[str]:
        effort = config.effort
        if effort is None and not self.allow_default_effort:
            raise ClaudeCodeError("effort must be explicit (pass --effort). See PLAN.md §1.2.")
        cmd = [
            self.cli, "-p",
            "--model", self.model_name,
            "--output-format", "json",
            "--system-prompt", system,
            "--tools", "",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--disable-slash-commands",
            "--no-session-persistence",
            "--setting-sources", self.setting_sources,
        ]
        if effort is not None:
            cmd += ["--effort", effort]
        return cmd

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> tuple[ModelOutput | Exception, ModelCall]:
        if tools:
            raise ClaudeCodeError("livenerf's claudecode provider is tool-free by design")
        if any(isinstance(m, ChatMessageAssistant) for m in input):
            raise ClaudeCodeError("livenerf's claudecode provider is single-turn by design")
        system = "\n\n".join(_text(m) for m in input if isinstance(m, ChatMessageSystem))
        prompt = "\n\n".join(_text(m) for m in input if not isinstance(m, ChatMessageSystem))
        cmd = self._command(system, config)
        request = {"argv": cmd[:6] + ["--system-prompt", "<system>"] + cmd[8:], "system": system, "prompt": prompt, "cli_version": self.cli_version}

        start = time.monotonic()
        cwd = _empty_cwd()
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd, env=self._env(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(prompt.encode()), self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            call = ModelCall.create(request=request, response={"error": "timeout"}, time=time.monotonic() - start)
            return ClaudeCodeError(f"claude -p timed out after {self.timeout}s"), call
        elapsed = time.monotonic() - start

        raw = stdout.decode(errors="replace")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {"unparsed_stdout": raw[-4000:], "stderr": stderr.decode(errors="replace")[-4000:], "returncode": proc.returncode}
        call = ModelCall.create(request=request, response=result, time=elapsed)

        if proc.returncode != 0 or result.get("is_error") or "result" not in result:
            detail = result.get("result") or result.get("stderr") or result.get("unparsed_stdout") or ""
            tag = "[refusal] " if result.get("stop_reason") == "refusal" else ""
            return ClaudeCodeError(f"{tag}claude -p failed (exit {proc.returncode}): {str(detail)[:500]}"), call

        usage = result.get("usage") or {}
        model_usage = result.get("modelUsage") or {}
        served = list(model_usage) or [self.model_name]
        # Integrity guards. A safety-classifier stop makes Claude Code retry the turn, sometimes
        # on a fallback model (seen in pilot 2: Opus 4.8 answered for Opus 5.5). Such a sample
        # does not measure the requested model, so it is an error with its own category, never
        # a score. The rate of these events is reported as a secondary metric.
        if set(served) != {self.model_name}:
            return ClaudeCodeError(f"[fallback] served by {served}, requested {self.model_name}"), call
        if result.get("num_turns") not in (None, 1):
            return ClaudeCodeError(f"[retried] num_turns={result.get('num_turns')} (classifier stop and retry)"), call
        if result.get("stop_reason") == "refusal":
            return ClaudeCodeError("[refusal] stop_reason=refusal"), call
        context = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        if context > context_limit(system, prompt):
            return ClaudeCodeError(f"[context] {context} context tokens, limit {context_limit(system, prompt)}: "
                                   "something beyond the prompt was loaded"), call
        output = ModelOutput.from_content(model=served[0], content=result["result"])
        output.usage = ModelUsage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            input_tokens_cache_write=usage.get("cache_creation_input_tokens"),
            input_tokens_cache_read=usage.get("cache_read_input_tokens"),
            reasoning_tokens=(usage.get("output_tokens_details") or {}).get("thinking_tokens"),
        )
        output.time = elapsed
        output.metadata = {
            "cli_version": self.cli_version,
            "served_models": served,
            "duration_ms": result.get("duration_ms"),
            "duration_api_ms": result.get("duration_api_ms"),
            "num_turns": result.get("num_turns"),
            "session_id": result.get("session_id"),
            "stop_reason": result.get("stop_reason"),
            "terminal_reason": result.get("terminal_reason"),
            "ttft_ms": result.get("ttft_ms"),
            "service_tier": usage.get("service_tier"),
            "inference_geo": usage.get("inference_geo"),
            "speed": usage.get("speed"),
            # how the call was billed ("list" = API pricing); the Max-plan series should never change this
            "cost_basis": {m: (u or {}).get("costBasis") for m, u in model_usage.items()},
            "canonical_model": {m: (u or {}).get("canonicalModel") for m, u in model_usage.items()},
        }
        return output, call
