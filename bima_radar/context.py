"""Facts about the person's accounts that the rules engine needs: card use, balances, the nominee."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from bima_radar import schemes
from bima_radar.finder import RUPAY_CARD_RE
from bima_radar.models import Record


@dataclass
class Context:
    today: date
    card_activity: dict[str, str] = field(default_factory=dict)  # card last4 -> last qualifying use (ISO date)
    balances: dict[str, float] = field(default_factory=dict)  # account -> balance
    person: dict = field(default_factory=dict)
    nominee: dict = field(default_factory=dict)

    def last_card_use(self, last4: str) -> date | None:
        v = self.card_activity.get(last4)
        return date.fromisoformat(v) if v else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["today"] = self.today.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Context":
        return cls(**{**d, "today": date.fromisoformat(d["today"])})


def build_context(records: list[Record], profile: dict, today: date) -> Context:
    ctx = Context(today=today, person=profile.get("person", {}), nominee=profile.get("nominee", {}))
    for r in records:
        if r.source != "aa":
            continue
        if r.data.get("kind") == "account":
            ctx.balances[r.data["account"]] = r.data["balance"]
        elif r.data.get("kind") == "txn" and r.data.get("mode") in schemes.CARD_ACTIVITY_MODES and r.at and r.at <= today:
            m = RUPAY_CARD_RE.search(r.data.get("narration", ""))
            if m:
                last4 = m.group(2)
                prev = ctx.card_activity.get(last4)
                if prev is None or r.at.isoformat() > prev:
                    ctx.card_activity[last4] = r.at.isoformat()
    return ctx
