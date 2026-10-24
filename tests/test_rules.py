from datetime import date

from bima_radar import rules
from tests.conftest import TODAY


def test_rupay_status_follows_card_use(radar, by_type):
    rupay = by_type["rupay_pmjdy"]
    covers = radar.covers()
    assert rules.status(rupay, radar.context(), covers).level == "warn"  # used 70 days ago
    assert rules.status(rupay, radar.context(card_days=10), covers).level == "ok"
    assert rules.status(rupay, radar.context(card_days=95), covers).level == "risk"


def test_atm_withdrawal_does_not_count_as_card_use(radar):
    # The sample has an ATM withdrawal on 14 Feb and a shop payment on 19 Mar. Only the shop payment counts.
    assert radar.context().card_activity["4821"] == "2026-03-19"


def test_renewal_warning_depends_on_balance(radar, by_type):
    pmjjby = by_type["pmjjby"]
    covers = radar.covers()
    assert rules.status(pmjjby, radar.context(), covers).level == "warn"  # ₹210 < ₹456
    assert rules.status(pmjjby, radar.context(balance=500), covers).level == "ok"


def test_cover_year():
    assert rules.cover_year_start(date(2026, 5, 31)) == date(2025, 6, 1)
    assert rules.cover_year_start(date(2026, 6, 1)) == date(2026, 6, 1)
    assert rules.next_renewal(TODAY) == date(2026, 5, 31)


def test_alerts(radar):
    titles = [a.title for a in radar.alerts()]
    assert any("RuPay" in t for t in titles)
    assert any("renew" in t for t in titles)
    assert any("nominee" in t for t in titles)
    assert len(radar.alerts(card_days=5, balance=1000)) == 1  # only the nominee alert is left
