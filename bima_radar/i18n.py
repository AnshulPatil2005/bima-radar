"""Family mode messages in Hindi and English, built only from the matcher's results."""

from __future__ import annotations

from datetime import date

from bima_radar.claims import ClaimPack
from bima_radar.context import Context
from bima_radar.fmt import inr, lakh, nice_date
from bima_radar.matcher import MatchResult
from bima_radar.models import Cover

SHORT = {
    "en": {"rupay_pmjdy": "RuPay card cover", "pmsby": "PMSBY", "pmjjby": "PMJJBY", "loan_protection": "Loan protection", "irctc_travel": "Train cover", "other": "Other cover"},
    "hi": {"rupay_pmjdy": "RuPay कार्ड बीमा", "pmsby": "PMSBY", "pmjjby": "PMJJBY", "loan_protection": "लोन बीमा", "irctc_travel": "रेल यात्रा बीमा", "other": "अन्य बीमा"},
}
PAPERS_HI = {
    "death_certificate": "मृत्यु प्रमाण पत्र", "fir": "FIR", "post_mortem": "पोस्टमार्टम रिपोर्ट", "claimant_kyc": "आपका आधार और PAN",
    "bank_proof": "पासबुक", "hospital_bills": "अस्पताल के बिल", "discharge_summary": "डिस्चार्ज समरी", "insured_kyc": "आधार और PAN",
}


def family_message(result: MatchResult, pack: ClaimPack, covers: list[Cover], ctx: Context, lang: str = "hi") -> list[str]:
    """The first replies the nominee sees, in order. Every number comes from the rules engine."""
    hi = lang == "hi"
    names = SHORT["hi" if hi else "en"]
    kind = {c.id: c.type for c in covers}
    name_key = "name_hi" if hi else "name"
    nominee = (ctx.nominee.get(name_key) or ctx.nominee.get("name") or "").split(" ")[0]
    insured = (ctx.person.get(name_key) or ctx.person.get("name") or "").split(" ")[0]
    paying = result.paying
    deadlines = sorted((date.fromisoformat(c.deadline), names[kind[c.cover_id]]) for c in pack.claims if c.deadline)
    to_collect = [p for p in pack.papers if not p["auto"]]

    def amount(v) -> str:
        if v.payee == "lender":
            return inr(v.amount) + (" लोन के लिए" if hi else " to the lender")
        return lakh(v.amount, lang)

    if hi:
        out = [f"{nominee} जी, मुझे बहुत दुख है। हम यह साथ में, एक-एक कदम करेंगे।"]
        if not paying:
            return out + [f"{insured} जी के नाम पर ऐसा कोई बीमा नहीं मिला जो इसके लिए पैसा दे।"]
        loan = ", और बाइक लोन भी बंद हो जाएगा" if result.to_lender else ""
        out.append(f"{insured} जी के नाम पर {len(paying)} बीमा हैं जो पैसा देंगे। इनसे आपको लगभग {lakh(result.to_family, 'hi')} मिल सकते हैं{loan}।")
        out.append("; ".join(f"{names[kind[v.cover_id]]}: {amount(v)}" for v in paying))
        if deadlines:
            out.append("ज़रूरी तारीखें: " + "; ".join(f"{n} — {nice_date(d, 'hi')} तक" for d, n in deadlines))
        out.append("ये कागज़ एक बार इकट्ठा कर लें: " + ", ".join(PAPERS_HI.get(p["key"], p["label"]) for p in to_collect)
                   + f"। मैंने सभी {len(pack.claims)} क्लेम फ़ॉर्म भर दिए हैं।")
        return out

    out = [f"I'm so sorry, {nominee}. We will do this together, one step at a time."]
    if not paying:
        return out + [f"I could not find any cover in {insured}'s name that pays for this."]
    loan = ", and close his bike loan" if result.to_lender else ""
    out.append(f"{insured} had {len(paying)} covers that pay. Together they can give you about {lakh(result.to_family)}{loan}.")
    out.append("; ".join(f"{names[kind[v.cover_id]]}: {amount(v)}" for v in paying))
    if deadlines:
        out.append("Dates that matter: " + "; ".join(f"{n} by {nice_date(d)}" for d, n in deadlines))
    out.append("Collect these papers once: " + ", ".join(p["label"] for p in to_collect) + f". I have filled all {len(pack.claims)} claim forms.")
    return out
