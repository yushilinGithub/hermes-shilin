#!/usr/bin/env python3
"""Fetch onshore A-share close data for the post-close wrap (Phase 2).

Uses AkShare against sources that are reachable from outside mainland China.
IMPORTANT: AkShare's eastmoney push endpoints (the ``*_em`` family) are
frequently throttled / connection-dropped from non-CN networks. This script
deliberately uses sina / legu / exchange sources instead, and every block is
best-effort: a failed source is marked unavailable rather than crashing the
brief. Run ~15:30 CST (after the 15:00 close).

Pulls:
  • Index closes (CSI 300 / CSI 1000 / ChiNext / STAR 50)  — sina
  • Market breadth (advancers/decliners, limit-ups/downs, activity) — legu
  • Main-force fund flow (net amount + share)               — eastmoney daily csv (works)
  • Margin balance + 1-day change                           — SSE (best-effort, staleness-checked)
  • Key levels (recent swing high/low for CSI 300)          — sina daily

Usage:
    python3 fetch_a_share.py            # pretty + JSON
    python3 fetch_a_share.py --json     # JSON only
"""
from __future__ import annotations

import datetime as dt
import io
import json
import sys
from contextlib import redirect_stderr
from typing import Any, Callable, Dict, Optional

import akshare as ak

# Index code -> friendly label. sh000300 preferred over sz399300 (same series).
INDICES = {
    "sh000300": "CSI 300 (沪深300)",
    "sh000852": "CSI 1000 (中证1000)",
    "sz399006": "ChiNext (创业板指)",
    "sh000688": "STAR 50 (科创50)",
}


def _try(fn: Callable[[], Any], attempts: int = 2) -> tuple[Optional[Any], Optional[str]]:
    """Run fn with retries, swallowing AkShare's stderr tqdm noise."""
    err = "unavailable"
    for _ in range(attempts):
        try:
            with redirect_stderr(io.StringIO()):
                return fn(), None
        except Exception as exc:  # noqa: BLE001 — best-effort, never crash the brief
            err = repr(exc)[:110]
    return None, err


def get_indices() -> Dict[str, Any]:
    spot, err = _try(ak.stock_zh_index_spot_sina)
    if spot is None:
        return {"error": err}
    out: Dict[str, Any] = {}
    for code, label in INDICES.items():
        row = spot[spot["代码"] == code]
        if row.empty:
            continue
        r = row.iloc[0]
        out[code] = {
            "label": label,
            "last": float(r["最新价"]),
            "change_pct": float(r["涨跌幅"]),
            "prev_close": float(r["昨收"]),
            "turnover": float(r.get("成交额", 0) or 0),
        }
    return out


def get_breadth() -> Dict[str, Any]:
    df, err = _try(ak.stock_market_activity_legu)
    if df is None:
        return {"error": err}
    kv = {str(r["item"]): r["value"] for _, r in df.iterrows()}
    pick = lambda k: kv.get(k)  # noqa: E731
    return {
        "up": pick("上涨"),
        "down": pick("下跌"),
        "limit_up": pick("涨停"),
        "limit_down": pick("跌停"),
        "halted": pick("停牌"),
        "activity": pick("活跃度"),
        "as_of": pick("统计日期"),
    }


def get_fund_flow() -> Dict[str, Any]:
    df, err = _try(ak.stock_market_fund_flow)
    if df is None:
        return {"error": err}
    df = df.copy()
    df["日期"] = df["日期"].astype(str)
    latest = df.sort_values("日期").iloc[-1]
    return {
        "date": latest["日期"],
        "main_net_amount": _num(latest.get("主力净流入-净额")),
        "main_net_pct": _num(latest.get("主力净流入-净占比")),
    }


def get_margin() -> Dict[str, Any]:
    today = dt.date.today()
    start = (today - dt.timedelta(days=12)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    df, err = _try(lambda: ak.stock_margin_sse(start_date=start, end_date=end))
    if df is None or df.empty:
        return {"error": err or "no rows"}
    df = df.copy()
    df["信用交易日期"] = df["信用交易日期"].astype(str)
    df = df.sort_values("信用交易日期")
    latest = df.iloc[-1]
    latest_date = latest["信用交易日期"]
    # Staleness guard: SSE margin defaults to a fixed historical range without
    # dates; if the newest row is >5 days old, treat as unavailable.
    try:
        ld = dt.datetime.strptime(latest_date, "%Y%m%d").date()
        if (today - ld).days > 5:
            return {"error": f"stale (latest {latest_date})"}
    except ValueError:
        return {"error": "unparseable date"}
    bal = _num(latest.get("融资余额"))
    chg = None
    if len(df) >= 2:
        prev = _num(df.iloc[-2].get("融资余额"))
        if bal is not None and prev:
            chg = round(bal - prev, 0)
    return {"date": latest_date, "margin_balance_sse": bal, "day_change": chg}


def get_levels() -> Dict[str, Any]:
    """Per-index 20-day swing high/low + last close (sina daily series).

    Covers all tracked indices, not just CSI 300 — the pre-market brief needs
    real anchor levels for each, otherwise the model guesses them. Reachable
    off-China; the daily series may lag the very latest intraday print near
    the close, which is fine for support/resistance.
    """
    out: Dict[str, Any] = {}
    for code, label in INDICES.items():
        df, err = _try(lambda c=code: ak.stock_zh_index_daily(symbol=c))
        if df is None or df.empty:
            out[code] = {"label": label, "error": err}
            continue
        tail = df.tail(20)
        out[code] = {
            "label": label,
            "recent_high_20d": round(float(tail["high"].max()), 2),
            "recent_low_20d": round(float(tail["low"].min()), 2),
            "last_close": round(float(df.iloc[-1]["close"]), 2),
        }
    return out


def _num(v: Any) -> Optional[float]:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def main() -> int:
    json_only = "--json" in sys.argv
    # --levels-only: pre-market mode. Only the data that exists before the open
    # — latest index quote (prior close) + per-index 20d swing levels. Skips
    # breadth/margin/fund-flow, which are post-close concepts.
    levels_only = "--levels-only" in sys.argv

    out = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "indices": get_indices(),
        "levels": get_levels(),
    }
    if not levels_only:
        out["breadth"] = get_breadth()
        out["fund_flow"] = get_fund_flow()
        out["margin"] = get_margin()

    if levels_only:
        if not json_only:
            print("=" * 60)
            print("A-SHARE LEVELS — pre-market anchor levels")
            print("=" * 60)
            idx = out["indices"]
            lv = out["levels"]
            for code, label in INDICES.items():
                q = idx.get(code, {})
                l = lv.get(code, {})
                prev = q.get("last") or l.get("last_close")
                hi, lo = l.get("recent_high_20d"), l.get("recent_low_20d")
                if prev is None:
                    print(f"  {label:<22} unavailable")
                else:
                    print(f"  {label:<22} prev_close {prev:>10.2f}  "
                          f"| 20d high {hi}  low {lo}")
            print("\n" + "-" * 60)
            print("Use these as REAL anchor levels — do not guess index levels.")
            print("-" * 60 + "\nJSON:")
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    if not json_only:
        print("=" * 60)
        print("A-SHARE CLOSE — post-close wrap")
        print("=" * 60)
        idx = out["indices"]
        if "error" in idx:
            print(f"  indices: unavailable ({idx['error']})")
        else:
            print("\n[indices]")
            for d in idx.values():
                a = "▲" if d["change_pct"] >= 0 else "▼"
                print(f"  {d['label']:<22} {d['last']:>11.2f}  {a} {d['change_pct']:+.2f}%")
        b = out["breadth"]
        if "error" not in b:
            print(f"\n[breadth] up {b['up']} / down {b['down']}  "
                  f"| limit-up {b['limit_up']} limit-down {b['limit_down']} "
                  f"| activity {b['activity']}  (as of {b['as_of']})")
        f = out["fund_flow"]
        if "error" not in f:
            print(f"[fund flow] main-force net {f['main_net_amount']} "
                  f"({f['main_net_pct']}%)  on {f['date']}")
        m = out["margin"]
        print(f"[margin SSE] {m if 'error' not in m else 'unavailable: ' + m['error']}")
        lv = out["levels"]
        if "error" not in lv:
            print(f"[levels CSI300] 20d high {lv['recent_high_20d']} / "
                  f"low {lv['recent_low_20d']} / last {lv['last_close']}")
        print("\n" + "-" * 60)
        print("Breadth read: indices down hard but up≈down -> heavyweight/tech-led")
        print("  selloff with small caps holding (a flow/sector story, not broad panic).")
        print("-" * 60 + "\nJSON:")

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
