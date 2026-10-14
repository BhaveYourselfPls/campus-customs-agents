"""Smoke test — launches the MCP server over stdio exactly as .mcp.json does,
calls all 3 tools through a real MCP client, and records the evidence.

Run:  .venv/Scripts/python.exe mcp_server/smoke_test.py
Out:  output/mcp_smoke.json
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import Client

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
_RAW = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))


def _resolved_config() -> dict:
    """Resolve .mcp.json's portable entries against this checkout.

    The committed config uses a bare "python" and a repo-relative script path
    so a clone works anywhere. Launching it needs the interpreter actually in
    use and an absolute path, which is what this does.
    """
    import sys

    cfg = {"mcpServers": {}}
    for name, entry in _RAW["mcpServers"].items():
        entry = dict(entry)
        if Path(entry.get("command", "")).stem.lower() in {"python", "python3"}:
            entry["command"] = sys.executable
        entry["args"] = [
            str((ROOT / a).resolve()) if (ROOT / a).exists() else a
            for a in entry.get("args", [])
        ]
        entry.setdefault("cwd", str(ROOT))
        cfg["mcpServers"][name] = entry
    return cfg


CONFIG = _resolved_config()

# Each case is the customer-facing prompt an agent would be answering, the tool
# that answers it, and the arguments the agent would pass.
CASES = [
    {
        "ticket": "#2 Handsome Dan (vocabulary gap)",
        "asked_by": "Customer Service agent",
        "prompt": "Do you have any item with Handsome Dan on it?",
        "tool": "search_products",
        "arguments": {"query": "any item with handsome dan", "limit": 3},
    },
    {
        "ticket": "#3 emerald green hoodie (color gap)",
        "asked_by": "Customer Service agent",
        "prompt": "Do you have a bright emerald green hoodie, and can we actually ship one?",
        "tool": "search_products",
        "arguments": {
            "query": "bright emerald green hoodie",
            "in_stock_only": True,
            "limit": 3,
        },
    },
    {
        "ticket": "#1 gym shorts (assortment gap)",
        "asked_by": "Inventory agent",
        "prompt": "A customer asked for gym shorts. Do we carry anything that matches?",
        "tool": "search_products",
        "arguments": {"query": "im looking for gym shorts", "limit": 5},
    },
    {
        "ticket": "#3 promise gate",
        "asked_by": "Customer Service agent",
        "prompt": "Before I promise it — is the Basic Hoodie Big Yale available in size L?",
        "tool": "check_stock",
        "arguments": {"product_id": "basic-hoodie-big-yale", "size": "L"},
    },
    {
        "ticket": "promise gate, negative case",
        "asked_by": "Inventory agent",
        "prompt": "Can we still sell the Baseball Left Chest Crewneck in XS?",
        "tool": "check_stock",
        "arguments": {"product_id": "baseball-left-chest-crewneck", "size": "XS"},
    },
    {
        "ticket": "all open tickets",
        "asked_by": "Boss agent",
        "prompt": "What tickets are still open, and whose problem is each one?",
        "tool": "find_unmet_demand",
        "arguments": {},
    },
]


def _payload(result) -> object:
    """Pull the structured JSON an MCP tool returned."""
    if getattr(result, "data", None) is not None:
        return result.data
    if getattr(result, "structured_content", None):
        return result.structured_content
    return [getattr(c, "text", str(c)) for c in result.content]


async def main() -> None:
    async with Client(CONFIG) as client:
        tools = await client.list_tools()
        tool_names = sorted(t.name for t in tools)

        results = []
        for case in CASES:
            name = f"campus-customs-shop_{case['tool']}"
            if not any(t.name == name for t in tools):
                name = case["tool"]
            res = await client.call_tool(name, case["arguments"])
            results.append(
                {
                    "ticket": case["ticket"],
                    "asked_by": case["asked_by"],
                    "prompt": case["prompt"],
                    "tool_name": case["tool"],
                    "arguments": case["arguments"],
                    "tool_output": _payload(res),
                }
            )

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "server": "campus-customs-shop",
        "transport": "stdio (launched from .mcp.json)",
        "database": "data/campus_customs_new.db",
        "tools_discovered": tool_names,
        "test_count": len(results),
        "tests": results,
    }

    out = ROOT / "output" / "mcp_smoke.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"Wrote {out} — {len(results)} calls across {len(tool_names)} tools")
    for r in results:
        o = r["tool_output"]
        if r["tool_name"] == "search_products":
            summary = f"{o['match_count']} matches, unmatched={o['unmatched_terms']}"
        elif r["tool_name"] == "check_stock":
            summary = f"{o['status']}, qty={o.get('quantity')}, can_promise={o['can_promise']}"
        else:
            summary = f"{o['open_ticket_count']} open tickets {o['by_classification']}"
        print(f"  [{r['tool_name']}] {summary}")


if __name__ == "__main__":
    asyncio.run(main())
