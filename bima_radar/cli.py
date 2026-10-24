"""Command line for the pipeline. `python -m bima_radar demo` runs every stage on the sample family."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from bima_radar.claims import render_markdown
from bima_radar.fmt import inr, lakh, nice_date
from bima_radar.matcher import MatchResult
from bima_radar.pipeline import SAMPLES, BimaRadar

MARK = {"ok": "ok  ", "warn": "WARN", "risk": "OFF ", "info": "info"}
DEFAULT_DB = os.environ.get("BIMA_RADAR_DB", "bima_radar.db")


def _out(line: str = ""):
    print(line)


def _amount(c) -> str:
    if c.type == "loan_protection":
        return inr(c.sum_insured) if c.sum_insured else "loan"
    return lakh(c.sum_insured)


def print_scan(report: dict, folder: Path):
    _out(f"Bima Radar · scan of {folder.name} · as of {nice_date(report['today'])}")
    _out()
    _out("1  Sources read with consent")
    for s in report["sources"]:
        _out(f"   {s['status']:<20} {s['name']:<32} {s['records']:>3} records")
    if report["llm"]:
        for line in report["llm"]:
            _out(f"   claude: {line}")


def print_map(radar: BimaRadar, **what_if):
    rows = radar.cover_map(**what_if)
    _out()
    _out(f"2  Cover Map · {len(rows)} covers found")
    for cover, status in rows:
        _out(f"   {MARK[status.level]}  {cover.name:<28} {_amount(cover):>10}   {status.text}")
        refs = ", ".join(e.ref for e in cover.evidence)
        _out(f"         found in: {refs}")


def print_alerts(radar: BimaRadar, **what_if):
    alerts = radar.alerts(**what_if)
    _out()
    _out(f"3  Lapse guard · {len(alerts)} alert{'s' if len(alerts) != 1 else ''}")
    for a in alerts:
        _out(f"   [{a.level.upper()}] {a.title}")
        _out(f"          {a.body}")
        _out(f"          -> {a.action}")


def print_match(result: MatchResult, title: str):
    ev = result.event
    _out()
    _out(f"   {title}: {ev.type} ({ev.cause}) on {nice_date(ev.date)}" + (f" · bill {inr(ev.bill)}" if ev.bill else "")
         + (f" · {ev.note}" if ev.note else ""))
    for v in result.verdicts:
        verdict = ("PAYS " + (inr(v.amount) + " to lender" if v.payee == "lender" else lakh(v.amount))) if v.pays else (
            "check terms" if v.pays is None else "no")
        _out(f"      {v.cover_name:<28} {verdict:<22} {v.reasons[0] if v.reasons else ''}")
    if result.paying:
        _out(f"      = {lakh(result.to_family)} to the family" + (f", {inr(result.to_lender)} to the lender" if result.to_lender else ""))
    else:
        _out("      = nothing pays. Bima Radar says so instead of guessing.")


def cmd_demo(args) -> int:
    folder = Path(args.path) if args.path else SAMPLES / "suresh"
    radar = BimaRadar(":memory:")
    report = radar.scan(folder, use_llm=args.llm)
    print_scan(report, folder)
    print_map(radar)
    print_alerts(radar)

    _out()
    _out("4  Event Watcher and matcher · one event, every cover")
    for ev in report["events"]:
        print_match(radar.match(ev.id), "From payments")
    death = radar.report("death", "accident", report["today"], note="reported by the nominee")
    result = radar.match(death.id)
    print_match(result, "Reported")
    print_match(radar.match(death.id, card_days=95), "Same event if the card had sat unused for 95 days")

    pack = radar.claim_pack(death.id)
    _out()
    _out(f"5  Claim Builder · {len(pack.claims)} claims, one list of papers")
    for p in pack.papers:
        tick = "have" if p["auto"] else "need"
        _out(f"   [{tick}] {p['label']:<34} for {len(p['needed_by'])} claim{'s' if len(p['needed_by']) > 1 else ''}"
             + (f" · on file from {p['auto']}" if p["auto"] else ""))
    for c in pack.claims:
        _out(f"   {c.cover_name:<28} {inr(c.amount):>12}  -> {c.send_to}" + (f" · {c.deadline_label} {c.deadline}" if c.deadline else ""))

    _out()
    _out("6  Family mode · what the nominee reads first (Hindi)")
    for line in radar.family(death.id, "hi"):
        _out(f"   {line}")

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "claim_pack.md").write_text(render_markdown(pack), encoding="utf-8")
        _out()
        _out(f"Claim pack written to {out / 'claim_pack.md'}")
    return 0


def cmd_scan(args) -> int:
    radar = BimaRadar(args.db)
    folder = Path(args.path)
    report = radar.scan(folder, today=date.fromisoformat(args.today) if args.today else None, use_llm=args.llm)
    print_scan(report, folder)
    print_map(radar)
    for ev in report["events"]:
        _out(f"   event from payments: {ev.id} · {ev.type} on {nice_date(ev.date)} · {ev.note}")
    return 0


def _what_if(args) -> dict:
    return {k: v for k, v in {"card_days": getattr(args, "card_days", None), "balance": getattr(args, "balance", None)}.items() if v is not None}


def cmd_covers(args) -> int:
    print_map(BimaRadar(args.db), **_what_if(args))
    return 0


def cmd_alerts(args) -> int:
    print_alerts(BimaRadar(args.db), **_what_if(args))
    return 0


def cmd_event(args) -> int:
    radar = BimaRadar(args.db)
    when = date.fromisoformat(args.date) if args.date else radar.context().today
    ev = radar.report(args.type, args.cause, when, bill=args.bill, pnr=args.pnr)
    _out(f"Event {ev.id}")
    print_match(radar.match(ev.id, **_what_if(args)), "Reported")
    return 0


def cmd_claims(args) -> int:
    radar = BimaRadar(args.db)
    pack = radar.claim_pack(args.event_id, **_what_if(args))
    md = render_markdown(pack)
    if args.md:
        Path(args.md).write_text(md, encoding="utf-8")
        _out(f"Wrote {args.md}")
    else:
        _out(md)
    return 0


def cmd_family(args) -> int:
    for line in BimaRadar(args.db).family(args.event_id, args.lang, **_what_if(args)):
        _out(line)
    return 0


def cmd_find(args) -> int:
    radar = BimaRadar(args.db)
    covers, how = radar.find_in_text(args.text, use_llm=args.llm, save=args.save)
    _out(f"Read by: {how}")
    if not covers:
        _out("No cover found in this text." + ("" if args.llm else " Try --llm to ask Claude."))
    for c in covers:
        _out(f"- {c.name} ({c.kind}) · {lakh(c.sum_insured) if c.sum_insured else 'amount not stated'} · {c.confidence} confidence")
        _out(f"  evidence: \"{c.evidence[0].quote}\"")
        if c.attrs.get("what_it_pays"):
            _out(f"  pays: {c.attrs['what_it_pays']}")
    return 0


def cmd_serve(args) -> int:
    try:
        import uvicorn
    except ImportError:
        _out("The API needs the 'api' extra: pip install bima-radar[api]")
        return 1
    os.environ["BIMA_RADAR_DB"] = args.db
    uvicorn.run("bima_radar.api:app", host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bima-radar", description="Find hidden insurance cover, keep it alive, prepare claims.")
    p.add_argument("--db", default=DEFAULT_DB, help="SQLite file for the Cover Map (default: %(default)s)")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="run every stage on the sample family")
    d.add_argument("path", nargs="?", help="sample folder (default: samples/suresh)")
    d.add_argument("--llm", action="store_true", help="also send unexplained records to Claude")
    d.add_argument("--out", help="folder to write the claim pack into")
    d.set_defaults(fn=cmd_demo)

    s = sub.add_parser("scan", help="read a folder of consented data and build the Cover Map")
    s.add_argument("path")
    s.add_argument("--today", help="pretend today is this date (YYYY-MM-DD)")
    s.add_argument("--llm", action="store_true")
    s.set_defaults(fn=cmd_scan)

    for name, fn, help_ in [("covers", cmd_covers, "show the Cover Map"), ("alerts", cmd_alerts, "show lapse warnings")]:
        x = sub.add_parser(name, help=help_)
        x.add_argument("--card-days", type=int, help="what if the RuPay card was last used this many days ago")
        x.add_argument("--balance", type=float, help="what if the account balance were this")
        x.set_defaults(fn=fn)

    e = sub.add_parser("event", help="report a life event and check it against every cover")
    e.add_argument("type", choices=["death", "hospitalisation"])
    e.add_argument("--cause", choices=["accident", "illness"], default="accident")
    e.add_argument("--date")
    e.add_argument("--bill", type=int)
    e.add_argument("--pnr", help="set when it happened on an insured train journey")
    e.add_argument("--card-days", type=int)
    e.set_defaults(fn=cmd_event)

    c = sub.add_parser("claims", help="build the claim pack for an event")
    c.add_argument("event_id")
    c.add_argument("--md", help="write Markdown here instead of printing")
    c.set_defaults(fn=cmd_claims)

    f = sub.add_parser("family", help="the nominee's first messages, in Hindi or English")
    f.add_argument("event_id")
    f.add_argument("--lang", choices=["hi", "en"], default="hi")
    f.set_defaults(fn=cmd_family)

    t = sub.add_parser("find", help="find cover in a pasted SMS or document text")
    t.add_argument("text")
    t.add_argument("--llm", action="store_true", help="ask Claude")
    t.add_argument("--save", action="store_true", help="add what is found to the Cover Map")
    t.set_defaults(fn=cmd_find)

    v = sub.add_parser("serve", help="run the HTTP API")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.set_defaults(fn=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
