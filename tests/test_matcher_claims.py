from datetime import date

from bima_radar.claims import render_markdown
from tests.conftest import TODAY


def _paying(result):
    return {v.cover_id.split(":")[0]: v.amount for v in result.paying}


def test_accidental_death_checks_every_cover(radar):
    ev = radar.report("death", "accident", TODAY)
    result = radar.match(ev.id)
    assert len(result.verdicts) == 5
    assert _paying(result) == {"pmsby": 200_000, "pmjjby": 200_000, "rupay": 200_000, "loan": 41_200}
    assert result.to_family == 600_000
    assert result.to_lender == 41_200


def test_illness_death_pays_only_life_and_loan(radar):
    ev = radar.report("death", "illness", TODAY)
    assert set(_paying(radar.match(ev.id))) == {"pmjjby", "loan"}


def test_card_unused_too_long_drops_rupay(radar):
    ev = radar.report("death", "accident", TODAY)
    result = radar.match(ev.id, card_days=95)
    assert "rupay" not in _paying(result)
    rupay = next(v for v in result.verdicts if v.cover_id.startswith("rupay"))
    assert "95 days" in rupay.reasons[0]


def test_hospital_bill_from_payments_finds_no_cover(radar):
    events = radar.events()
    assert len(events) == 1 and events[0].source == "payments" and events[0].bill == 38_000
    assert radar.match(events[0].id).paying == []


def test_train_injury_pays_hospital_costs_up_to_cap(radar):
    ev = radar.report("hospitalisation", "accident", date(2026, 6, 2), bill=250_000, pnr="4217730954")
    assert _paying(radar.match(ev.id)) == {"irctc": 200_000}


def test_death_after_renewal_needs_new_premium(radar):
    # On 2 Jun 2026 a new cover year has started and no new premium is on record.
    ev = radar.report("death", "accident", date(2026, 6, 2))
    assert {"pmsby", "pmjjby"}.isdisjoint(_paying(radar.match(ev.id)))


def test_claim_pack_merges_papers(radar):
    ev = radar.report("death", "accident", TODAY)
    pack = radar.claim_pack(ev.id)
    assert len(pack.claims) == 4
    labels = [p["label"] for p in pack.papers]
    assert labels.count("Death certificate") == 1
    death_cert = next(p for p in pack.papers if p["key"] == "death_certificate")
    assert len(death_cert["needed_by"]) == 4
    assert next(p for p in pack.papers if p["key"] == "card_statement")["auto"]
    rupay = next(c for c in pack.claims if c.cover_id.startswith("rupay"))
    assert rupay.deadline == "2026-08-26"
    assert "Sunita Kumar" in rupay.fields["Claimant"]
    assert "RuPay card accident cover" in render_markdown(pack)


def test_family_message_in_hindi_and_english(radar):
    ev = radar.report("death", "accident", TODAY)
    hi = radar.family(ev.id, "hi")
    en = radar.family(ev.id, "en")
    assert hi[0].startswith("सुनीता जी")
    assert "₹6 लाख" in hi[1]
    assert "26 अगस्त 2026" in hi[3]
    assert "₹6 lakh" in en[1]
