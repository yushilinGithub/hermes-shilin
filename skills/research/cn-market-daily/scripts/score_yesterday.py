#!/usr/bin/env python3
"""Self-scoring log for the cn-market-daily agent (Phase 2).

The whole point of a daily market agent is that it *grades itself* — a forecast
nobody scores is astrology. This keeps a JSONL ledger of directional calls and
their outcomes, so the agent (and you) can see a real hit-rate over time and the
background-review loop can fold recurring misses back into the playbooks.

Ledger: $HERMES_HOME/cn-market-daily/calls.jsonl (HERMES_HOME defaults to ~/.hermes).
Each line is one record: a 'prediction' (written at pre-market) or a 'result'
(written at post-close after grading the matching prediction).

Workflow:
  # end of pre-market brief — record the directional lean per index
  score_yesterday.py record --date 2026-06-24 \
      --lean '{"CSI300":"down","CSI1000":"down","ChiNext":"down"}' \
      --note "imported US tech selloff; A50 -2.7% overnight"

  # post-close — grade that day against actual index % moves
  score_yesterday.py score --date 2026-06-24 \
      --actual '{"CSI300":-2.77,"CSI1000":-2.09,"ChiNext":-3.83}'

  # any time — running accuracy
  score_yesterday.py stats
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

FLAT_BAND = 0.3  # |move%| <= this counts as "flat"


def ledger_path() -> Path:
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    p = Path(home) / "cn-market-daily"
    p.mkdir(parents=True, exist_ok=True)
    return p / "calls.jsonl"


def _read() -> List[Dict[str, Any]]:
    fp = ledger_path()
    if not fp.exists():
        return []
    out = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append(rec: Dict[str, Any]) -> None:
    with ledger_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _sign(pct: float) -> str:
    if pct > FLAT_BAND:
        return "up"
    if pct < -FLAT_BAND:
        return "down"
    return "flat"


def cmd_record(args: argparse.Namespace) -> int:
    lean = json.loads(args.lean)
    _append({
        "type": "prediction",
        "date": args.date,
        "lean": lean,
        "note": args.note or "",
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
    })
    print(f"recorded prediction for {args.date}: {lean}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    actual = {k: float(v) for k, v in json.loads(args.actual).items()}
    # find the most recent unscored prediction for this date
    records = _read()
    pred: Optional[Dict[str, Any]] = None
    for rec in reversed(records):
        if rec.get("type") == "prediction" and rec.get("date") == args.date:
            pred = rec
            break
    if pred is None:
        print(f"no prediction found for {args.date} — nothing to score")
        return 1

    graded: Dict[str, Any] = {}
    hits = 0
    total = 0
    for idx, called in pred["lean"].items():
        if idx not in actual:
            continue
        total += 1
        got = _sign(actual[idx])
        ok = (called == got)
        hits += int(ok)
        graded[idx] = {"called": called, "actual_pct": actual[idx], "got": got, "hit": ok}

    acc = round(hits / total * 100, 1) if total else None
    _append({
        "type": "result",
        "date": args.date,
        "graded": graded,
        "hits": hits,
        "total": total,
        "accuracy_pct": acc,
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
    })
    print(f"scored {args.date}: {hits}/{total} correct ({acc}%)")
    for idx, g in graded.items():
        mark = "✓" if g["hit"] else "✗"
        print(f"  {mark} {idx:<8} called {g['called']:<5} actual {g['actual_pct']:+.2f}% ({g['got']})")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    results = [r for r in _read() if r.get("type") == "result"]
    if not results:
        print("no scored days yet")
        return 0
    n = min(args.last, len(results)) if args.last else len(results)
    window = results[-n:]
    hits = sum(r["hits"] for r in window)
    total = sum(r["total"] for r in window)
    acc = round(hits / total * 100, 1) if total else 0.0
    # per-index breakdown
    per: Dict[str, List[int]] = {}
    for r in window:
        for idx, g in r.get("graded", {}).items():
            per.setdefault(idx, [0, 0])
            per[idx][0] += int(g["hit"])
            per[idx][1] += 1
    print(f"hit-rate over last {len(window)} scored day(s): {hits}/{total} = {acc}%")
    for idx, (h, t) in sorted(per.items()):
        print(f"  {idx:<8} {h}/{t} = {round(h / t * 100, 1) if t else 0}%")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="cn-market-daily self-scoring ledger")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="record a pre-market directional lean")
    r.add_argument("--date", required=True, help="trade date YYYY-MM-DD")
    r.add_argument("--lean", required=True, help='JSON: {"CSI300":"down","ChiNext":"up",...}')
    r.add_argument("--note", default="", help="one-line rationale")
    r.set_defaults(func=cmd_record)

    s = sub.add_parser("score", help="grade a date against actual moves")
    s.add_argument("--date", required=True)
    s.add_argument("--actual", required=True, help='JSON: {"CSI300":-2.77,...}')
    s.set_defaults(func=cmd_score)

    st = sub.add_parser("stats", help="running hit-rate")
    st.add_argument("--last", type=int, default=0, help="limit to last N scored days")
    st.set_defaults(func=cmd_stats)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
