"""Inspect entry point (see [project.entry-points.inspect_ai] in pyproject.toml)."""

from inspect_ai.model import modelapi


@modelapi(name="claudecode")
def claudecode():
    from .providers.claudecode import ClaudeCodeAPI

    return ClaudeCodeAPI
