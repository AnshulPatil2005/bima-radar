import json
import shutil
from types import SimpleNamespace

from bima_radar import llm_finder
from bima_radar.finder import find_covers
from bima_radar.models import Record
from bima_radar.pipeline import SAMPLES, BimaRadar


def test_finds_all_five_covers(by_type):
    assert set(by_type) == {"pmsby", "pmjjby", "rupay_pmjdy", "loan_protection", "irctc_travel"}


def test_same_cover_from_two_sources_is_merged(by_type):
    refs = {e.ref for e in by_type["pmsby"].evidence}
    assert refs == {"sms:s101", "aa:XX4821:T2506010001"}


def test_loan_protection_reads_outstanding_not_premium(by_type):
    loan = by_type["loan_protection"]
    assert loan.attrs["outstanding"] == 41_200
    assert loan.attrs["premium"] == 2_450
    assert loan.attrs["loan_no"] == "TW-88213"
    assert loan.attrs["lender"] == "GANGA TWO-WHEELER FINANCE LTD"


def test_rupay_amount_follows_account_opening_date(by_type):
    rupay = by_type["rupay_pmjdy"]
    assert rupay.attrs["card_last4"] == "4821"
    assert rupay.sum_insured == 200_000  # opened 2019, after 28 Aug 2018


def test_consent_controls_what_is_read(tmp_path):
    folder = tmp_path / "suresh"
    shutil.copytree(SAMPLES / "suresh", folder)
    consent = json.loads((folder / "consent.json").read_text(encoding="utf-8"))
    consent["sources"]["documents"] = False
    (folder / "consent.json").write_text(json.dumps(consent), encoding="utf-8")
    radar = BimaRadar(":memory:")
    report = radar.scan(folder)
    assert "loan_protection" not in {c.type for c in radar.covers()}
    assert any(s["source"] == "documents" and s["status"].startswith("skipped") for s in report["sources"])


def test_pasted_sms_is_recognised_by_rules():
    covers = find_covers([Record("sms", "x", "Rs 436.00 debited from A/c XX7710 towards PMJJBY renewal on 25-May-2026.")])
    assert [c.type for c in covers] == ["pmjjby"]
    assert covers[0].attrs["account"] == "XX7710"


class FakeClient:
    """Stands in for anthropic.Anthropic so the guard logic can be tested offline."""

    def __init__(self, payload, stop_reason="end_turn"):
        self.calls = []
        text = json.dumps(payload)
        create = lambda **kw: self.calls.append(kw) or SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


def _item(**over):
    base = {"type": "loan_protection", "name": "Credit Shield", "sum_insured_inr": 150000, "what_it_pays": "Pays the loan",
            "conditions": [], "evidence_quote": "Credit Shield insurance premium Rs 3,150", "confidence": "high"}
    return {**base, **over}


TEXT = "Your personal loan of Rs 1,50,000 is disbursed. Charges: Credit Shield insurance premium Rs 3,150 (sum assured Rs 1,50,000)."


def test_llm_keeps_only_quoted_evidence():
    client = FakeClient({"covers": [_item(), _item(name="Invented", evidence_quote="free health cover of Rs 5 lakh")]})
    covers = llm_finder.extract(TEXT, client=client)
    assert [c.name for c in covers] == ["Credit Shield"]
    assert covers[0].found_by == "llm"
    assert covers[0].sum_insured == 150_000  # stated in the text


def test_llm_amount_must_appear_in_text():
    client = FakeClient({"covers": [_item(sum_insured_inr=900000)]})
    assert llm_finder.extract(TEXT, client=client)[0].sum_insured is None


def test_llm_request_shape():
    client = FakeClient({"covers": []})
    llm_finder.extract(TEXT, client=client)
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"


def test_llm_refusal_returns_nothing():
    client = FakeClient({"covers": [_item()]}, stop_reason="refusal")
    assert llm_finder.extract(TEXT, client=client) == []
