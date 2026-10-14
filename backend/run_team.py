"""CLI entry point — run the team against one question.

    .venv/Scripts/python.exe backend/run_team.py "What tickets are open?"

Appends to output/audit_trail.json. Never truncates it.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from boss import run_team  # noqa: E402

DEFAULT_QUESTION = (
    "Review every open customer ticket. For each one, decide what we do about it, "
    "who owns it, and whether it needs my approval. Record each resolution."
)


async def main() -> None:
    question = " ".join(sys.argv[1:]).strip() or DEFAULT_QUESTION
    result = await run_team(question)

    print(f"\nrun_id: {result.run_id}")
    print(f"summary: {result.summary}")
    if result.error:
        print(f"ERROR: {result.error}")

    for d in result.decisions:
        flag = "  [NEEDS HUMAN APPROVAL]" if d.needs_human_approval else ""
        print(f"\n[{d.ticket_ref}] owner={d.owner} ({d.classification}){flag}")
        print(f"  decision:  {d.decision}")
        print(f"  rationale: {d.rationale}")

    if result.escalations:
        print("\nEscalations:")
        for e in result.escalations:
            print(f"  - {e}")

    print(f"\naudit steps this run: {result.steps_logged}")


if __name__ == "__main__":
    asyncio.run(main())
