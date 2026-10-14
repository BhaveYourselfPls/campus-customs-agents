"""Direct database access for the API layer.

Deliberately separate from the MCP server. The MCP server is the *agents'*
interface and is read-only apart from recording decisions; this module is the
*operator's* interface and is the only place money moves.

That split is the control: an agent cannot pay for anything, because no agent
has a tool that reaches these functions. A human calling the approval route
does.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "campus_customs_new.db"
BASELINE_DB = PROJECT_ROOT / "data" / "campus_customs.db"

sys.path.insert(0, str(PROJECT_ROOT / "mcp_server"))

OPENING_CHECKING_BALANCE = 25_000.00

# Stable, human-readable refs so the API, the Boss's decisions and
# output/desk_tickets.html all name the same ticket the same way.
TICKET_SLUGS: list[tuple[str, str]] = [
    (r"shorts", "T1-gym-shorts"),
    (r"handsome\s*dan", "T2-handsome-dan"),
    (r"emerald|green", "T3-emerald-green-hoodie"),
]


def connect(readonly: bool = False) -> sqlite3.Connection:
    uri = f"file:{DB_PATH}?mode=ro" if readonly else f"file:{DB_PATH}"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema() -> None:
    """Create the operational tables if they are absent, and seed cash once.

    Safe to call repeatedly — it is run at startup and again after a reset.
    """
    conn = connect()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cash_accounts (
                   account_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                   account_name TEXT NOT NULL UNIQUE,
                   account_type TEXT NOT NULL,
                   balance      REAL NOT NULL,
                   currency     TEXT NOT NULL DEFAULT 'USD',
                   updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        # Append-only money log. Balance is derived from it, never edited blind.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cash_transactions (
                   txn_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                   account_name  TEXT NOT NULL,
                   amount        REAL NOT NULL,
                   direction     TEXT NOT NULL CHECK (direction IN ('debit','credit')),
                   memo          TEXT NOT NULL,
                   resolution_id INTEGER,
                   approved_by   TEXT NOT NULL,
                   balance_after REAL NOT NULL,
                   created_at    TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ticket_resolutions (
                   resolution_id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ticket_ref    TEXT NOT NULL,
                   decision      TEXT NOT NULL,
                   rationale     TEXT NOT NULL,
                   decided_by    TEXT NOT NULL,
                   owner         TEXT NOT NULL,
                   product_ids   TEXT NOT NULL DEFAULT '[]',
                   recorded_at   TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        existing = conn.execute(
            "SELECT COUNT(*) FROM cash_accounts WHERE account_name = 'checking'"
        ).fetchone()[0]
        if not existing:
            conn.execute(
                """INSERT INTO cash_accounts (account_name, account_type, balance)
                   VALUES ('checking', 'operating', ?)""",
                (OPENING_CHECKING_BALANCE,),
            )
        conn.commit()
    finally:
        conn.close()


def ticket_ref_for(ask: str, index: int) -> str:
    low = ask.lower()
    for pattern, slug in TICKET_SLUGS:
        if re.search(pattern, low):
            return slug
    return f"T{index}-{re.sub(r'[^a-z0-9]+', '-', low)[:28].strip('-')}"


def list_tickets() -> list[dict]:
    """The 3 tickets with Open/Resolved status.

    Open vs Resolved is decided by whether the Boss has recorded a resolution
    against the ticket ref, not by anything the agents assert in prose.
    """
    import server  # imported late so DB_PATH is settled first

    demand = server.find_unmet_demand(limit=20)

    conn = connect(readonly=True)
    try:
        resolutions = conn.execute(
            "SELECT * FROM ticket_resolutions ORDER BY resolution_id"
        ).fetchall()
    except sqlite3.OperationalError:
        resolutions = []
    finally:
        conn.close()

    by_ref: dict[str, list[dict]] = {}
    for r in resolutions:
        by_ref.setdefault(r["ticket_ref"], []).append(dict(r))

    tickets = []
    for i, t in enumerate(demand["tickets"], start=1):
        ref = ticket_ref_for(t["customer_asked"], i)
        # Match loosely: the Boss may append its own suffix to the ref.
        matched = [
            row
            for key, rows in by_ref.items()
            if ref.lower() in key.lower() or key.lower() in ref.lower()
            for row in rows
        ]
        tickets.append(
            {
                "ticket_id": ref,
                "status": "Resolved" if matched else "Open",
                "customer": t["user_name"],
                "customer_email": t["user_email"],
                "customer_asked": t["customer_asked"],
                "asked_at": t["asked_at"],
                "times_asked": t["times_asked"],
                "classification": t["classification"],
                "suggested_owner": t["owner"],
                "unmatched_terms": t["unmatched_terms"],
                "would_now_find": t["would_now_find"],
                "resolutions": matched,
            }
        )
    return tickets


def get_ticket(ticket_id: str) -> dict | None:
    want = ticket_id.strip().lower()
    for t in list_tickets():
        if t["ticket_id"].lower() == want or t["ticket_id"].lower().startswith(want):
            return t
    return None


def record_resolution(
    ticket_ref: str,
    decision: str,
    rationale: str,
    decided_by: str,
    owner: str,
) -> dict:
    """Append a resolution. Same append-only contract as the agents' tool.

    A human closing a ticket writes a row exactly like the Boss does, so the
    history reads uniformly regardless of who closed what.
    """
    for name, value in (
        ("decision", decision), ("rationale", rationale),
        ("decided_by", decided_by), ("owner", owner),
    ):
        if not (value or "").strip():
            return {"recorded": False, "error": f"{name} is required"}

    ensure_schema()
    conn = connect()
    try:
        cur = conn.execute(
            """INSERT INTO ticket_resolutions
                   (ticket_ref, decision, rationale, decided_by, owner, product_ids)
               VALUES (?, ?, ?, ?, ?, '[]')""",
            (ticket_ref, decision.strip(), rationale.strip(),
             decided_by.strip(), owner.strip()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ticket_resolutions WHERE resolution_id = ?", (cur.lastrowid,)
        ).fetchone()
    finally:
        conn.close()
    return {"recorded": True, "status": "Resolved", "resolution": dict(row)}


def checking_balance() -> dict:
    conn = connect(readonly=True)
    try:
        row = conn.execute(
            "SELECT * FROM cash_accounts WHERE account_name = 'checking'"
        ).fetchone()
        txns = conn.execute(
            """SELECT * FROM cash_transactions WHERE account_name = 'checking'
               ORDER BY txn_id DESC LIMIT 10"""
        ).fetchall()
    finally:
        conn.close()

    if row is None:
        return {"account_name": "checking", "balance": None,
                "error": "No checking account. Call /admin/reset or restart the API."}

    return {
        "account_name": row["account_name"],
        "account_type": row["account_type"],
        "balance": round(row["balance"], 2),
        "currency": row["currency"],
        "updated_at": row["updated_at"],
        "opening_balance": OPENING_CHECKING_BALANCE,
        "recent_transactions": [dict(t) for t in txns],
    }


def approve_payment(
    resolution_id: int,
    amount: float,
    approved_by: str,
    memo: str,
) -> dict:
    """Debit checking against a Boss decision that a human has approved.

    Four refusals, all of which must hold for this to be safe:
      - the amount must be positive
      - a named human approver is required (no agent name is accepted)
      - the resolution must already exist, so money only moves against a
        decision that is on the record
      - the balance must cover it; this never goes negative
    """
    if amount is None or amount <= 0:
        return {"approved": False, "error": "amount must be greater than zero"}
    if not (approved_by or "").strip():
        return {"approved": False, "error": "approved_by is required (name the human approver)"}
    if (approved_by or "").strip() in {"Boss", "Inventory", "Accounting",
                                       "Facilities", "CustomerService"}:
        return {
            "approved": False,
            "error": "approved_by must be a human. Agents cannot approve their own spend.",
        }
    if not (memo or "").strip():
        return {"approved": False, "error": "memo is required (what is being bought, and why)"}

    conn = connect()
    try:
        resolution = conn.execute(
            "SELECT * FROM ticket_resolutions WHERE resolution_id = ?", (resolution_id,)
        ).fetchone()
        if resolution is None:
            return {
                "approved": False,
                "error": f"No resolution {resolution_id}. Money only moves against a recorded decision.",
            }

        account = conn.execute(
            "SELECT * FROM cash_accounts WHERE account_name = 'checking'"
        ).fetchone()
        if account is None:
            return {"approved": False, "error": "No checking account exists."}

        balance = float(account["balance"])
        if amount > balance:
            return {
                "approved": False,
                "error": "Insufficient funds.",
                "balance": round(balance, 2),
                "requested": round(amount, 2),
            }

        new_balance = round(balance - amount, 2)
        conn.execute(
            """UPDATE cash_accounts
               SET balance = ?, updated_at = datetime('now')
               WHERE account_name = 'checking'""",
            (new_balance,),
        )
        cur = conn.execute(
            """INSERT INTO cash_transactions
                   (account_name, amount, direction, memo, resolution_id,
                    approved_by, balance_after)
               VALUES ('checking', ?, 'debit', ?, ?, ?, ?)""",
            (round(amount, 2), memo.strip(), resolution_id, approved_by.strip(), new_balance),
        )
        conn.commit()
        txn = conn.execute(
            "SELECT * FROM cash_transactions WHERE txn_id = ?", (cur.lastrowid,)
        ).fetchone()
    finally:
        conn.close()

    return {
        "approved": True,
        "transaction": dict(txn),
        "balance_before": round(balance, 2),
        "balance_after": new_balance,
        "resolution": dict(resolution),
    }


def reset_database() -> dict:
    """Restore the working DB from the untouched baseline, then re-seed cash.

    This is destructive to the working copy by design — it is the point of the
    route. It never touches `campus_customs.db`, and it never touches
    `output/audit_trail.json`: the record of what the agents did survives a
    data reset, which is what makes the reset auditable rather than a cover-up.
    """
    if not BASELINE_DB.exists():
        return {"reset": False, "error": f"Baseline missing: {BASELINE_DB}"}

    conn = connect(readonly=True)
    try:
        before = {
            "resolutions": conn.execute(
                "SELECT COUNT(*) FROM ticket_resolutions"
            ).fetchone()[0],
            "transactions": conn.execute(
                "SELECT COUNT(*) FROM cash_transactions"
            ).fetchone()[0],
        }
    except sqlite3.OperationalError:
        before = {"resolutions": 0, "transactions": 0}
    finally:
        conn.close()

    shutil.copy2(BASELINE_DB, DB_PATH)
    ensure_schema()

    return {
        "reset": True,
        "restored_from": str(BASELINE_DB.relative_to(PROJECT_ROOT)),
        "cleared": before,
        "checking_balance": OPENING_CHECKING_BALANCE,
        "audit_trail": "untouched — output/audit_trail.json is append-only and survives reset",
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _audit_records() -> list[dict]:
    path = PROJECT_ROOT / "output" / "audit_trail.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def ticket_history(ticket_id: str) -> dict:
    """The most recent completed run for a ticket, reconstructed from the trail.

    Without this, a page reload loses the run: the dashboard would show a
    resolved ticket with every agent idle and no record of who did the work.
    The audit trail already holds it, so the board should read it back rather
    than depend on in-memory state that dies with the tab.
    """
    records = _audit_records()

    # A run belongs to a ticket if its opening step named that ticket.
    run_ids: list[str] = []
    for r in records:
        if r.get("step_type") == "run_started":
            question = str((r.get("payload") or {}).get("question", ""))
            if ticket_id.lower() in question.lower():
                run_ids.append(r["run_id"])

    if not run_ids:
        return {"ticket_id": ticket_id, "run_id": None, "actions": [], "decisions": []}

    run_id = run_ids[-1]
    rows = [r for r in records if r.get("run_id") == run_id]

    actions = [
        {
            "run_id": r.get("run_id"),
            "seq": r.get("seq"),
            "ts": r.get("ts"),
            "actor": r.get("actor"),
            "step_type": r.get("step_type"),
            "said": r.get("summary"),
            "tool_used": (r.get("payload") or {}).get("tool"),
            "tools_in_report": (r.get("payload") or {}).get("tools_actually_called"),
            "model": r.get("model"),
            "duration_ms": r.get("duration_ms"),
            "tokens": r.get("tokens"),
        }
        for r in rows
    ]

    return {
        "ticket_id": ticket_id,
        "run_id": run_id,
        "run_count": len(run_ids),
        "actions": actions,
        "decisions": [
            (r.get("payload") or {}) for r in rows if r.get("step_type") == "decision"
        ],
        "reports": [
            (r.get("payload") or {}) for r in rows if r.get("step_type") == "specialist_report"
        ],
        "agents_involved": sorted(
            {r["actor"] for r in rows if r.get("actor") not in (None, "orchestrator")}
        ),
    }


def recent_actions(limit: int = 50, run_id: str | None = None) -> dict:
    """Recent agent activity, read from the append-only audit trail."""
    path = PROJECT_ROOT / "output" / "audit_trail.json"
    if not path.exists():
        return {"count": 0, "actions": [], "note": "No audit trail yet. Run the team first."}

    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"count": 0, "actions": [], "error": "Audit trail is not readable JSON."}

    if run_id:
        records = [r for r in records if r.get("run_id") == run_id]

    actions = []
    for r in records[-limit:]:
        payload = r.get("payload") or {}
        actions.append(
            {
                "run_id": r.get("run_id"),
                "seq": r.get("seq"),
                "ts": r.get("ts"),
                "actor": r.get("actor"),
                "step_type": r.get("step_type"),
                "said": r.get("summary"),
                "tool_used": payload.get("tool"),
                "tools_in_report": payload.get("tools_actually_called"),
                "model": r.get("model"),
                "duration_ms": r.get("duration_ms"),
                "tokens": r.get("tokens"),
            }
        )

    tools_used: dict[str, int] = {}
    for a in actions:
        if a["tool_used"]:
            tools_used[a["tool_used"]] = tools_used.get(a["tool_used"], 0) + 1

    return {
        "count": len(actions),
        "total_on_file": len(records),
        "runs": sorted({a["run_id"] for a in actions if a["run_id"]}),
        "tool_call_counts": tools_used,
        "actions": actions,
    }
