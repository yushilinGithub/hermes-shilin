#!/usr/bin/env python3
"""Fetch overnight inputs that drive the next China A-share / HK-tech session.

Dependency-light: uses only `requests` against Yahoo Finance's free public JSON
chart API (no API key, no pandas/yfinance). Prints a compact human-readable
block AND a machine-readable JSON blob so the agent can synthesize a pre-market
brief. All times surfaced are the source's; run this ~07:30 CST.

This is a Phase-1 MVP fetcher. The A-share breadth/margin/flows layer
(AkShare-based) is added in Phase 2 as fetch_a_share.py.

Usage:
    python3 fetch_overnight.py            # pretty + JSON
    python3 fetch_overnight.py --json     # JSON only
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, Optional

import requests

# Symbol -> (label, group). Yahoo tickers; A50/ADRs included as leading tells.
SYMBOLS: Dict[str, tuple[str, str]] = {
    "^IXIC": ("Nasdaq Composite", "US equity"),
    "^GSPC": ("S&P 500", "US equity"),
    "^SOX": ("PHLX Semiconductor (SOX)", "US tech lead"),
    "^TNX": ("US 10Y yield (%)", "rates"),
    "DX-Y.NYB": ("US Dollar Index (DXY)", "fx"),
    "CNY=X": ("USD/CNY", "fx"),
    "CNH=X": ("USD/CNH (offshore)", "fx"),
    "CL=F": ("WTI crude", "commodity"),
    "GC=F": ("Gold", "commodity"),
    "XIN9.FGI": ("FTSE China A50 futures", "A-share lead"),
    "KWEB": ("KraneShares China Internet ETF", "China-tech ADR"),
    "CQQQ": ("Invesco China Tech ETF", "China-tech ADR"),
    "FXI": ("iShares China Large-Cap ETF", "China large-cap ADR"),
}

YF_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
HEADERS = {"User-Agent": "Mozilla/5.0 (cn-market-daily/0.1)"}


def fetch_one(sym: str, attempts: int = 3) -> Optional[Dict[str, Any]]:
    """Return last price + % change vs previous close, or None on failure.

    Retries a few times with backoff — Yahoo's free endpoint intermittently
    throttles/drops connections, so a single miss shouldn't blank a symbol.
    """
    last_exc = "no data"
    for attempt in range(attempts):
        try:
            r = requests.get(
                YF_CHART.format(sym=sym),
                params={"range": "5d", "interval": "1d"},
                headers=HEADERS,
                timeout=10,
            )
            r.raise_for_status()
            return _parse_chart(sym, r.json())
        except Exception as exc:  # noqa: BLE001 — best-effort fetch, never crash the brief
            last_exc = str(exc)[:120]
            time.sleep(0.5 * (attempt + 1))
    return {"symbol": sym, "error": last_exc}


def _parse_chart(sym: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse a Yahoo chart payload into last/prev/change_pct."""
    try:
        result = payload["chart"]["result"][0]
        meta = result["meta"]

        # Compute a TRUE 1-session change from the actual daily close series.
        # meta.chartPreviousClose is the close *before the range starts*, so
        # using it would span multiple days for some symbols (the bug that made
        # KWEB and CQQQ diverge). Take the last two non-null daily closes; fall
        # back to meta only if the series is unusable.
        closes = []
        try:
            closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        except (KeyError, IndexError, TypeError):
            closes = []

        last = meta.get("regularMarketPrice")
        if len(closes) >= 2:
            last = closes[-1] if last is None else last
            prev = closes[-2]
        else:
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")

        if last is None or prev in (None, 0):
            return None
        pct = (last - prev) / prev * 100.0
        return {
            "symbol": sym,
            "last": round(last, 4),
            "prev_close": round(prev, 4),
            "change_pct": round(pct, 2),
        }
    except Exception:  # noqa: BLE001 — malformed payload -> let caller mark it missing
        return None


def main() -> int:
    json_only = "--json" in sys.argv
    out: Dict[str, Any] = {"generated_unix": int(time.time()), "instruments": {}}

    for sym, (label, group) in SYMBOLS.items():
        data = fetch_one(sym)
        if data is None:
            data = {"symbol": sym, "error": "no data"}
        data["label"] = label
        data["group"] = group
        out["instruments"][sym] = data
        time.sleep(0.15)  # be gentle on the free endpoint

    if not json_only:
        print("=" * 60)
        print("OVERNIGHT INPUTS — China pre-market read")
        print("=" * 60)
        last_group = None
        for sym, d in out["instruments"].items():
            if d.get("group") != last_group:
                last_group = d.get("group")
                print(f"\n[{last_group}]")
            if "error" in d:
                print(f"  {d['label']:<34} —  (fetch failed: {d['error']})")
            else:
                arrow = "▲" if d["change_pct"] >= 0 else "▼"
                print(f"  {d['label']:<34} {d['last']:>12}  {arrow} {d['change_pct']:+.2f}%")
        print("\n" + "-" * 60)
        print("Reading guide:")
        print("  • SOX / Nasdaq down hard  -> ChiNext/STAR & CSI 1000 most at risk")
        print("  • FTSE A50 futures        -> implied direction for the 09:30 CST open")
        print("  • KWEB/CQQQ/FXI           -> overnight China sentiment (ADR proxy)")
        print("  • USD/CNH up + 10Y up     -> foreign risk-off pressure on A-shares")
        print("-" * 60 + "\n")
        print("JSON:")

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
