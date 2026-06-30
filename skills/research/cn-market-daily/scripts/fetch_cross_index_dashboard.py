#!/usr/bin/env python3
"""Cross-bloc dashboard for the four ETF-tracked indices the desk follows.

Covers both macro blocs (US + China) and both axes (broad vs tech/growth):

    +-------------+----------------+----------------------+
    |             | Broad market   | Tech / high-growth   |
    +-------------+----------------+----------------------+
    | US          | S&P 500        | Nasdaq 100           |
    | China       | CSI 300        | Hang Seng Tech       |
    +-------------+----------------+----------------------+

Unlike ``fetch_overnight.py`` (one-session premarket read) this gives a
multi-window view — 1d / 5d / 1mo / YTD — so the cross-bloc divergences that
actually drive positioning (onshore vs offshore China, broad vs AI-led US) are
visible at a glance.

DATA SOURCE: Yahoo Finance via yfinance. The rest of the skill is CN-native
(AkShare/sina) because Yahoo was historically blocked from the mainland
deployment; this script is the exception — the server can now reach Yahoo,
which buys back the macro gauges no CN source serves reliably (US 10Y, DXY,
VIX). If Yahoo access regresses, fall back to the sina/AkShare symbols
(.INX / .NDX / sh000300 / HSTECH) used elsewhere in this skill.

Notes:
  • Hang Seng Tech has no native Yahoo index symbol — proxied by 3032.HK, the
    Hang Seng TECH Index ETF (NAV-based; returns track the index closely but
    are not identical).
  • ^TNX is the 10Y yield *level* (e.g. 4.37 = 4.37%); its % columns are the
    relative move in the yield, i.e. direction, not a price return.

Every block is best-effort: a failed ticker is marked unavailable rather than
crashing the brief.

Usage:
    python3 fetch_cross_index_dashboard.py            # pretty + JSON
    python3 fetch_cross_index_dashboard.py --json     # JSON only
"""
from __future__ import annotations

import datetime as dt
import io
import json
import sys
from contextlib import redirect_stderr
from typing import Any, Dict, List, Optional, Tuple

import yfinance as yf

# (label, yahoo symbol, bloc, axis)
INDICES: List[Tuple[str, str, str, str]] = [
    ("S&P 500", "^GSPC", "US", "broad"),
    ("Nasdaq 100", "^NDX", "US", "tech"),
    ("CSI 300 (沪深300)", "000300.SS", "China", "broad"),
    ("Hang Seng Tech (3032.HK proxy)", "3032.HK", "China", "tech"),
]
# (label, yahoo symbol)
MACRO: List[Tuple[str, str]] = [
    ("US 10Y yield", "^TNX"),
    ("DXY (dollar)", "DX-Y.NYB"),
    ("VIX", "^VIX"),
    ("Nvidia (AI-leadership)", "NVDA"),
    ("USD/CNY", "CNY=X"),
    ("WTI oil", "CL=F"),
]
# Trailing-session windows, in trading days.
WINDOWS: List[Tuple[str, int]] = [("1d", 1), ("5d", 5), ("1mo", 21)]

ALL_SYMBOLS = [s for _, s, _, _ in INDICES] + [s for _, s in MACRO]


def _download(attempts: int = 3) -> Any:
    """Batch-pull 1y of daily closes for every symbol, swallowing yf noise."""
    last_exc: Optional[Exception] = None
    for _ in range(attempts):
        try:
            with redirect_stderr(io.StringIO()):
                df = yf.download(
                    ALL_SYMBOLS, period="1y", interval="1d",
                    auto_adjust=True, progress=False, threads=True,
                )
            if df is not None and not df.empty:
                return df["Close"]
        except Exception as exc:  # noqa: BLE001 — best-effort, never crash the brief
            last_exc = exc
    if last_exc:
        print(f"# batch download failed: {last_exc!r}", file=sys.stderr)
    return None


def _fetch_one(symbol: str, attempts: int = 3) -> Any:
    """Single-symbol fallback for tickers a batch download silently drops."""
    for _ in range(attempts):
        try:
            with redirect_stderr(io.StringIO()):
                df = yf.download(
                    symbol, period="1y", interval="1d",
                    auto_adjust=True, progress=False, threads=False,
                )
            if df is not None and not df.empty:
                close = df["Close"]
                # single-symbol download may return a 1-col frame
                return close.iloc[:, 0] if hasattr(close, "columns") else close
        except Exception:  # noqa: BLE001 — best-effort
            continue
    return None


def _metrics(closes: Any) -> Optional[Dict[str, Any]]:
    """Last close + 1d/5d/1mo/YTD % from a close Series with a DatetimeIndex."""
    if closes is None:
        return None
    closes = closes.dropna()
    if len(closes) < 2:
        return None
    vals = [float(v) for v in closes.tolist()]
    idx = closes.index
    last = vals[-1]
    out: Dict[str, Any] = {"last": round(last, 2), "as_of": idx[-1].date().isoformat()}
    for name, n in WINDOWS:
        out[name] = round((last / vals[-1 - n] - 1) * 100, 2) if len(vals) > n else None
    year = idx[-1].year
    base = next((vals[i] for i in range(len(vals)) if idx[i].year == year), None)
    out["YTD"] = round((last / base - 1) * 100, 2) if base else None
    return out


def _series(close_df: Any, symbol: str) -> Any:
    """Pull a symbol's close series from the batch, falling back to a solo
    download when the batch dropped or blanked it (yfinance does this on
    transient errors)."""
    s = close_df[symbol] if close_df is not None and symbol in getattr(close_df, "columns", []) else None
    if s is None or s.dropna().empty:
        s = _fetch_one(symbol)
    return s


def _wrap(label: str, parsed: Optional[Dict[str, Any]], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = {"label": label, **(extra or {})}
    return {**base, **parsed} if parsed else {**base, "error": "no data"}


def build() -> Dict[str, Any]:
    close_df = _download()
    indices: Dict[str, Any] = {}
    for label, sym, bloc, axis in INDICES:
        indices[sym] = _wrap(label, _metrics(_series(close_df, sym)), {"bloc": bloc, "axis": axis})
    macro: Dict[str, Any] = {}
    for label, sym in MACRO:
        macro[sym] = _wrap(label, _metrics(_series(close_df, sym)))
    return {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "source": "yfinance",
        "indices": indices,
        "macro": macro,
    }


def _fmt_row(d: Dict[str, Any]) -> str:
    if "error" in d:
        return f"  {d['label']:<32} — (unavailable)"
    cells = []
    for name, _ in WINDOWS + [("YTD", 0)]:
        v = d.get(name)
        cells.append(f"{v:+6.2f}%" if isinstance(v, (int, float)) else "    n/a")
    return f"  {d['label']:<32} {d['last']:>11,.2f}   " + "  ".join(cells) + f"   ({d.get('as_of', '—')})"


def main() -> int:
    json_only = "--json" in sys.argv
    out = build()

    if not json_only:
        hdr = " " * 48 + "last   " + "    ".join(n for n, _ in WINDOWS) + "    YTD"
        print("=" * 84)
        print("CROSS-BLOC DASHBOARD — four ETF-tracked indices (yfinance)")
        print("=" * 84)
        print(hdr)
        print("\n[Indices]")
        for d in out["indices"].values():
            print(_fmt_row(d))
        print("\n[Macro context]")
        for d in out["macro"].values():
            print(_fmt_row(d))

        print("\n" + "-" * 84)
        print("Reading guide (ties to references/drivers.md):")
        print("  • Nasdaq 100 vs S&P 500 gap   -> AI/tech leadership vs broad market")
        print("  • 10Y falling but Nasdaq soft -> pullback is positioning/earnings, not rates")
        print("  • Nvidia rolling over         -> Nasdaq's main swing factor weakening")
        print("  • CSI 300 vs Hang Seng Tech   -> onshore (policy-supported) vs offshore")
        print("                                   (foreign-flow / USD-driven) China split")
        print("  • DXY up + HSTECH down        -> dollar/sentiment hit, NOT CN fundamentals")
        print("  • VIX > ~20                   -> cross-bloc correlations tighten (sell together)")
        print("-" * 84 + "\nJSON:")

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
