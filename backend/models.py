"""Shared data types for the Campus Customs agent team.

Every structured hand-off between agents is typed here so a specialist cannot
return free prose where the Boss expects a decision, and so the audit trail
records the same shape every time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

AgentName = Literal["Boss", "Inventory", "Accounting", "Facilities", "CustomerService"]

AGENT_NAMES: tuple[str, ...] = (
    "Boss",
    "Inventory",
    "Accounting",
    "Facilities",
    "CustomerService",
)


class Confidence(str, Enum):
    """How much weight the Boss should put on a specialist's answer."""

    high = "high"        # grounded in tool output the specialist actually read
    medium = "medium"    # grounded, but with a judgment call layered on top
    low = "low"          # tools were inconclusive; this is inference


class Severity(str, Enum):
    info = "info"
    warning = "warning"
    blocker = "blocker"


class Finding(BaseModel):
    """One grounded observation from a specialist.

    `evidence` must quote or cite the tool output it came from. A finding with
    no evidence is an opinion, and the Boss is instructed to discount it.
    """

    statement: str = Field(description="What is true, in one sentence.")
    evidence: str = Field(description="The tool output or DB value this rests on.")
    severity: Severity = Severity.info
    tools_used: list[str] = Field(default_factory=list)


class SpecialistReport(BaseModel):
    """What every specialist returns to the Boss. Same shape for all four."""

    agent: AgentName
    summary: str = Field(description="Two sentences maximum, for the Boss to read first.")
    findings: list[Finding] = Field(default_factory=list)
    recommendation: str = Field(description="The single action this agent advises.")
    confidence: Confidence = Confidence.medium
    needs_human: bool = Field(
        default=False,
        description="True when this exceeds the agent's authority or the data cannot settle it.",
    )
    escalation_reason: str | None = None

    @field_validator("escalation_reason")
    @classmethod
    def _reason_required(cls, v: str | None, info) -> str | None:
        if info.data.get("needs_human") and not (v or "").strip():
            raise ValueError("needs_human=True requires an escalation_reason")
        return v


class TicketDecision(BaseModel):
    """The Boss's ruling on one ticket."""

    ticket_ref: str = Field(description="Stable reference, e.g. 'T1-gym-shorts'.")
    customer_ask: str
    classification: Literal["true_assortment_gap", "fixable_by_search", "undetermined"]
    decision: str = Field(description="The action being taken, stated as a commitment.")
    rationale: str = Field(description="Why, citing which specialist's finding carried it.")
    owner: AgentName = Field(description="The agent accountable for carrying it out.")
    product_ids: list[str] = Field(default_factory=list)
    consulted: list[AgentName] = Field(default_factory=list)
    needs_human_approval: bool = Field(
        default=False,
        description="True for spend, new SKUs, or anything irreversible to a customer.",
    )
    recorded_resolution_id: int | None = None


class TeamRunResult(BaseModel):
    """The whole loop, as returned to the caller and the dashboard."""

    run_id: str
    question: str
    decisions: list[TicketDecision] = Field(default_factory=list)
    reports: list[SpecialistReport] = Field(default_factory=list)
    summary: str = ""
    steps_logged: int = 0
    escalations: list[str] = Field(default_factory=list)
    started_at: str
    finished_at: str | None = None
    error: str | None = None


class AuditStep(BaseModel):
    """One append-only line in output/audit_trail.json.

    Deliberately flat and self-describing: an auditor reading a single record
    should be able to tell who acted, on what input, with which tools, and what
    came back, without needing the rest of the file.
    """

    run_id: str
    seq: int = Field(description="Monotonic within a run, starting at 1.")
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    step_type: Literal[
        "run_started",
        "delegation",
        "agent_step",
        "tool_call",
        "specialist_report",
        "decision",
        "escalation",
        "run_finished",
        "error",
    ]
    actor: str = Field(description="Agent name, or 'orchestrator' for loop mechanics.")
    model: str | None = None
    summary: str = Field(description="One line a human can read without opening the payload.")
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None
    tokens: dict[str, int] | None = None
