---
name: cn-market-daily
description: "Research and analyze Chinese equity index conditions (CSI 300, CSI 1000, ChiNext/STAR 'China Nasdaq') and produce a pre-market brief and post-close wrap with scenarios, key levels, and a decision-support trading strategy. Decision-support only — never places trades."
version: 0.1.0
author: aleennzhang
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [markets, china, csi300, csi1000, chinext, research, trading, daily-brief]
prerequisites:
  commands: [python3]
---

# CN Market Daily

Daily research analyst for **Chinese equity indices**: CSI 300 (沪深300, large cap),
CSI 1000 (中证1000, small cap), and the "China Nasdaq" growth complex (ChiNext 创业板 /
STAR 科创 onshore; KWEB/CQQQ offshore). Produces two briefs a day with scenarios, key
levels, the day's drivers, and a **decision-support** strategy for the next session.

## Hard boundary — read first

This skill is **decision-support only**. It NEVER places, sizes, or recommends trades as
instructions to execute. It outputs *analysis and scenarios*; the user makes every trading
decision. Always frame strategy as "if/then scenarios + risk framing," never as advice.
Every brief ends with the disclaimer line in the templates.

## What this skill knows

The analytical core lives in two references — **read the relevant one fully before writing a brief**:

- `references/drivers.md` — the driver taxonomy: how policy, liquidity, macro, external
  (US/Fed/USD), flows/derivatives, and retail sentiment move A-shares, and the typical
  +1% / -2% asymmetry.
- `references/index-playbooks.md` — per-index playbooks: composition, beta, the heavyweight
  stocks and sectors that actually move each index, and what each is most sensitive to.

## Daily workflow (all times China Standard Time, CST)

### 1. Pre-market brief — run ~07:30 CST

```bash
python3 skills/research/cn-market-daily/scripts/fetch_overnight.py            # overnight US/ADR/A50
python3 skills/research/cn-market-daily/scripts/fetch_a_share.py --levels-only # REAL A-share anchor levels
```

The first pulls overnight inputs (US close, semis/Mag-7 proxy, 10Y yield, USD/CNY,
oil/gold, FTSE China A50 futures, KWEB/CQQQ ADRs) via Yahoo's free JSON API. The second
gives each index's prior close + 20-day swing high/low from sina — **use these as the key
levels; never guess index levels** (fetch_overnight has no A-share level source). Then:

1. Read `references/drivers.md` + `references/index-playbooks.md`.
2. Web-search for any overnight China policy/regulatory headlines and the day's scheduled
   events (PMI/CPI/FOMC/expiry — see `references/calendar.md` once created).
3. Synthesize using `templates/premarket.md`. Output: overnight wrap → 2–3 scenarios with
   explicit triggers → key levels for all three indices → "what would change my mind."

### 2. Post-close wrap + next-day outlook — run ~15:30 CST

```bash
python3 skills/research/cn-market-daily/scripts/fetch_a_share.py     # close, breadth, margin, flows, levels
```

Then:
1. Read the close data + `references/drivers.md` + `references/index-playbooks.md`.
2. **Self-score yesterday's call** and check the running hit-rate:
   ```bash
   python3 skills/research/cn-market-daily/scripts/score_yesterday.py score \
       --date <today> --actual '{"CSI300":-2.77,"CSI1000":-2.09,"ChiNext":-3.83}'
   python3 skills/research/cn-market-daily/scripts/score_yesterday.py stats
   ```
   Log the miss reason to memory so the playbooks improve over time.
3. Web-search tomorrow's calendar + any post-close policy news.
4. Fill `templates/postclose.md` → drivers, scenarios, levels, strategy lean.
5. **Record tomorrow's directional lean** so it can be scored next session:
   ```bash
   python3 skills/research/cn-market-daily/scripts/score_yesterday.py record \
       --date <tomorrow> --lean '{"CSI300":"down","CSI1000":"down","ChiNext":"down"}' --note "..."
   ```

The self-scoring ledger lives at `$HERMES_HOME/cn-market-daily/calls.jsonl`.

## Data-source reality (read before trusting numbers)

AkShare's **eastmoney push endpoints (`*_em`, and `stock_market_fund_flow`) are frequently
throttled / connection-dropped from non-mainland-China networks.** `fetch_a_share.py`
deliberately prefers reachable sources and degrades gracefully (a failed block is marked
`unavailable`, never crashes the brief):

| Datum | Source used | Reliable off-CN? |
|---|---|---|
| Index closes | `stock_zh_index_spot_sina` | ✅ |
| Breadth | `stock_market_activity_legu` | ✅ |
| Margin (SSE) | `stock_margin_sse` (needs recent dates; staleness-checked) | ✅ |
| Levels | `stock_zh_index_daily` (sina; may lag intraday near close) | ✅ |
| Main-force fund flow | `stock_market_fund_flow` (eastmoney) | ⚠️ often fails off-CN |

If you run the agent on a China VPS (recommended for live trading use), the eastmoney
sources become reliable and you can re-enable `*_em` variants for richer sector flows.
`fetch_overnight.py` (US/ADR/A50) uses Yahoo and is reachable everywhere.

## Output discipline

- Separate **knowable facts** (overnight prints, calendar events, levels) from
  **speculation** (next-day direction). Label speculation as such.
- Always give scenarios with triggers, not a single point forecast.
- Map every "why it moved" claim to a driver in `references/drivers.md`.
- Keep it scannable — a trader reads this in 60 seconds before the open.

## Roadmap

- [x] Phase 1 (MVP): skill + drivers + playbooks + `fetch_overnight.py` + pre-market template, CLI output.
- [x] Phase 2: AkShare A-share fetcher (`fetch_a_share.py`) + post-close template + self-scoring (`score_yesterday.py`).
- [ ] Phase 3: cron schedule (07:30 + 15:30 CST) + Telegram delivery via gateway.

Phase 2 requires `akshare` in the env: `uv pip install akshare` (already installed in `.venv`).
