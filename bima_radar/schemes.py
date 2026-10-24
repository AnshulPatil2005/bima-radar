"""Public scheme rules, kept in one place so the rules engine never hard-codes a number.

Simplified for the prototype. Every value here must be re-checked against the current
scheme notification before production use.
"""

from datetime import date

# Pradhan Mantri Suraksha Bima Yojana: accident cover, auto-debited yearly.
PMSBY = {
    "premium": 20,
    "accidental_death": 200_000,
    "total_disability": 200_000,
    "partial_disability": 100_000,
    "age_range": (18, 70),
    "claim_window_days": 30,  # claim procedure asks for filing within 30 days; later needs a reason
}

# Pradhan Mantri Jeevan Jyoti Bima Yojana: life cover for death from any cause.
PMJJBY = {
    "premium": 436,
    "death": 200_000,
    "entry_age_range": (18, 50),
    "lien_days": 30,  # non-accidental death in the first 30 days after enrolment is not covered
    "claim_window_days": 30,
}

# Both schemes run from 1 June to 31 May; the premium is auto-debited around renewal.
COVER_YEAR_START_MONTH = 6
RENEWAL_REMINDER_DAYS = 30

# Accident cover on RuPay debit cards issued with Jan Dhan (PMJDY) accounts.
RUPAY_PMJDY = {
    "cover_new": 200_000,  # accounts opened after 28 Aug 2018
    "cover_old": 100_000,
    "new_cover_from": date(2018, 8, 28),
    "card_use_window_days": 90,  # one successful card transaction within 90 days before the accident
    "intimation_days": 90,  # tell the bank within 90 days of the accident
    "warn_from_days": 60,
}

# Which statement modes count as using the card. Banks differ (some count ATM, some only POS/e-com);
# the full build loads this per issuing bank.
CARD_ACTIVITY_MODES = {"CARD", "POS", "ECOM"}

# Optional travel insurance on IRCTC e-tickets (45 paise), valid only for that journey.
IRCTC_TRAVEL = {
    "premium": 0.45,
    "death": 1_000_000,
    "total_disability": 1_000_000,
    "partial_disability_max": 750_000,
    "hospitalisation_max": 200_000,
}

# Merchant category codes the Event Watcher treats as health spending.
HEALTH_MCC = {"8062": "hospital", "8011": "doctor", "8099": "medical service", "5912": "pharmacy"}
