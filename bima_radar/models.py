"""Plain data types shared by every stage of the pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class Record:
    """One line of consented data, as read from a source (an SMS, a statement row, a document line)."""

    source: str  # "sms" | "aa" | "document" | "payments"
    ref: str  # stable id inside the source, used as the evidence pointer
    text: str  # human-readable text, quoted back to the user as evidence
    at: date | None = None
    data: dict = field(default_factory=dict)  # structured fields: amount, mode, account, meta...


@dataclass
class Evidence:
    source: str
    ref: str
    quote: str
    at: str | None = None


@dataclass
class Cover:
    """A cover on the Cover Map. `attrs` holds the type-specific facts the rules engine needs."""

    id: str
    type: str  # "pmsby" | "pmjjby" | "rupay_pmjdy" | "loan_protection" | "irctc_travel" | "other"
    name: str
    kind: str  # "Accident" | "Life" | "Loan" | "Travel" | "Health" | "Other"
    sum_insured: int | None
    payee: str  # "nominee" | "insured" | "lender"
    attrs: dict = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    found_by: str = "rules"  # "rules" | "llm"
    confidence: str = "high"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Cover":
        return cls(**{**d, "evidence": [Evidence(**e) for e in d.get("evidence", [])]})


@dataclass
class Check:
    ok: bool | None  # None = information, not a pass/fail
    text: str


@dataclass
class Status:
    level: str  # "ok" | "warn" | "risk" | "info"
    text: str
    checks: list[Check] = field(default_factory=list)


@dataclass
class LifeEvent:
    id: str
    type: str  # "death" | "hospitalisation"
    cause: str  # "accident" | "illness"
    date: date
    bill: int | None = None
    pnr: str | None = None  # set when it happened on an insured train journey
    source: str = "reported"  # "reported" | "payments"
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "LifeEvent":
        return cls(**{**d, "date": date.fromisoformat(d["date"])})


@dataclass
class Verdict:
    cover_id: str
    cover_name: str
    pays: bool | None  # None = cannot decide from the rules (cover added from free text)
    amount: int = 0
    payee: str = "nominee"
    reasons: list[str] = field(default_factory=list)
    deadline: date | None = None
    deadline_label: str = ""


@dataclass
class Alert:
    cover_id: str
    level: str  # "warn" | "risk"
    title: str
    body: str
    action: str
