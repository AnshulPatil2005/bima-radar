"""Stage 4 · Rules engine. One rule set per cover type: is it working today, and does it pay for an event?

The language model never decides eligibility. Every yes or no here comes with its reasons.
"""

from __future__ import annotations

from datetime import date, timedelta

from bima_radar import schemes
from bima_radar.context import Context
from bima_radar.fmt import inr, lakh, nice_date
from bima_radar.models import Check, Cover, LifeEvent, Status, Verdict


def cover_year_start(d: date) -> date:
    m = schemes.COVER_YEAR_START_MONTH
    return date(d.year if d.month >= m else d.year - 1, m, 1)


def next_renewal(today: date) -> date:
    """31 May at the end of the current cover year."""
    start = cover_year_start(today)
    return date(start.year + 1, start.month, 1) - timedelta(days=1)


def premium_paid_for(cover: Cover, d: date) -> bool:
    start = cover_year_start(d)
    window = (start - timedelta(days=31), start + timedelta(days=92))
    return any(window[0] <= date.fromisoformat(p) <= window[1] for p in cover.attrs.get("premiums_paid", []))


def _renewal_premiums_due(covers: list[Cover], account: str) -> int:
    return sum(c.attrs.get("premium", 0) for c in covers if c.type in {"pmsby", "pmjjby"} and c.attrs.get("account") == account)


# ---------- status: is the cover working today? ----------

def status(cover: Cover, ctx: Context, all_covers: list[Cover] | None = None) -> Status:
    all_covers = all_covers or [cover]
    t = cover.type
    today = ctx.today

    if t == "rupay_pmjdy":
        last = ctx.last_card_use(cover.attrs.get("card_last4", ""))
        window = schemes.RUPAY_PMJDY["card_use_window_days"]
        days = (today - last).days if last else None
        checks = [
            Check(days is not None and days <= window,
                  f"One card payment in the {window} days before an accident. Last one: "
                  + (f"{nice_date(last)} ({days} days ago)." if last else "none found.")),
            Check(True, f"Account opened {cover.attrs.get('account_opened')}, so the cover is {lakh(cover.sum_insured)}."),
            Check(None, f"Tell the bank within {schemes.RUPAY_PMJDY['intimation_days']} days of an accident."),
        ]
        if days is None or days > window:
            return Status("risk", f"Off: card not used for {days if days is not None else 'over ' + str(window)} days", checks)
        if days >= schemes.RUPAY_PMJDY["warn_from_days"]:
            return Status("warn", f"Use the card within {window - days} days to keep it on", checks)
        return Status("ok", f"Active · card used {days} days ago", checks)

    if t in {"pmsby", "pmjjby"}:
        renewal = next_renewal(today)
        account = cover.attrs.get("account")
        balance = ctx.balances.get(account)
        due = _renewal_premiums_due(all_covers, account)
        paid_now = premium_paid_for(cover, today)
        checks = [
            Check(paid_now, f"Premium paid for the cover year starting {nice_date(cover_year_start(today))}."
                  if paid_now else "No premium found for this cover year."),
            Check(balance is not None and balance >= due,
                  f"Renewal on {nice_date(renewal)} needs {inr(due)} in {account}. Balance: "
                  + (inr(balance) if balance is not None else "unknown") + "."),
        ]
        if not paid_now:
            return Status("risk", "Lapsed: no premium this year", checks)
        if (renewal - today).days <= schemes.RENEWAL_REMINDER_DAYS and (balance is None or balance < due):
            return Status("warn", f"Renews {nice_date(renewal)} · balance too low", checks)
        return Status("ok", f"Active · renews {nice_date(renewal)}", checks)

    if t == "loan_protection":
        left = cover.attrs.get("outstanding")
        if cover.attrs.get("closed"):
            return Status("info", "Ended with the loan", [Check(None, "The loan was closed, so this cover has ended.")])
        return Status("ok", f"Active · {inr(left)} left on the loan" if left else "Active",
                      [Check(True, f"Loan {cover.attrs.get('loan_no')} is running."),
                       Check(None, "If the loan is closed early, this cover ends with it.")])

    if t == "irctc_travel":
        jd = cover.attrs.get("journey_date")
        journey = date.fromisoformat(jd) if jd else None
        nominee = cover.attrs.get("nominee")
        checks = [Check(None, f"Covers only the {nice_date(journey) if journey else 'booked'} journey ({cover.attrs.get('route', '')})."),
                  Check(bool(nominee), f"Nominee: {nominee}." if nominee else "No nominee yet. Without one, the money goes to legal heirs.")]
        if journey and journey < today:
            return Status("info", "Journey over · cover ended", checks)
        if not nominee:
            return Status("warn", "No nominee added", checks)
        return Status("ok", f"Active for the {nice_date(journey)} journey", checks)

    return Status("info", "Added from text · check the terms", [Check(None, "Bima Radar cannot check these terms yet.")])


# ---------- match: does the cover pay for this event? ----------

def match(cover: Cover, event: LifeEvent, ctx: Context) -> Verdict:
    v = Verdict(cover.id, cover.name, False, payee=cover.payee)
    t = cover.type
    accident_death = event.type == "death" and event.cause == "accident"

    if t == "rupay_pmjdy":
        if not accident_death:
            v.reasons.append("Pays only for death or full disability in an accident.")
            return v
        last = ctx.last_card_use(cover.attrs.get("card_last4", ""))
        window = schemes.RUPAY_PMJDY["card_use_window_days"]
        days = (event.date - last).days if last else None
        if days is None or days > window or days < 0:
            v.reasons.append(f"Card last used {days if days is not None else 'never'} days before the accident; the rule needs {window} or fewer.")
            return v
        v.pays, v.amount = True, cover.sum_insured or 0
        v.reasons.append(f"Accident, and the card was used {days} days before it ({window} or fewer).")
        v.deadline, v.deadline_label = event.date + timedelta(days=schemes.RUPAY_PMJDY["intimation_days"]), "Tell the bank by"
        return v

    if t == "pmsby":
        if not accident_death:
            v.reasons.append("Pays only for accidental death or disability.")
            return v
        if not premium_paid_for(cover, event.date):
            v.reasons.append(f"No premium found for the cover year starting {nice_date(cover_year_start(event.date))}.")
            return v
        v.pays, v.amount = True, schemes.PMSBY["accidental_death"]
        v.reasons.append("Accidental death, and this cover year's ₹20 premium was paid.")
        v.deadline, v.deadline_label = event.date + timedelta(days=schemes.PMSBY["claim_window_days"]), "File by"
        return v

    if t == "pmjjby":
        if event.type != "death":
            v.reasons.append("Pays only on death.")
            return v
        if not premium_paid_for(cover, event.date):
            v.reasons.append(f"No premium found for the cover year starting {nice_date(cover_year_start(event.date))}.")
            return v
        enrolled = cover.attrs.get("enrolled_on")
        if enrolled and event.cause != "accident" and (event.date - date.fromisoformat(enrolled)).days < schemes.PMJJBY["lien_days"]:
            v.reasons.append("Death from illness within 30 days of joining is not covered.")
            return v
        v.pays, v.amount = True, schemes.PMJJBY["death"]
        v.reasons.append("Death from any cause, and this cover year's ₹436 premium was paid.")
        v.deadline, v.deadline_label = event.date + timedelta(days=schemes.PMJJBY["claim_window_days"]), "File by"
        return v

    if t == "loan_protection":
        if event.type != "death":
            v.reasons.append("Pays only on death.")
            return v
        if cover.attrs.get("closed"):
            v.reasons.append("The loan was closed, so the cover had ended.")
            return v
        v.pays, v.amount = True, cover.attrs.get("outstanding") or 0
        v.reasons.append("Pays the lender what is left, so the family stops paying EMIs.")
        return v

    if t == "irctc_travel":
        if event.pnr != cover.attrs.get("pnr") or event.cause != "accident":
            v.reasons.append(f"Covers only accidents on the {cover.attrs.get('route', 'booked')} journey (PNR {cover.attrs.get('pnr')}).")
            return v
        if event.type == "death":
            v.pays, v.amount = True, schemes.IRCTC_TRAVEL["death"]
            v.reasons.append("Death in an accident on the insured journey.")
        else:
            v.pays, v.amount = True, min(event.bill or 0, schemes.IRCTC_TRAVEL["hospitalisation_max"])
            v.payee = "insured"
            v.reasons.append(f"Accident on the insured journey. Hospital costs are covered up to {lakh(schemes.IRCTC_TRAVEL['hospitalisation_max'])}.")
        return v

    v.pays = None
    v.reasons.append("Added from free text. The exact terms need checking.")
    return v
