"""The four specialist agents: Inventory, Accounting, Facilities, Customer Service.

They share one shape — same MCP server, same output type, same audit hooks —
and differ only in their system prompt and which tools they are told to reach
for. Keeping them uniform is what lets the Boss treat their reports
interchangeably and lets the audit trail record every one the same way.

Each specialist is given the whole MCP toolset but is instructed, in its own
prompt, which tools are its own. That is deliberate: full connectivity means a
specialist can verify a neighbour's claim rather than taking it on trust.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pydantic_ai import Agent

from audit import RunRecorder
from config import MODEL_NAME, build_model, build_mcp_server, load_prompt
from models import Confidence, SpecialistReport

# agent name -> prompt file in backend/prompts/
SPECIALISTS: dict[str, str] = {
    "Inventory": "inventory",
    "Accounting": "accounting",
    "Facilities": "facilities",
    "CustomerService": "customer_service",
}


@dataclass
class SpecialistDeps:
    """Shared run state handed to every specialist call."""

    recorder: RunRecorder
    mcp_server: object


def build_specialist(name: str, mcp_server) -> Agent[None, SpecialistReport]:
    """Construct one specialist agent bound to the shared MCP server."""
    if name not in SPECIALISTS:
        raise ValueError(f"Unknown specialist: {name}. Known: {sorted(SPECIALISTS)}")

    return Agent(
        build_model(),
        output_type=SpecialistReport,
        system_prompt=load_prompt(SPECIALISTS[name]),
        toolsets=[mcp_server],
        name=name,
        retries=2,
    )


async def run_specialist(
    name: str,
    question: str,
    recorder: RunRecorder,
    mcp_server,
) -> SpecialistReport:
    """Run one specialist on one question and audit every stage of it.

    Failures are caught and returned as a low-confidence report rather than
    raised. A specialist crashing must not take down the Boss's whole run —
    the Boss needs to see that the agent failed and decide without it, which
    is exactly what a `needs_human` report tells him.
    """
    started = time.perf_counter()
    recorder.log(
        "delegation",
        actor="Boss",
        summary=f"Boss asked {name}: {question[:120]}",
        payload={"to": name, "question": question},
    )

    agent = build_specialist(name, mcp_server)

    try:
        result = await agent.run(question)
        report = result.output
        report.agent = name  # type: ignore[assignment]

        # Record which MCP tools actually ran, not which the prompt suggested.
        tool_calls: list[dict] = []
        for message in result.all_messages():
            for part in getattr(message, "parts", []):
                # `final_result` is pydantic-ai's internal structured-output
                # call, not an MCP tool. Logging it would overstate tool use.
                if (
                    part.__class__.__name__ == "ToolCallPart"
                    and getattr(part, "tool_name", "") != "final_result"
                ):
                    tool_calls.append(
                        {"tool": getattr(part, "tool_name", "?"),
                         "args": str(getattr(part, "args", ""))[:400]}
                    )

        for call in tool_calls:
            recorder.log(
                "tool_call",
                actor=name,
                summary=f"{name} called {call['tool']}",
                payload=call,
                model=MODEL_NAME,
            )

        # `usage` is a property in pydantic-ai 2.x and a method in 1.x.
        usage = result.usage
        if callable(usage):
            usage = usage()
        recorder.log(
            "specialist_report",
            actor=name,
            summary=f"{name}: {report.summary[:140]}",
            payload={
                "recommendation": report.recommendation,
                "confidence": report.confidence.value,
                "needs_human": report.needs_human,
                "escalation_reason": report.escalation_reason,
                "findings": [f.model_dump(mode="json") for f in report.findings],
                "tools_actually_called": [c["tool"] for c in tool_calls],
            },
            model=MODEL_NAME,
            duration_ms=round((time.perf_counter() - started) * 1000),
            tokens={
                "input": getattr(usage, "input_tokens", 0) or 0,
                "output": getattr(usage, "output_tokens", 0) or 0,
            },
        )

        if report.needs_human:
            recorder.log(
                "escalation",
                actor=name,
                summary=f"{name} escalated: {report.escalation_reason or 'no reason given'}",
                payload={"reason": report.escalation_reason,
                         "recommendation": report.recommendation},
            )

        return report

    except Exception as exc:  # noqa: BLE001 - a failed specialist must not kill the run
        recorder.log(
            "error",
            actor=name,
            summary=f"{name} failed: {type(exc).__name__}",
            payload={"error": str(exc)[:600], "question": question},
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return SpecialistReport(
            agent=name,  # type: ignore[arg-type]
            summary=f"{name} could not complete this request.",
            recommendation="Treat this agent's input as unavailable for this decision.",
            confidence=Confidence.low,
            needs_human=True,
            escalation_reason=f"{name} errored: {type(exc).__name__}: {str(exc)[:200]}",
        )
