"""Indian number and date formatting, in English and Hindi."""

from __future__ import annotations

from datetime import date

HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]


def _group(digits: str) -> str:
    """12345678 -> 1,23,45,678 (Indian grouping)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def inr(n: float | int | None) -> str:
    if n is None:
        return "₹?"
    n = round(float(n), 2)
    whole = int(abs(n))
    paise = round(abs(n) - whole, 2)
    s = "₹" + _group(str(whole)) + (f"{paise:.2f}"[1:] if paise else "")
    return "-" + s if n < 0 else s


def lakh(n: int | None, lang: str = "en") -> str:
    if n is None:
        return "amount not stated"
    word = "लाख" if lang == "hi" else "lakh"
    if n >= 100_000 and n % 10_000 == 0:
        value = n / 100_000
        text = f"{value:.1f}".rstrip("0").rstrip(".")
        return f"₹{text} {word}"
    return inr(n)


def nice_date(d: date | None, lang: str = "en") -> str:
    if d is None:
        return "?"
    if lang == "hi":
        return f"{d.day} {HI_MONTHS[d.month - 1]} {d.year}"
    return f"{d.day} {d.strftime('%b')} {d.year}"
