"""Stage 5 · Claim Builder. One claim per paying cover, forms filled from the Cover Map, one list of papers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from bima_radar.context import Context
from bima_radar.fmt import inr, lakh, nice_date
from bima_radar.matcher import MatchResult
from bima_radar.models import Cover

DOCS = {
    "death_certificate": "Death certificate",
    "fir": "FIR copy",
    "post_mortem": "Post-mortem report",
    "claimant_kyc": "Nominee's Aadhaar and PAN",
    "bank_proof": "Passbook or cancelled cheque",
    "card_statement": "Bank statement showing card use",
    "loan_statement": "Loan account statement",
    "hospital_bills": "Hospital bills",
    "discharge_summary": "Discharge summary",
    "ticket": "Train ticket (PNR)",
    "insured_kyc": "Insured person's Aadhaar and PAN",
}
# Papers Bima Radar already holds from consented sources, so the family never has to find them.
AUTO_DOCS = {"card_statement": "the Account Aggregator statement", "loan_statement": "the loan papers", "ticket": "the Paytm booking"}

ROUTES = {
    "pmjjby": ("Bank branch that debits the premium", "PMJJBY claim form and discharge receipt"),
    "pmsby": ("Bank branch that debits the premium", "PMSBY claim form"),
    "rupay_pmjdy": ("Card-issuing bank, which sends it to the insurer", "RuPay PMJDY accident claim form"),
    "loan_protection": ("The lender, under its group credit-life policy", "Credit-life death claim intimation"),
    "irctc_travel": ("Insurer named on the e-ticket", "Travel insurance claim form"),
}


def _docs_for(cover: Cover, event_type: str, cause: str) -> list[str]:
    t = cover.type
    if event_type == "hospitalisation":
        return ["fir", "hospital_bills", "discharge_summary", "ticket", "insured_kyc"]
    base = ["death_certificate", "claimant_kyc", "bank_proof"]
    if cause == "accident" and t in {"pmsby", "rupay_pmjdy", "irctc_travel"}:
        base[1:1] = ["fir", "post_mortem"]
    if t == "rupay_pmjdy":
        base.append("card_statement")
    if t == "loan_protection":
        base = ["death_certificate", "claimant_kyc", "loan_statement"]
    if t == "irctc_travel":
        base.append("ticket")
    return base


@dataclass
class Claim:
    cover_id: str
    cover_name: str
    amount: int
    payee: str
    send_to: str
    form: str
    fields: dict
    documents: list[str]
    deadline: str | None = None
    deadline_label: str = ""
    status: str = "ready"


@dataclass
class ClaimPack:
    event_id: str
    claims: list[Claim] = field(default_factory=list)
    papers: list[dict] = field(default_factory=list)  # [{key, label, needed_by: [...], auto: source|None}]
    to_family: int = 0
    to_lender: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def build_claim_pack(result: MatchResult, covers: list[Cover], ctx: Context) -> ClaimPack:
    by_id = {c.id: c for c in covers}
    ev = result.event
    person, nominee = ctx.person, ctx.nominee
    pack = ClaimPack(ev.id, to_family=result.to_family, to_lender=result.to_lender)
    needed: dict[str, list[str]] = {}

    for v in result.paying:
        cover = by_id[v.cover_id]
        send_to, form = ROUTES.get(cover.type, ("Insurer", "Claim form"))
        docs = _docs_for(cover, ev.type, ev.cause)
        fields = {
            "Insured": person.get("name", "?"),
            "Event": f"{ev.type.replace('_', ' ')} ({ev.cause}) on {nice_date(ev.date)}",
        }
        if ev.type == "death":
            fields["Claimant"] = f"{nominee.get('name', '?')}, {nominee.get('relation', '').lower()} and nominee"
        if cover.attrs.get("account"):
            fields["Account"] = cover.attrs["account"]
        if cover.attrs.get("card_last4"):
            fields["Card"] = f"RuPay ending {cover.attrs['card_last4']}"
        if cover.attrs.get("loan_no"):
            fields["Loan"] = f"{cover.attrs['loan_no']} with {cover.attrs.get('lender') or 'the lender'}"
        if cover.attrs.get("pnr"):
            fields["PNR"] = cover.attrs["pnr"]
        if ev.bill:
            fields["Bill"] = inr(ev.bill)
        fields["Pay into"] = ("The lender, to close the loan" if v.payee == "lender"
                              else f"{nominee.get('name')}'s account {nominee.get('account')}" if ev.type == "death" and nominee
                              else "The insured's own account")
        pack.claims.append(Claim(cover.id, cover.name, v.amount, v.payee, f"{send_to}" + (f" · {cover.attrs['account']}" if cover.type in {"pmsby", "pmjjby"} else ""),
                                 form, fields, docs, v.deadline.isoformat() if v.deadline else None, v.deadline_label))
        for d in docs:
            needed.setdefault(d, []).append(cover.name)

    pack.papers = [{"key": k, "label": DOCS[k], "needed_by": needed[k], "auto": AUTO_DOCS.get(k)} for k in needed]
    return pack


def render_markdown(pack: ClaimPack) -> str:
    lines = [f"# Claim pack · event {pack.event_id}", ""]
    if not pack.claims:
        lines.append("No cover pays for this event.")
        return "\n".join(lines) + "\n"
    lines.append(f"To the family: **{lakh(pack.to_family)}**" + (f" · to the lender: **{inr(pack.to_lender)}**" if pack.to_lender else ""))
    lines += ["", "## Papers to collect once", ""]
    for p in pack.papers:
        mark = "[x]" if p["auto"] else "[ ]"
        src = f" (already on file: {p['auto']})" if p["auto"] else ""
        lines.append(f"- {mark} {p['label']}{src} — for {', '.join(p['needed_by'])}")
    for c in pack.claims:
        lines += ["", f"## {c.cover_name} · {inr(c.amount)}", "", f"Send to: {c.send_to}  ", f"Form: {c.form}, filled  "]
        if c.deadline:
            lines.append(f"{c.deadline_label} {c.deadline}  ")
        lines += ["", "| Field | Value |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in c.fields.items()]
        lines += ["", "Papers: " + ", ".join(DOCS[d] for d in c.documents)]
    return "\n".join(lines) + "\n"
