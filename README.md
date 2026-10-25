# Bima Radar

Bima Radar finds the insurance a person already has but doesn't know about, warns before it quietly
lapses, and when something happens, checks the event against every cover at once and prepares the
family's claims.

This repository is the working first slice of the pipeline pitched for the Paytm Hackathon
(Track 2, AI-Powered Financial Journeys). It runs end to end on a sample family today; the next stage
is turning each stage into the production service described under [Full build](#full-build).

## Run it

```bash
python -m bima_radar demo            # no dependencies needed
python -m pytest                     # 27 tests
```

Python 3.11 or newer. The core pipeline uses only the standard library. Optional extras:

```bash
pip install -e ".[api]"    # FastAPI server: python -m bima_radar serve
pip install -e ".[pdf]"    # read PDF loan and policy papers
pip install -e ".[dev]"    # tests
```

The AI step calls Gemini over plain HTTPS, so it needs no extra package, only a key from Google AI Studio:

```bash
cp .env.example .env       # then paste your key after GEMINI_API_KEY=
```

`.env` is git-ignored. `GEMINI_MODEL` picks another model (default `gemini-3.5-flash`).

## The pipeline

```
 consented data            Cover Finder              Cover Map            rules engine                Claim Builder
 ───────────────          ─────────────            ───────────          ─────────────               ──────────────
 bank SMS (on phone)  ─┐   rules for PMSBY,         one record per      status: is it working?      one claim per paying cover
 AA statement         ─┼─▶ PMJJBY, RuPay PMJDY, ─▶  cover, with the  ─▶ lapse guard: warn before ─▶ forms filled from the map
 loan / policy papers ─┤   loan protection,         line it came        it stops                    one merged list of papers
 Paytm payments       ─┘   train travel cover;      from (SQLite)       matcher: one event against  deadlines, tracking
                           Gemini for the rest                          every cover, with reasons   Hindi / English messages
                                                         ▲
                               Event Watcher ────────────┘
                               hospital bills from payments, deaths and accidents reported by the family
```

| Stage | Module | What it does now |
|---|---|---|
| Ingestion | `sources.py` | Reads only the sources switched on in `consent.json`: an SMS export, Account Aggregator FI data (simplified ReBIT deposit layout), loan papers (.txt or .pdf), a Paytm payments export. |
| Cover Finder | `finder.py`, `llm_finder.py` | Rules recognise five bundled covers and merge evidence for the same cover across sources. Anything mentioning insurance that the rules can't explain can go to Gemini (`gemini-3.5-flash`, JSON-schema output). Gemini's answer is kept only if its quoted evidence appears in the text, and amounts for known schemes always come from `schemes.py`. |
| Cover Map | `store.py`, `context.py` | Covers, events and claim packs in SQLite. Context holds the facts the rules need: last qualifying card use, balances, the nominee. |
| Rules engine | `rules.py`, `schemes.py` | Per-cover rules: RuPay needs a card payment within 90 days before an accident; PMSBY/PMJJBY need this cover year's premium and money for the 31 May renewal; train cover applies only to its own journey; loan protection pays the lender what is left. |
| Event Watcher | `watcher.py` | Hospital payments (MCC 8062 and others) become events; deaths and accidents are reported. |
| Matcher, lapse guard | `matcher.py` | Checks one event against every cover and totals what goes to the family and to the lender; raises lapse alerts. |
| Claim Builder | `claims.py`, `i18n.py` | One claim per paying cover with the route, form, filled fields and deadline; one merged papers list (papers already on file are ticked); the nominee's first messages in Hindi or English. |
| Interfaces | `cli.py`, `api.py` | `bima-radar demo / scan / covers / alerts / event / claims / family / find / serve`, and the same over HTTP. |

**AI explains, rules decide.** The language model reads messy text. Whether a cover pays is decided by
explicit rules, and every yes or no carries its reason.

## What the demo shows

The sample family (in `samples/suresh/`, all invented): Suresh, 34, a delivery rider in Lucknow, and his
wife Sunita. Output from `python -m bima_radar demo`, shortened:

```
2  Cover Map · 5 covers found
   WARN  PMSBY accident cover            ₹2 lakh   Renews 31 May 2026 · balance too low
         found in: sms:s101, aa:XX4821:T2506010001
   WARN  PMJJBY life cover               ₹2 lakh   Renews 31 May 2026 · balance too low
   ok    Bike-loan protection            ₹41,200   Active · ₹41,200 left on the loan
   WARN  Train travel cover             ₹10 lakh   No nominee added
   WARN  RuPay card accident cover       ₹2 lakh   Use the card within 20 days to keep it on

4  Event Watcher and matcher · one event, every cover
   From payments: hospitalisation (illness) on 26 May 2026 · bill ₹38,000
      = nothing pays. Bima Radar says so instead of guessing.

   Reported: death (accident) on 28 May 2026
      PMSBY accident cover         PAYS ₹2 lakh           Accidental death, and this cover year's ₹20 premium was paid.
      PMJJBY life cover            PAYS ₹2 lakh           Death from any cause, and this cover year's ₹436 premium was paid.
      Bike-loan protection         PAYS ₹41,200 to lender Pays the lender what is left, so the family stops paying EMIs.
      Train travel cover           no                     Covers only accidents on the LKO to NDLS journey (PNR 4217730954).
      RuPay card accident cover    PAYS ₹2 lakh           Accident, and the card was used 70 days before it (90 or fewer).
      = ₹6 lakh to the family, ₹41,200 to the lender

   Same event if the card had sat unused for 95 days
      RuPay card accident cover    no                     Card last used 95 days before the accident; the rule needs 90 or fewer.
      = ₹4 lakh to the family, ₹41,200 to the lender

6  Family mode · what the nominee reads first (Hindi)
   सुनीता जी, मुझे बहुत दुख है। हम यह साथ में, एक-एक कदम करेंगे।
   सुरेश जी के नाम पर 4 बीमा हैं जो पैसा देंगे। इनसे आपको लगभग ₹6 लाख मिल सकते हैं, और बाइक लोन भी बंद हो जाएगा।
```

Try the what-ifs yourself:

```bash
python -m bima_radar scan samples/suresh
python -m bima_radar alerts --card-days 95 --balance 120
python -m bima_radar event death --cause accident --card-days 95
python -m bima_radar find "Rs 436.00 debited from A/c XX7710 towards PMJJBY renewal" 
python -m bima_radar find "<any SMS or loan paragraph>" --llm     # needs GEMINI_API_KEY
```

A live run of the AI step on a message the rules have no pattern for:

```
$ python -m bima_radar find "Dear Customer, Rs 3,150 has been debited from your loan a/c PL-55120 towards
  Credit Shield insurance premium. Sum assured Rs 1,50,000 covers your outstanding loan in case of death.
  -SAMPLE BANK" --llm
Read by: gemini
- Credit Shield Insurance (Loan) · ₹1.5 lakh · high confidence
  evidence: "Rs 3,150 has been debited from your loan a/c PL-55120 towards Credit Shield insurance premium.
  Sum assured Rs 1,50,000 covers your outstanding loan in case of death."
  pays: Pays your remaining loan amount if you die.
```

## Status of each part

- Rules, matcher, lapse guard, claim builder, Hindi/English messages, CLI and API: working, covered by tests.
- Gemini extraction: runs against the live Gemini API, and is unit-tested offline against a stand-in
  (request shape, evidence guard, amount guard, blocked answers, missing key). A busy model is retried
  twice; without a key or a connection the pipeline falls back to rules and says so.
- Scheme numbers in `schemes.py` are a simplified reading of the public rules and must be re-checked
  against current notifications before any real use.

## Full build

What the next stage adds to each part of this slice:

| Stage | This repository | Full build |
|---|---|---|
| Ingestion | Files in the real formats | Account Aggregator FIU integration, on-device SMS reader in the Paytm app, DigiLocker pull, live Paytm payment stream (Kafka) |
| Cover Finder | Rules for 5 covers, Gemini for the rest | Employer group health, credit-card air accident, LPG cover; per-bank card-use rules; evaluation set of real (consented, redacted) messages |
| Cover Map | SQLite | PostgreSQL, encryption at rest, consent ledger under the DPDP Act 2023, delete on request |
| Rules engine | Simplified scheme rules | Rules versioned against scheme notifications, with tests per rule change |
| Event Watcher | MCC rules and reported events | Streaming detection, trusted-contact flows for family mode |
| Claim Builder | Claim pack as JSON / Markdown | Real insurer and bank claim forms, submission where APIs exist, status tracking, Bima Sugam once its claims phase is live |
| Language | Hindi and English templates | Voice and more Indian languages through Bhashini or Sarvam AI |

## Layout

```
bima_radar/   pipeline code (one module per stage)
samples/      synthetic consented data for one family
tests/        27 tests across finder, rules, matcher, claims, API
```
