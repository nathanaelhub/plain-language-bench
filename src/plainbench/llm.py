"""Call Claude through the `claude` CLI in print mode, stripped down to a plain model call.

No tools, no MCP servers, no settings or slash commands: about 600 tokens of
overhead instead of tens of thousands (the judge-audit measurement). The
prompt goes on stdin, so a long letter never hits the argument-length limit.

PLAINBENCH_USE_LOGIN=1 drops ANTHROPIC_API_KEY from the environment so the
CLI uses its claude.ai login rather than a stray key.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass

MODELS = {"haiku", "sonnet", "opus"}


@dataclass
class Reply:
    text: str
    model: str | None
    cost_usd: float
    error: str | None = None


def argv(model: str, system: str, effort: str | None = None) -> list[str]:
    a = ["claude", "-p", "--model", model, "--output-format", "json", "--system-prompt", system,
         "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "",
         "--disable-slash-commands", "--no-session-persistence"]
    return a + (["--effort", effort] if effort else [])


def env() -> dict[str, str]:
    e = dict(os.environ)
    if os.environ.get("PLAINBENCH_USE_LOGIN"):
        e.pop("ANTHROPIC_API_KEY", None)
    return e


def parse(stdout: bytes, stderr: bytes, returncode: int | None) -> Reply:
    try:
        d = json.loads(stdout)
    except ValueError:
        return Reply("", None, 0.0, f"exit {returncode}: {(stderr or stdout).decode(errors='replace')[:300]}")
    cost = float(d.get("total_cost_usd") or 0)
    model = next(iter(d.get("modelUsage") or {}), None)
    if d.get("is_error"):
        return Reply("", model, cost, str(d.get("result"))[:300])
    return Reply(d.get("result") or "", model, cost)


async def call(prompt: str, system: str, model: str = "sonnet", effort: str | None = None,
               timeout: float = 300.0) -> Reply:
    proc = await asyncio.create_subprocess_exec(
        *argv(model, system, effort), env=env(), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return Reply("", None, 0.0, f"timed out after {timeout:.0f}s")
    return parse(out, err, proc.returncode)


def json_block(text: str) -> dict | list | None:
    """The first JSON object or array in a reply, tolerating a ```json fence or a sentence around it."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m.group(1) if m else text
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = body.find(opener), body.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(body[i:j + 1])
            except ValueError:
                continue
    return None


def tagged(text: str, tag: str) -> str | None:
    """Text between <tag> and </tag>, stripped; None if the tags aren't there."""
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.S)
    return m.group(1) if m else None
