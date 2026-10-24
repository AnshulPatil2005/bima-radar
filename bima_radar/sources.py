"""Stage 1 · Ingestion. Each adapter turns one consented source into Records.

Only sources switched on in consent.json are read. In the full build these become live
connectors (on-device SMS reader, Account Aggregator FIU, DigiLocker, Paytm payments);
here they read the same shapes from files.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from bima_radar.models import Record

SOURCE_NAMES = {
    "sms": "Bank SMS (read on the phone)",
    "aa": "Account Aggregator statement",
    "documents": "Loan and policy papers",
    "payments": "Paytm payments",
}


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return date.fromisoformat(value[:10])


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_consent(folder: Path) -> dict:
    path = folder / "consent.json"
    if not path.exists():
        raise FileNotFoundError(f"No consent.json in {folder}. Bima Radar reads nothing without consent.")
    return load_json(path)


def load_profile(folder: Path) -> dict:
    path = folder / "profile.json"
    return load_json(path) if path.exists() else {}


def read_sms(path: Path) -> list[Record]:
    """An SMS export: [{id, sender, received_at, body}]. On a phone this runs on-device."""
    out = []
    for m in load_json(path):
        out.append(Record("sms", f"sms:{m['id']}", m["body"].strip(), _date(m.get("received_at")), {"sender": m.get("sender", "")}))
    return out


def read_aa(path: Path) -> list[Record]:
    """Account Aggregator FI data for a deposit account (simplified ReBIT layout)."""
    fi = load_json(path)
    acct = fi["account"]
    masked = "XX" + acct["maskedAccNumber"][-4:]
    summary = acct.get("summary", {})
    out = [
        Record(
            "aa",
            f"aa:{masked}:summary",
            f"Account {masked} · {summary.get('type', '').title()} · scheme {summary.get('x_scheme', 'n/a')} · "
            f"opened {summary.get('openingDate', '?')} · balance Rs {summary.get('currentBalance', '?')}",
            _date(summary.get("balanceDateTime")),
            {
                "kind": "account",
                "account": masked,
                "scheme": summary.get("x_scheme"),
                "opened": summary.get("openingDate"),
                "balance": float(summary.get("currentBalance", 0) or 0),
                "ifsc": summary.get("ifscCode"),
                "branch": summary.get("branch"),
            },
        )
    ]
    for t in acct.get("transactions", {}).get("transaction", []):
        out.append(
            Record(
                "aa",
                f"aa:{masked}:{t['txnId']}",
                f"{t.get('valueDate')} {t['type']} Rs {t['amount']} {t.get('narration', '')}".strip(),
                _date(t.get("valueDate") or t.get("transactionTimestamp")),
                {
                    "kind": "txn",
                    "account": masked,
                    "type": t["type"],
                    "mode": t.get("mode", "OTHERS"),
                    "amount": float(t["amount"]),
                    "balance": float(t.get("currentBalance", 0) or 0),
                    "narration": t.get("narration", ""),
                },
            )
        )
    return out


def _document_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:  # pragma: no cover - optional dependency
            raise RuntimeError("Reading PDFs needs the 'pdf' extra: pip install bima-radar[pdf]") from e
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8")


def read_documents(folder: Path) -> list[Record]:
    """Loan and policy papers. One Record per non-empty line, plus the whole document for context."""
    out = []
    for path in sorted(folder.glob("*")):
        if path.suffix.lower() not in {".txt", ".pdf"}:
            continue
        text = _document_text(path)
        out.append(Record("document", f"doc:{path.name}", text, None, {"kind": "document", "file": path.name}))
    return out


def read_payments(path: Path) -> list[Record]:
    """Paytm payment history: [{id, at, type, merchant, mcc, amount, meta}]."""
    out = []
    for p in load_json(path):
        text = f"{p['at'][:10]} {p['type']} Rs {p['amount']:.2f} {p['merchant']}"
        meta = p.get("meta", {})
        if p["type"] == "train_booking":
            text += f" PNR {meta.get('pnr')} {meta.get('from')}->{meta.get('to')} on {meta.get('journey_date')}"
            if meta.get("travel_insurance"):
                text += f" · travel insurance opted (Rs {meta.get('insurance_premium')})"
        out.append(Record("payments", f"pay:{p['id']}", text, _date(p["at"]), {**p, "meta": meta}))
    return out


def ingest(folder: Path, consent: dict) -> tuple[list[Record], list[dict]]:
    """Read every source the consent allows. Returns the records and a log of what was read or skipped."""
    allowed = consent.get("sources", {})
    plan = [
        ("sms", folder / "sms.json", read_sms),
        ("aa", folder / "aa_fi_data.json", read_aa),
        ("documents", folder / "documents", read_documents),
        ("payments", folder / "paytm_payments.json", read_payments),
    ]
    records: list[Record] = []
    log = []
    for key, path, reader in plan:
        if not allowed.get(key):
            log.append({"source": key, "name": SOURCE_NAMES[key], "status": "skipped: no consent", "records": 0})
            continue
        if not path.exists():
            log.append({"source": key, "name": SOURCE_NAMES[key], "status": "not provided", "records": 0})
            continue
        got = reader(path)
        records.extend(got)
        log.append({"source": key, "name": SOURCE_NAMES[key], "status": "read", "records": len(got)})
    return records, log


ACCOUNT_RE = re.compile(r"A/c\s*(?:No\.?\s*)?(?:X+|\*+)?(\d{4})", re.I)


def account_in(text: str) -> str | None:
    m = ACCOUNT_RE.search(text)
    return f"XX{m.group(1)}" if m else None
