#!/usr/bin/env python3
"""Fetch overnight inputs that drive the next China A-share / HK-tech session.

CHINA-NATIVE: uses AkShare against **sina** sources, which are reachable from
mainland China (where Yahoo Finance is blocked). The previous Yahoo/`requests`
implementation is gone — it does not work on a China-hosted deployment.

Sina daily series return the *previous* US session's close, which at ~07:30 CST
is exactly last night's close — the overnight read we want.

Pulls (all sina, work in CN and abroad):
  • US indices: Nasdaq / S&P 500 / PHLX Semiconductor (SOX) — index_us_stock_sina
  • China ADRs: KWEB / CQQQ / FXI (overnight China sentiment + implied direction)
  • USD/CNY — fx_spot_quote

Dropped vs the old Yahoo version: US 10Y (akshare source is stale), DXY (not in
sina fx), FTSE A50 futures (no clean CN source — FXI ADR is the overnight
China-direction proxy instead).

Usage:
    python3 fetch_overnight.py            # pretty + JSON
    python3 fetch_overnight.py --json     # JSON only
"""
from __future__ import annotations

import datetime as dt
import io
import json
import sys
from contextlib import redirect_stderr
from typing import Any, Callable, Dict, Optional

import akshare as ak

# sina symbol -> label
US_INDICES = {
    ".IXIC": "Nasdaq Composite",
    ".INX": "S&P 500",
    ".SOX": "PHLX Semiconductor (SOX)",
}
ADRS = {
    "KWEB": "KraneShares China Internet ETF",
    "CQQQ": "Invesco China Tech ETF",
    "FXI": "iShares China Large-Cap ETF",
}


def _try(fn: Callable[[], Any], attempts: int = 3) -> tuple[Optional[Any], Optional[str]]:
    """Run fn with retries, swallowing AkShare's stderr tqdm noise."""
    err = "unavailable"
    for _ in range(attempts):
        try:
            with redirect_stderr(io.StringIO()):
                return fn(), None
        except Exception as exc:  # noqa: BLE001 — best-effort, never crash the brief
            err = repr(exc)[:110]
    return None, err


def _pct_from_daily(df: Any) -> Optional[Dict[str, Any]]:
    """Last close + 1-session % change from a daily OHLC dataframe."""
    if df is None or df.empty or "close" not in df.columns:
        return None
    closes = [float(c) for c in df["close"].tolist() if c is not None]
    if len(closes) < 2:
        return None
    last, prev = closes[-1], closes[-2]
    if prev == 0:
        return None
    return {
        "last": round(last, 4),
        "prev_close": round(prev, 4),
        "change_pct": round((last - prev) / prev * 100.0, 2),
    }


def get_us_indices() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for sym, label in US_INDICES.items():
        df, err = _try(lambda s=sym: ak.index_us_stock_sina(symbol=s))
        parsed = _pct_from_daily(df)
        out[sym] = {"label": label, **parsed} if parsed else {"label": label, "error": err or "no data"}
    return out


def get_adrs() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for sym, label in ADRS.items():
        df, err = _try(lambda s=sym: ak.stock_us_daily(symbol=s))
        parsed = _pct_from_daily(df)
        out[sym] = {"label": label, **parsed} if parsed else {"label": label, "error": err or "no data"}
    return out


def get_usdcny() -> Dict[str, Any]:
    df, err = _try(ak.fx_spot_quote)
    if df is None:
        return {"error": err}
    row = df[df["货币对"] == "USD/CNY"]
    if row.empty:
        return {"error": "USD/CNY not in feed"}
    bid = float(row.iloc[0]["买报价"])
    ask = float(row.iloc[0]["卖报价"])
    return {"label": "USD/CNY", "mid": round((bid + ask) / 2, 4)}


def main() -> int:
    json_only = "--json" in sys.argv
    out = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "us_indices": get_us_indices(),
        "china_adrs": get_adrs(),
        "usdcny": get_usdcny(),
    }

    if not json_only:
        print("=" * 60)
        print("OVERNIGHT INPUTS — China pre-market read (sina / CN-accessible)")
        print("=" * 60)

        print("\n[US indices — last session]")
        for d in out["us_indices"].values():
            if "error" in d:
                print(f"  {d['label']:<34} — (unavailable)")
            else:
                a = "▲" if d["change_pct"] >= 0 else "▼"
                print(f"  {d['label']:<34} {d['last']:>12}  {a} {d['change_pct']:+.2f}%")

        print("\n[China ADRs — overnight sentiment]")
        for d in out["china_adrs"].values():
            if "error" in d:
                print(f"  {d['label']:<34} — (unavailable)")
            else:
                a = "▲" if d["change_pct"] >= 0 else "▼"
                print(f"  {d['label']:<34} {d['last']:>12}  {a} {d['change_pct']:+.2f}%")

        u = out["usdcny"]
        print(f"\n[FX] USD/CNY {u.get('mid', 'unavailable')}")

        print("\n" + "-" * 60)
        print("Reading guide:")
        print("  • SOX / Nasdaq down hard  -> ChiNext/STAR & CSI 1000 most at risk")
        print("  • FXI (China large-cap ADR) -> best overnight proxy for the A-share open")
        print("  • KWEB / CQQQ             -> China-tech sentiment read")
        print("  • USD/CNY up              -> foreign risk-off / capital-outflow pressure")
        print("-" * 60 + "\nJSON:")

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
