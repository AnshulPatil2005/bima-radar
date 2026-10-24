import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bima_radar import api  # noqa: E402
from bima_radar.pipeline import BimaRadar  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "radar", BimaRadar(":memory:"))
    return TestClient(api.app)


def test_scan_then_claims(client):
    r = client.post("/scan", json={"sample": "suresh"})
    assert r.status_code == 200 and len(r.json()["covers"]) == 5
    assert len(client.get("/alerts").json()) == 3
    assert len(client.get("/alerts", params={"card_days": 5, "balance": 1000}).json()) == 1

    ev = client.post("/events", json={"type": "death", "cause": "accident"}).json()
    m = client.get(f"/events/{ev['id']}/match").json()
    assert m["to_family"] == 600_000 and m["to_lender"] == 41_200
    pack = client.get(f"/events/{ev['id']}/claims").json()
    assert len(pack["claims"]) == 4
    fam = client.get(f"/events/{ev['id']}/family", params={"lang": "hi"}).json()
    assert "₹6 लाख" in fam["messages"][1]


def test_unknown_sample_is_rejected(client):
    assert client.post("/scan", json={"sample": "../etc"}).status_code == 404


def test_find_with_rules(client):
    r = client.post("/find", json={"text": "Rs 20.00 debited from A/c XX1111 for PMSBY on 01-Jun-25"}).json()
    assert r["read_by"] == "rules" and r["covers"][0]["type"] == "pmsby"
