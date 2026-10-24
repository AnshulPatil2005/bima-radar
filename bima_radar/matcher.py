"""Stage 4 · Matcher and lapse guard, built on the rules engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from bima_radar import rules
from bima_radar.context import Context
from bima_radar.fmt import inr, lakh, nice_date
from bima_radar.models import Alert, Cover, LifeEvent, Verdict


@dataclass
class MatchResult:
    event: LifeEvent
    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def paying(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.pays]

    @property
    def to_family(self) -> int:
        return sum(v.amount for v in self.paying if v.payee in {"nominee", "insured"})

    @property
    def to_lender(self) -> int:
        return sum(v.amount for v in self.paying if v.payee == "lender")


def match_event(event: LifeEvent, covers: list[Cover], ctx: Context) -> MatchResult:
    """Check one event against every cover on the map."""
    return MatchResult(event, [rules.match(c, event, ctx) for c in covers])


def lapse_alerts(covers: list[Cover], ctx: Context) -> list[Alert]:
    alerts: list[Alert] = []
    renewal_done = False
    for c in covers:
        s = rules.status(c, ctx, covers)
        if s.level not in {"warn", "risk"}:
            continue
        if c.type == "rupay_pmjdy":
            last = ctx.last_card_use(c.attrs.get("card_last4", ""))
            days = (ctx.today - last).days if last else None
            if s.level == "risk":
                alerts.append(Alert(c.id, "risk", "Your RuPay accident cover is off",
                                    f"The card has not been used for {days} days. The free {lakh(c.sum_insured)} cover needs one card "
                                    "payment every 90 days. One payment switches it back on.", "Pay once with this card"))
            else:
                alerts.append(Alert(c.id, "warn", f"Use your RuPay card in the next {90 - days} days",
                                    f"Your free {lakh(c.sum_insured)} accident cover needs one card payment every 90 days. "
                                    f"You last used the card {days} days ago.", "Pay once with this card"))
        elif c.type in {"pmsby", "pmjjby"} and not renewal_done:
            renewal_done = True
            account = c.attrs.get("account")
            due = rules._renewal_premiums_due(covers, account)
            balance = ctx.balances.get(account, 0)
            at_stake = sum(x.sum_insured or 0 for x in covers if x.type in {"pmsby", "pmjjby"} and x.attrs.get("account") == account)
            if s.level == "risk":
                alerts.append(Alert(c.id, "risk", "PMJJBY or PMSBY has lapsed",
                                    "No premium was found for this cover year. Re-enrol at the bank branch.", "Re-enrol"))
            else:
                alerts.append(Alert(c.id, "warn", f"PMJJBY and PMSBY renew by {nice_date(rules.next_renewal(ctx.today))}",
                                    f"The {inr(due)} premiums need money in {account}. Your balance is {inr(balance)}. If the debit "
                                    f"fails, {lakh(at_stake)} of cover lapses and nobody tells the family.",
                                    f"Add {inr(max(due - balance, 0))}"))
        elif c.type == "irctc_travel":
            alerts.append(Alert(c.id, "warn", "Your train ticket has no nominee",
                                f"PNR {c.attrs.get('pnr')} carries up to {lakh(c.sum_insured)} of travel cover. Add a nominee so "
                                "your family can claim without going through legal heirs.", "Add nominee"))
    return alerts
