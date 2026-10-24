"""HTTP API over the pipeline (FastAPI). Run: python -m bima_radar serve"""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from bima_radar.pipeline import SAMPLES, BimaRadar

app = FastAPI(title="Bima Radar", version="0.1.0", description="Find hidden insurance cover, keep it alive, prepare claims.")
radar = BimaRadar(os.environ.get("BIMA_RADAR_DB", ":memory:"))


class ScanIn(BaseModel):
    sample: str = Field("suresh", description="Folder name under samples/")
    today: date | None = None
    use_llm: bool = False


class EventIn(BaseModel):
    type: str = Field(..., pattern="^(death|hospitalisation)$")
    cause: str = Field("accident", pattern="^(accident|illness)$")
    when: date | None = Field(None, description="Date of the event; defaults to the scan date")
    bill: int | None = None
    pnr: str | None = None


class FindIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=60_000)
    use_llm: bool = False
    save: bool = False


def _what_if(card_days: int | None, balance: float | None) -> dict:
    return {k: v for k, v in {"card_days": card_days, "balance": balance}.items() if v is not None}


@app.post("/scan")
def scan(body: ScanIn):
    allowed = {p.name for p in SAMPLES.iterdir() if p.is_dir()}
    if body.sample not in allowed:
        raise HTTPException(404, f"Unknown sample. Available: {', '.join(sorted(allowed))}")
    report = radar.scan(SAMPLES / body.sample, today=body.today, use_llm=body.use_llm)
    return {
        "today": report["today"].isoformat(),
        "sources": report["sources"],
        "records": report["records"],
        "covers": [c.to_dict() for c in report["covers"]],
        "events": [e.to_dict() for e in report["events"]],
        "llm": report["llm"],
    }


@app.get("/covers")
def covers(card_days: int | None = None, balance: float | None = None):
    return [{"cover": c.to_dict(), "status": asdict(s)} for c, s in radar.cover_map(**_what_if(card_days, balance))]


@app.get("/alerts")
def alerts(card_days: int | None = None, balance: float | None = None):
    return [asdict(a) for a in radar.alerts(**_what_if(card_days, balance))]


@app.post("/events")
def report_event(body: EventIn):
    when = body.when or radar.context().today
    ev = radar.report(body.type, body.cause, when, bill=body.bill, pnr=body.pnr)
    return ev.to_dict()


@app.get("/events")
def events():
    return [e.to_dict() for e in radar.events()]


@app.get("/events/{event_id}/match")
def match(event_id: str, card_days: int | None = None):
    try:
        result = radar.match(event_id, **_what_if(card_days, None))
    except KeyError:
        raise HTTPException(404, "No such event")
    verdicts = [{**asdict(v), "deadline": v.deadline.isoformat() if v.deadline else None} for v in result.verdicts]
    return {"event": result.event.to_dict(), "verdicts": verdicts, "to_family": result.to_family, "to_lender": result.to_lender}


@app.get("/events/{event_id}/claims")
def claims(event_id: str):
    try:
        return radar.claim_pack(event_id).to_dict()
    except KeyError:
        raise HTTPException(404, "No such event")


@app.get("/events/{event_id}/family")
def family(event_id: str, lang: str = "hi"):
    if lang not in {"hi", "en"}:
        raise HTTPException(422, "lang must be hi or en")
    try:
        return {"lang": lang, "messages": radar.family(event_id, lang)}
    except KeyError:
        raise HTTPException(404, "No such event")


@app.post("/find")
def find(body: FindIn):
    covers, how = radar.find_in_text(body.text, use_llm=body.use_llm, save=body.save)
    return {"read_by": how, "covers": [c.to_dict() for c in covers]}
