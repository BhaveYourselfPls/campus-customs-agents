"""FastAPI backend for the Campus Customs agent team.

Start from backend/:

    uvicorn main:app --reload --port 8000

Interactive docs: http://127.0.0.1:8000/docs

Two layers with different authority, kept apart on purpose:
  - the agents reach the shop through the MCP server, which is read-only
    except for recording decisions;
  - money moves only through /approvals/{id}/pay, which requires a named human
    and a decision already on the record.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import shop_data
from boss import run_team
from config import MODEL_NAME

app = FastAPI(
    title="Campus Customs — Agent Team API",
    description="Boss, Inventory, Accounting, Facilities and Customer Service over one MCP server.",
    version="1.0.0",
)

# The React dashboard runs on a different port in development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    """Create the operational tables and seed checking if this is a fresh DB."""
    shop_data.ensure_schema()


# --------------------------------------------------------------------------
# Request bodies
# --------------------------------------------------------------------------
class RunRequest(BaseModel):
    question: str | None = Field(
        default=None,
        description="Override the question. Defaults to a full review of this ticket.",
    )


class ResolveRequest(BaseModel):
    decision: str = Field(min_length=3, description="What was decided.")
    rationale: str = Field(min_length=3, description="Why. A resolution with no reasoning is rejected.")
    resolved_by: str = Field(min_length=2, description="Who is closing it.")
    owner: str | None = Field(default=None, description="Accountable agent; defaults to the suggested owner.")


class PaymentApproval(BaseModel):
    amount: float = Field(gt=0, description="USD to debit from checking.")
    approved_by: str = Field(
        min_length=2,
        description="Name of the human approving. Agent names are rejected.",
    )
    memo: str = Field(min_length=3, description="What is being bought, and why.")


# --------------------------------------------------------------------------
# 1. Tickets and status
# --------------------------------------------------------------------------
@app.get("/tickets", tags=["tickets"])
def get_tickets() -> dict:
    """The 3 open tickets and their status.

    Status is Resolved only when the Boss has recorded a resolution against
    the ticket ref — never because an agent said so in prose.
    """
    tickets = shop_data.list_tickets()
    return {
        "count": len(tickets),
        "open": sum(1 for t in tickets if t["status"] == "Open"),
        "resolved": sum(1 for t in tickets if t["status"] == "Resolved"),
        "tickets": tickets,
    }


@app.get("/tickets/{ticket_id}", tags=["tickets"])
def get_ticket(ticket_id: str) -> dict:
    """One ticket by id, e.g. `T1-gym-shorts`."""
    ticket = shop_data.get_ticket(ticket_id)
    if ticket is None:
        known = [t["ticket_id"] for t in shop_data.list_tickets()]
        raise HTTPException(404, f"Unknown ticket '{ticket_id}'. Known: {known}")
    return ticket


# --------------------------------------------------------------------------
# 2. Run the agent team on a ticket
# --------------------------------------------------------------------------
@app.post("/tickets/{ticket_id}/run", tags=["agents"])
async def run_on_ticket(ticket_id: str, body: RunRequest | None = None) -> dict:
    """Run the full agent team against one ticket.

    Synchronous and slow by design — a full Boss-plus-specialists loop takes
    tens of seconds against a real model. Every step appends to
    output/audit_trail.json while it runs, so /actions shows progress.
    """
    ticket = shop_data.get_ticket(ticket_id)
    if ticket is None:
        known = [t["ticket_id"] for t in shop_data.list_tickets()]
        raise HTTPException(404, f"Unknown ticket '{ticket_id}'. Known: {known}")

    question = (body.question if body and body.question else None) or (
        f"Work ticket {ticket['ticket_id']}. The customer "
        f"({ticket['customer']}) asked: \"{ticket['customer_asked']}\". "
        f"It is classified {ticket['classification']}. Decide what we do, who owns it, "
        f"and whether it needs my approval. Record the resolution."
    )

    result = await run_team(question)
    return {
        "ticket_id": ticket["ticket_id"],
        "model": MODEL_NAME,
        "run_id": result.run_id,
        "summary": result.summary,
        "decisions": [d.model_dump(mode="json") for d in result.decisions],
        "reports": [r.model_dump(mode="json") for r in result.reports],
        "escalations": result.escalations,
        "steps_logged": result.steps_logged,
        "error": result.error,
    }


@app.get("/tickets/{ticket_id}/history", tags=["tickets"])
def ticket_history(ticket_id: str) -> dict:
    """The most recent completed run for this ticket, read back from the trail.

    Lets the dashboard show who worked a resolved ticket after a reload,
    instead of losing it with the browser tab.
    """
    return shop_data.ticket_history(ticket_id)


@app.post("/tickets/{ticket_id}/resolve", tags=["tickets"])
def resolve_ticket(ticket_id: str, body: ResolveRequest) -> dict:
    """Mark a ticket resolved by recording a human decision against it.

    Status is never a flag someone flips — it is derived from the resolution
    record. Closing a ticket therefore means writing down who closed it and
    why, which is exactly what makes the status defensible later.
    """
    ticket = shop_data.get_ticket(ticket_id)
    if ticket is None:
        known = [t["ticket_id"] for t in shop_data.list_tickets()]
        raise HTTPException(404, f"Unknown ticket '{ticket_id}'. Known: {known}")

    result = shop_data.record_resolution(
        ticket_ref=ticket["ticket_id"],
        decision=body.decision,
        rationale=body.rationale,
        decided_by=body.resolved_by,
        owner=body.owner or ticket["suggested_owner"],
    )
    if not result.get("recorded"):
        raise HTTPException(400, result)
    return result


# --------------------------------------------------------------------------
# 3. Recent agent actions
# --------------------------------------------------------------------------
@app.get("/actions", tags=["agents"])
def get_actions(
    limit: int = Query(50, ge=1, le=500),
    run_id: str | None = Query(None, description="Filter to one run."),
) -> dict:
    """Recent agent actions: who acted, what they said, which tools they used.

    Read straight from the append-only audit trail, so this reflects what was
    actually recorded rather than a separate in-memory view that could drift.
    """
    return shop_data.recent_actions(limit=limit, run_id=run_id)


# --------------------------------------------------------------------------
# 4. Human-approved payment
# --------------------------------------------------------------------------
@app.post("/approvals/{resolution_id}/pay", tags=["money"])
def approve_payment(resolution_id: int, body: PaymentApproval) -> dict:
    """Debit checking against a recorded decision, after a human approved it.

    This is the only route in the system that moves money, and no agent can
    reach it. It refuses: a non-positive amount, a missing or agent-named
    approver, a resolution that is not on the record, and any amount that
    would overdraw the account.
    """
    result = shop_data.approve_payment(
        resolution_id=resolution_id,
        amount=body.amount,
        approved_by=body.approved_by,
        memo=body.memo,
    )
    if not result.get("approved"):
        raise HTTPException(400, result)
    return result


# --------------------------------------------------------------------------
# 5. Checking balance
# --------------------------------------------------------------------------
@app.get("/cash/checking", tags=["money"])
def get_checking() -> dict:
    """Current checking balance from `cash_accounts`, plus the last 10 movements."""
    return shop_data.checking_balance()


# --------------------------------------------------------------------------
# 6. Reset
# --------------------------------------------------------------------------
@app.post("/admin/reset", tags=["admin"])
def reset() -> dict:
    """Restore the working database from the untouched baseline.

    Destructive to `campus_customs_new.db` by design. It does not touch the
    pristine `campus_customs.db`, and it does not touch the audit trail — the
    record of what the agents did survives a data reset, which is what keeps
    the reset auditable rather than a cover-up.
    """
    result = shop_data.reset_database()
    if not result.get("reset"):
        raise HTTPException(500, result)
    return result


@app.get("/health", tags=["admin"])
def health() -> dict:
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "database": str(shop_data.DB_PATH.name),
        "agents": ["Boss", "Inventory", "Accounting", "Facilities", "CustomerService"],
    }
