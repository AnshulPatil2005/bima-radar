"""The pipeline in one place: ingest -> find -> map -> watch -> match -> claim."""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

from bima_radar import llm_finder, rules, watcher
from bima_radar.claims import ClaimPack, build_claim_pack
from bima_radar.context import Context, build_context
from bima_radar.finder import find_covers, unexplained
from bima_radar.i18n import family_message
from bima_radar.matcher import MatchResult, lapse_alerts, match_event
from bima_radar.models import Alert, Cover, LifeEvent, Record, Status
from bima_radar.sources import ingest, load_consent, load_profile
from bima_radar.store import Store

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class BimaRadar:
    def __init__(self, db_path: str = ":memory:"):
        self.store = Store(db_path)

    # ---- scan ----
    def scan(self, folder: Path | str, today: date | None = None, use_llm: bool = False) -> dict:
        folder = Path(folder)
        consent = load_consent(folder)
        profile = load_profile(folder)
        today = today or (date.fromisoformat(profile["as_of"]) if profile.get("as_of") else date.today())
        records, source_log = ingest(folder, consent)

        covers = find_covers(records)
        llm_log: list[str] = []
        if use_llm:
            for r in unexplained(records, covers):
                try:
                    found = llm_finder.extract(r.text, r.source, r.ref)
                    covers += found
                    llm_log.append(f"{r.ref}: {len(found)} cover(s)")
                except llm_finder.LLMUnavailable as e:
                    llm_log.append(str(e))
                    break

        ctx = build_context(records, profile, today)
        events = watcher.from_payments(records)
        self.store.replace_covers(covers)
        self.store.set_meta("context", ctx.to_dict())
        for e in events:
            self.store.save_event(e)
        return {"today": today, "sources": source_log, "records": len(records), "covers": covers, "events": events, "llm": llm_log}

    # ---- the map ----
    def context(self, **what_if) -> Context:
        d = self.store.meta("context")
        if d is None:
            raise RuntimeError("Nothing scanned yet. Run a scan first.")
        ctx = Context.from_dict(d)
        return apply_what_if(ctx, self.covers(), **what_if)

    def covers(self) -> list[Cover]:
        return self.store.covers()

    def cover_map(self, **what_if) -> list[tuple[Cover, Status]]:
        covers, ctx = self.covers(), self.context(**what_if)
        return [(c, rules.status(c, ctx, covers)) for c in covers]

    def alerts(self, **what_if) -> list[Alert]:
        return lapse_alerts(self.covers(), self.context(**what_if))

    # ---- events ----
    def report(self, kind: str, cause: str, when: date, bill: int | None = None, pnr: str | None = None, note: str = "") -> LifeEvent:
        event = watcher.reported(kind, cause, when, bill, pnr, note)
        self.store.save_event(event)
        return event

    def events(self) -> list[LifeEvent]:
        return self.store.events()

    def match(self, event_id: str, **what_if) -> MatchResult:
        event = self.store.event(event_id)
        if event is None:
            raise KeyError(f"No event {event_id}")
        return match_event(event, self.covers(), self.context(**what_if))

    def claim_pack(self, event_id: str, **what_if) -> ClaimPack:
        result = self.match(event_id, **what_if)
        pack = build_claim_pack(result, self.covers(), self.context(**what_if))
        self.store.save_pack(event_id, pack.to_dict())
        return pack

    def family(self, event_id: str, lang: str = "hi", **what_if) -> list[str]:
        result = self.match(event_id, **what_if)
        pack = self.claim_pack(event_id, **what_if)
        return family_message(result, pack, self.covers(), self.context(**what_if), lang)

    # ---- free text ----
    def find_in_text(self, text: str, use_llm: bool = False, save: bool = False) -> tuple[list[Cover], str]:
        records = [Record("sms", "text:pasted", text, None, {}), Record("document", "text:pasted-doc", text, None, {"file": "pasted text"})]
        covers = find_covers(records)
        how = "rules"
        if use_llm:
            try:
                covers = llm_finder.extract(text, "text", "text:pasted") or covers
                how = "claude"
            except llm_finder.LLMUnavailable as e:
                how = f"rules (Claude unavailable: {e})"
        if save:
            for c in covers:
                self.store.add_cover(c)
        return covers, how


def apply_what_if(ctx: Context, covers: list[Cover], card_days: int | None = None, balance: float | None = None) -> Context:
    """Change the facts for one question without touching the stored map (the sliders in a demo)."""
    if card_days is None and balance is None:
        return ctx
    ctx = dataclasses.replace(ctx, card_activity=dict(ctx.card_activity), balances=dict(ctx.balances))
    if card_days is not None:
        for c in covers:
            if c.type == "rupay_pmjdy":
                ctx.card_activity[c.attrs["card_last4"]] = date.fromordinal(ctx.today.toordinal() - card_days).isoformat()
    if balance is not None:
        for account in ctx.balances:
            ctx.balances[account] = balance
    return ctx
