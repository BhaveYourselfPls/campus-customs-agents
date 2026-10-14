"""Append-only audit trail for output/audit_trail.json.

The contract is one-way: records are added, never edited, never removed. A
decision that turns out to be wrong is corrected by appending a new record,
so the history of what the team believed and when stays intact.

Three mechanisms enforce that:
  1. Every write re-reads the existing file and appends to it.
  2. A write that would shrink the record count raises instead of truncating.
  3. The file is written to a temp file and atomically replaced, so an
     interrupted run cannot leave a half-written trail behind.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import AuditStep

AUDIT_PATH = Path(__file__).resolve().parent.parent / "output" / "audit_trail.json"

# Agents may run concurrently; serialise writes so no record is lost to a race.
_LOCK = threading.Lock()

# Keys whose values must never reach the trail, at any nesting depth.
_REDACT_KEYS = {
    "api_key", "apikey", "portkey_api_key", "authorization", "password",
    "password_hash", "token", "secret", "x-portkey-api-key",
}


def _redact(value: Any) -> Any:
    """Strip credentials and password hashes before anything is persisted.

    The audit trail is the file most likely to be shared with an auditor or
    committed, so it is the worst place for a secret to leak into.
    """
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if k.lower() in _REDACT_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _read_existing() -> list[dict]:
    if not AUDIT_PATH.exists():
        return []
    try:
        raw = AUDIT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Never discard an unreadable trail — quarantine it and start fresh,
        # so the damaged history is still recoverable by hand.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        AUDIT_PATH.rename(AUDIT_PATH.with_suffix(f".corrupt-{stamp}.json"))
        return []
    return data if isinstance(data, list) else [data]


def append(step: AuditStep) -> int:
    """Append one step. Returns the new total number of records on file."""
    record = _redact(json.loads(step.model_dump_json()))

    with _LOCK:
        existing = _read_existing()
        updated = existing + [record]

        if len(updated) <= len(existing):
            raise RuntimeError("Refusing to write: audit trail would not grow.")

        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _write(updated)

    return len(updated)


def _write(records: list[dict]) -> None:
    """Persist the trail, preferring an atomic replace.

    OneDrive and other sync clients hold transient locks that make os.replace
    fail with WinError 5, so we retry briefly and then fall back to writing in
    place. The fallback is only reached when the atomic path is impossible;
    losing a record is worse than a non-atomic write.
    """
    payload = json.dumps(records, indent=2)
    tmp = AUDIT_PATH.with_suffix(".tmp")

    for attempt in range(4):
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, AUDIT_PATH)
            return
        except PermissionError:
            time.sleep(0.15 * (attempt + 1))

    tmp.unlink(missing_ok=True)
    AUDIT_PATH.write_text(payload, encoding="utf-8")


class RunRecorder:
    """Per-run sequence counter so steps are ordered within a single question."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.seq = 0
        self.total_written = 0

    def log(
        self,
        step_type: str,
        actor: str,
        summary: str,
        payload: dict | None = None,
        model: str | None = None,
        duration_ms: int | None = None,
        tokens: dict[str, int] | None = None,
    ) -> AuditStep:
        self.seq += 1
        step = AuditStep(
            run_id=self.run_id,
            seq=self.seq,
            step_type=step_type,  # type: ignore[arg-type]
            actor=actor,
            summary=summary,
            payload=payload or {},
            model=model,
            duration_ms=duration_ms,
            tokens=tokens,
        )
        self.total_written = append(step)
        return step
