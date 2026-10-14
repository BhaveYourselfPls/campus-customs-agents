"""Portkey / model configuration and the shared MCP connection.

The PORTKEY_API_KEY is read from the root .env at runtime and never written to
a log, a payload, or the audit trail. Nothing here prints it.
"""

from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.mcp import MCPToolset, StdioTransport
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent          # HW 5/
PROMPTS_DIR = BACKEND_DIR / "prompts"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Walk up for the .env — the key lives in the course root, one level above HW 5.
for folder in [PROJECT_ROOT, *PROJECT_ROOT.parents]:
    if (folder / ".env").exists():
        load_dotenv(folder / ".env", override=False)
        break

MODEL_NAME = os.getenv("MODEL_NAME", "gpt-5.6-luna")
MCP_SERVER_NAME = "campus-customs-shop"
PORTKEY_BASE_URL = os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1").rstrip("/")

# Guard rails. These are spend and blast-radius limits, not style settings.
MAX_DELEGATIONS_PER_RUN = 12   # hard cap on specialist calls per question
MAX_TOOL_CALLS_PER_AGENT = 8   # hard cap on MCP calls inside one agent run


def require_api_key() -> str:
    key = os.getenv("PORTKEY_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "PORTKEY_API_KEY is missing. Put it in a .env in this project or a parent folder."
        )
    return key


@lru_cache(maxsize=4)
def build_model(model_name: str | None = None) -> OpenAIResponsesModel:
    """Model client for `model_name`, defaulting to MODEL_NAME. Cached per name.

    gpt-5.6-luna needs the Responses API for function tools; chat/completions
    rejects tools plus reasoning_effort on this model.
    """
    client = AsyncOpenAI(
        api_key=require_api_key(),
        base_url=PORTKEY_BASE_URL,
        default_headers={"x-portkey-provider": "openai"},
    )
    return OpenAIResponsesModel(
        model_name or MODEL_NAME, provider=OpenAIProvider(openai_client=client)
    )


def build_mcp_server() -> MCPToolset:
    """The one MCP toolset every agent shares.

    Read straight out of .mcp.json rather than hard-coded here, so the agents
    and the Claude Code session are provably pointed at the same server, the
    same transport, and the same database. Changing .mcp.json changes both.
    """
    config = json.loads((PROJECT_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    servers = config.get("mcpServers", {})
    if MCP_SERVER_NAME not in servers:
        raise RuntimeError(
            f"'{MCP_SERVER_NAME}' not found in .mcp.json. Present: {sorted(servers)}"
        )
    entry = servers[MCP_SERVER_NAME]

    # .mcp.json is checked into a public repo, so it stays portable: a bare
    # "python" and a repo-relative script path. Resolve both here against the
    # interpreter and checkout actually in use, so a clone works unmodified
    # and the venv's Python is preferred over whatever is first on PATH.
    command = entry["command"]
    if Path(command).stem.lower() in {"python", "python3"}:
        command = sys.executable

    args = [
        str((PROJECT_ROOT / a).resolve()) if (PROJECT_ROOT / a).exists() else a
        for a in (entry.get("args") or [])
    ]

    transport = StdioTransport(
        command=command,
        args=args,
        env=entry.get("env") or None,
        cwd=entry.get("cwd") or str(PROJECT_ROOT),
    )
    return MCPToolset(transport, id=MCP_SERVER_NAME)


def load_prompt(name: str) -> str:
    """Read an agent's system prompt from backend/prompts/<name>.md."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Missing prompt file: {path}")
    return path.read_text(encoding="utf-8")
