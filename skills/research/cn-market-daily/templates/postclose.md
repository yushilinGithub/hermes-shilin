# 盘后总结 + 次日展望 / Post-Close Wrap + Next-Day Outlook — {DATE} (CST)

> Decision-support only. Not financial advice. You make every trading decision.

## 1. 收盘 / The close
| Index | Close | Δ% |
|---|---|---|
| CSI 300 (沪深300) | | |
| CSI 1000 (中证1000) | | |
| ChiNext (创业板指) | | |
| STAR 50 (科创50) | | |

- **Breadth:** up {x} / down {y} · limit-up {a} / limit-down {b} · activity {z}
- **Margin (SSE):** balance {bal}, 1-day Δ {chg}
- **Main-force fund flow:** {net} ({pct}%)  *(mark "unavailable" if the source failed)*

## 2. 今日驱动 / What drove today
{2–4 bullets, each mapped to a driver in references/drivers.md. Note especially:
breadth vs index divergence — even breadth + big index drop = heavyweight/tech-led,
not broad panic. Identify which index led and which sectors.}

## 3. 自我打分 / Self-scoring (yesterday's call)
```
score_yesterday.py score --date {DATE} --actual '{"CSI300":..,"CSI1000":..,"ChiNext":..}'
score_yesterday.py stats
```
- Result: {hits/total, what was right/wrong, the miss reason — log lessons to memory}

## 4. 次日日程 / Tomorrow's calendar (CST)
- {data prints, policy meetings, futures/options expiry — time + expected impact}

## 5. 次日情景 / Tomorrow's scenarios (with triggers)
- **基准 / Base ({prob}):** {what + trigger}
- **上行 / Bull ({prob}):** {trigger}
- **下行 / Bear ({prob}):** {trigger}

## 6. 关键点位 / Key levels
- CSI 300: support {x} / resistance {y}  *(use 20d high/low from levels block as a start)*
- CSI 1000 / ChiNext: support {x} / resistance {y}

## 7. 次日策略倾向 / Strategy lean (decision-support)
- {bias per index + sizing/stop framing + an explicit "skip if X" gate}
- **Record the call:** `score_yesterday.py record --date {NEXT_DATE} --lean '{...}' --note "..."`
