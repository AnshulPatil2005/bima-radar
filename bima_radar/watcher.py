"""Stage 3 · Event Watcher. Life events come from payments (a hospital bill) or from a report (a death)."""

from __future__ import annotations

import hashlib
from datetime import date

from bima_radar import schemes
from bima_radar.models import LifeEvent, Record

EVENT_TYPES = {"death", "hospitalisation"}
CAUSES = {"accident", "illness"}


def event_id(kind: str, cause: str, when: date, extra: str = "") -> str:
    return "ev-" + hashlib.sha1(f"{kind}|{cause}|{when.isoformat()}|{extra}".encode()).hexdigest()[:8]


def from_payments(records: list[Record]) -> list[LifeEvent]:
    """A payment at a hospital is a moment to check cover. The cause is unknown, so it is treated as illness
    until the user says otherwise."""
    out = []
    for r in records:
        if r.source != "payments":
            continue
        mcc = str(r.data.get("mcc", ""))
        if mcc in schemes.HEALTH_MCC and r.data.get("amount", 0) >= 5_000 and r.at:
            out.append(LifeEvent(
                id=event_id("hospitalisation", "illness", r.at, r.ref),
                type="hospitalisation", cause="illness", date=r.at, bill=int(r.data["amount"]),
                source="payments", note=f"{schemes.HEALTH_MCC[mcc].title()} payment: {r.data.get('merchant')} ({r.ref})",
            ))
    return out


def reported(kind: str, cause: str, when: date, bill: int | None = None, pnr: str | None = None, note: str = "") -> LifeEvent:
    if kind not in EVENT_TYPES:
        raise ValueError(f"Unknown event type {kind!r}. Use one of: {', '.join(sorted(EVENT_TYPES))}.")
    if cause not in CAUSES:
        raise ValueError(f"Unknown cause {cause!r}. Use one of: {', '.join(sorted(CAUSES))}.")
    return LifeEvent(event_id(kind, cause, when, pnr or ""), kind, cause, when, bill=bill, pnr=pnr, source="reported", note=note)
