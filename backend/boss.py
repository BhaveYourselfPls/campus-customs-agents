"""Boss agent — owns the loop, delegates to specialists, makes the decisions.

The Boss is the only agent with a delegation tool. Specialists are exposed to
it as a single `ask_specialist` tool rather than four, so adding a sixth agent
is a dict entry and not a new tool definition.

Every delegation is counted against MAX_DELEGATIONS_PER_RUN. That cap is a
spend guard rail: without it a confused Boss can loop specialists indefinitely
against a paid API.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic_ai import Agent, RunContext

from audit import RunRecorder
from config import (
    MAX_DELEGATIONS_PER_RUN,
    MODEL_NAME,
    build_model,
    build_mcp_server,
    load_prompt,
)
from models import SpecialistReport, TeamRunResult, TicketDecision
from specialists import SPECIALISTS, run_specialist


@dataclass
class BossDeps:
    recorder: RunRecorder
    mcp_server: object
    reports: list[SpecialistReport] = field(default_factory=list)
    delegations: int = 0


class BossOutput(TeamRunResult):
    """What the Boss agent itself returns; the orchestrator fills in the rest."""


def build_boss(mcp_server) -> Agent[BossDeps, list[TicketDecision]]:
    agent = Agent(
        build_model(),
        deps_type=BossDeps,
        output_type=list[TicketDecision],
        system_prompt=load_prompt("boss"),
        toolsets=[mcp_server],
        name="Boss",
        retries=2,
    )

    @agent.tool
    async def ask_specialist(
        ctx: RunContext[BossDeps],
        specialist: str,
        question: str,
    ) -> dict:
        """Ask one specialist one question and get their structured report back.

        `specialist` must be one of: Inventory, Accounting, Facilities,
        CustomerService. Ask a single, concrete question — a delegation
        containing two questions comes back with two half-answers.
        """
        if specialist not in SPECIALISTS:
            return {
                "error": f"Unknown specialist '{specialist}'.",
                "valid": sorted(SPECIALISTS),
            }

        if ctx.deps.delegations >= MAX_DELEGATIONS_PER_RUN:
            ctx.deps.recorder.log(
                "escalation",
                actor="orchestrator",
                summary=f"Delegation cap hit ({MAX_DELEGATIONS_PER_RUN}); refusing further calls",
                payload={"cap": MAX_DELEGATIONS_PER_RUN},
            )
            return {
                "error": "Delegation budget exhausted for this run.",
                "instruction": "Decide with what you already have, or escalate to a human.",
            }

        ctx.deps.delegations += 1
        report = await run_specialist(
            specialist, question, ctx.deps.recorder, ctx.deps.mcp_server
        )
        ctx.deps.reports.append(report)
        return report.model_dump(mode="json")

    return agent


async def run_team(question: str) -> TeamRunResult:
    """Run one full team loop against `question`, auditing every step.

    Returns a TeamRunResult even on failure — the caller always gets a record
    of what happened, and the audit trail always gets a terminal step.
    """
    run_id = f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    recorder = RunRecorder(run_id)
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    recorder.log(
        "run_started",
        actor="orchestrator",
        summary=f"Team run started: {question[:140]}",
        payload={
            "question": question,
            "team": ["Boss", *SPECIALISTS],
            "delegation_cap": MAX_DELEGATIONS_PER_RUN,
        },
        model=MODEL_NAME,
    )

    mcp_server = build_mcp_server()
    result = TeamRunResult(run_id=run_id, question=question, started_at=started_at)

    try:
        boss = build_boss(mcp_server)
        deps = BossDeps(recorder=recorder, mcp_server=mcp_server)

        async with boss:  # starts the MCP server subprocess once for the run
            run = await boss.run(question, deps=deps)

        decisions = run.output
        result.decisions = decisions
        result.reports = deps.reports

        # The Boss's own MCP calls were previously invisible: only specialist
        # tool calls were instrumented, so `record_ticket_resolution` landed in
        # the database with nothing in the trail to show who called it. An
        # audit log that misses the one tool that writes is the wrong thing to
        # be missing, so the Boss's calls are now recorded here too.
        for message in run.all_messages():
            for part in getattr(message, "parts", []):
                name = getattr(part, "tool_name", "")
                if (
                    part.__class__.__name__ == "ToolCallPart"
                    and name not in ("final_result", "ask_specialist")
                ):
                    recorder.log(
                        "tool_call",
                        actor="Boss",
                        summary=f"Boss called {name}",
                        payload={"tool": name, "args": str(getattr(part, "args", ""))[:400]},
                        model=MODEL_NAME,
                    )

        for d in decisions:
            recorder.log(
                "decision",
                actor="Boss",
                summary=f"{d.ticket_ref}: {d.decision[:120]}",
                payload=d.model_dump(mode="json"),
                model=MODEL_NAME,
            )

        result.escalations = [
            f"{r.agent}: {r.escalation_reason}"
            for r in deps.reports
            if r.needs_human and r.escalation_reason
        ] + [
            f"Boss: {d.ticket_ref} needs human approval"
            for d in decisions
            if d.needs_human_approval
        ]

        pending = sum(1 for d in decisions if d.needs_human_approval)
        result.summary = (
            f"{len(decisions)} decision(s) from {len(deps.reports)} specialist report(s); "
            f"{pending} awaiting human approval."
        )

    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
        result.summary = "Run failed before decisions were reached."
        recorder.log(
            "error",
            actor="orchestrator",
            summary=f"Run failed: {type(exc).__name__}",
            payload={"error": str(exc)[:800]},
        )

    result.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    recorder.log(
        "run_finished",
        actor="orchestrator",
        summary=result.summary,
        payload={
            "decisions": len(result.decisions),
            "reports": len(result.reports),
            "escalations": result.escalations,
            "error": result.error,
        },
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    result.steps_logged = recorder.seq
    return result
