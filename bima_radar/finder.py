"""Stage 2 · Cover Finder. Turns plain Records into Covers, with the line each one came from.

The rules here recognise the bundled covers the pitch is about. Anything they cannot
explain can be sent to the Gemini extractor in llm_finder.py.
"""

from __future__ import annotations

import re

from bima_radar import schemes
from bima_radar.models import Cover, Evidence, Record
from bima_radar.sources import account_in

PMSBY_RE = re.compile(r"\bPMSBY\b|Suraksha\s+Bima", re.I)
PMJJBY_RE = re.compile(r"\bPMJJBY\b|Jeevan\s+Jyoti", re.I)
DEBIT_RE = re.compile(r"debit|premium|renewal", re.I)
RUPAY_CARD_RE = re.compile(r"RUPAY\D{0,20}(\d{4})?X*(\d{4})", re.I)
LOAN_PROTECT_RE = re.compile(
    r"(loan\s+protection|credit\s+shield|credit\s+life|group\s+credit|loan\s+(?:insurance|cover|secure))", re.I
)
LOAN_NO_RE = re.compile(r"Loan\s*(?:No|Number|A/c|ID)\.?\s*[:#]?\s*([A-Z]{1,5}-?\d{3,})", re.I)
RUPEES = r"(?:Rs\.?|INR|₹)\s?([\d,]+(?:\.\d+)?)"
PREMIUM_RE = re.compile(LOAN_PROTECT_RE.pattern + r"[^\n]*?" + RUPEES, re.I)
OUTSTANDING_RE = re.compile(r"^\s*(?:principal\s+)?outstanding[^\n]*?" + RUPEES, re.I | re.M)
SUM_ASSURED_RE = re.compile(r"sum\s+(?:assured|insured)\s*[:=]?\s*" + RUPEES, re.I)
LENDER_RE = re.compile(r"^\s*([A-Z][A-Z &.-]+(?:FINANCE|BANK|CAPITAL|FINSERV|LTD|LIMITED)[A-Z &.-]*)", re.M)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _line_with(text: str, pattern: re.Pattern) -> str:
    for line in text.splitlines():
        if pattern.search(line):
            return line.strip()
    return text.strip()[:200]


def _ev(r: Record, quote: str | None = None) -> Evidence:
    return Evidence(r.source, r.ref, (quote or r.text)[:300], r.at.isoformat() if r.at else None)


class _Map:
    """Merges findings for the same cover from different sources into one Cover."""

    def __init__(self):
        self.covers: dict[str, Cover] = {}

    def add(self, cover: Cover, ev: Evidence, **attrs) -> Cover:
        existing = self.covers.get(cover.id)
        if existing is None:
            self.covers[cover.id] = existing = cover
        if all(e.ref != ev.ref for e in existing.evidence):
            existing.evidence.append(ev)
        for k, v in attrs.items():
            if isinstance(v, list):
                existing.attrs.setdefault(k, [])
                existing.attrs[k] = sorted(set(existing.attrs[k]) | set(v))
            elif v is not None:
                existing.attrs[k] = v
        return existing


def _scheme_premium(m: _Map, r: Record, scheme: str):
    account = r.data.get("account") or account_in(r.text) or "unknown"
    when = r.at.isoformat() if r.at else None
    if scheme == "pmsby":
        cover = Cover(f"pmsby:{account}", "pmsby", "PMSBY accident cover", "Accident", schemes.PMSBY["accidental_death"], "nominee",
                      {"account": account, "premium": schemes.PMSBY["premium"]})
    else:
        cover = Cover(f"pmjjby:{account}", "pmjjby", "PMJJBY life cover", "Life", schemes.PMJJBY["death"], "nominee",
                      {"account": account, "premium": schemes.PMJJBY["premium"]})
    m.add(cover, _ev(r), premiums_paid=[when] if when else [])


def find_covers(records: list[Record]) -> list[Cover]:
    m = _Map()
    pmjdy_accounts: dict[str, dict] = {}
    rupay_cards: dict[str, list[Record]] = {}

    for r in records:
        text = r.text
        # Government schemes show up as small yearly debits, in SMS and in the statement.
        if r.source in {"sms", "aa"} and r.data.get("kind") != "account":
            if PMSBY_RE.search(text) and DEBIT_RE.search(text):
                _scheme_premium(m, r, "pmsby")
            if PMJJBY_RE.search(text) and DEBIT_RE.search(text):
                _scheme_premium(m, r, "pmjjby")
        # A Jan Dhan account, and RuPay card use on it, together mean card accident cover.
        if r.source == "aa" and r.data.get("kind") == "account" and (r.data.get("scheme") or "").upper() == "PMJDY":
            pmjdy_accounts[r.data["account"]] = {"record": r, **r.data}
        if r.source == "aa" and r.data.get("kind") == "txn":
            cm = RUPAY_CARD_RE.search(r.data.get("narration", ""))
            if cm:
                rupay_cards.setdefault(r.data["account"], []).append(r)
        # Loan protection is a line inside the loan papers.
        if r.source == "document" and LOAN_PROTECT_RE.search(text):
            loan_no = (LOAN_NO_RE.search(text) or [None, "unknown"])[1].upper()
            prem = PREMIUM_RE.search(text)
            outstanding = OUTSTANDING_RE.search(text)
            sum_assured = SUM_ASSURED_RE.search(text)
            lender = LENDER_RE.search(text)
            left = int(_num(outstanding.group(1))) if outstanding else (int(_num(sum_assured.group(1))) if sum_assured else None)
            cover = Cover(f"loan:{loan_no}", "loan_protection", "Bike-loan protection" if "two-wheeler" in text.lower() else "Loan protection",
                          "Loan", left, "lender")
            m.add(cover, _ev(r, _line_with(text, LOAN_PROTECT_RE)), loan_no=loan_no,
                  premium=int(_num(prem.group(prem.lastindex))) if prem else None, outstanding=left,
                  lender=lender.group(1).strip() if lender else None, closed=False, file=r.data.get("file"))
        # Travel insurance ticked while booking a train.
        if r.source == "payments" and r.data.get("type") == "train_booking" and r.data["meta"].get("travel_insurance"):
            meta = r.data["meta"]
            cover = Cover(f"irctc:{meta['pnr']}", "irctc_travel", "Train travel cover", "Travel", schemes.IRCTC_TRAVEL["death"], "nominee")
            m.add(cover, _ev(r), pnr=meta["pnr"], journey_date=meta.get("journey_date"), route=f"{meta.get('from')} to {meta.get('to')}",
                  nominee=meta.get("nominee"), passenger=meta.get("passenger"))

    for account, info in pmjdy_accounts.items():
        cards = rupay_cards.get(account)
        if not cards:
            continue
        last4 = RUPAY_CARD_RE.search(cards[-1].data["narration"]).group(2)
        opened = info.get("opened")
        new_cover = opened and opened >= schemes.RUPAY_PMJDY["new_cover_from"].isoformat()
        amount = schemes.RUPAY_PMJDY["cover_new"] if new_cover else schemes.RUPAY_PMJDY["cover_old"]
        cover = Cover(f"rupay:{last4}", "rupay_pmjdy", "RuPay card accident cover", "Accident", amount, "nominee")
        m.add(cover, _ev(info["record"]), account=account, card_last4=last4, account_opened=opened)
        m.add(cover, _ev(cards[-1]))

    return list(m.covers.values())


INSURANCE_HINT_RE = re.compile(r"insur|bima|policy|cover|protect|shield|assured|premium", re.I)


def unexplained(records: list[Record], covers: list[Cover]) -> list[Record]:
    """Records that mention insurance but did not become a cover. These go to the Gemini extractor."""
    used = {e.ref for c in covers for e in c.evidence}
    return [r for r in records if r.ref not in used and INSURANCE_HINT_RE.search(r.text)]
