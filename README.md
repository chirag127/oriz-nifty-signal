# oriz-nifty-signal

**Live:** https://nifty-signal.oriz.in — *is now a good time to buy Indian equity?*

![license](https://img.shields.io/badge/license-MIT-blue) ![python](https://img.shields.io/badge/python-3.11%2B-3776ab) ![astro](https://img.shields.io/badge/astro-6-ff5d01)

A market-timing signal for long-term Indian-equity investors. Reads valuation +
sentiment indicators once a day, scores each for buy-attractiveness, and combines
them into a single verdict — **STRONG BUY / ACCUMULATE / HOLD-SIP-ONLY / CAUTION**.
SIP always; time your lumpsum by the light.

## Indicators

| Indicator | Source | Bands |
|---|---|---|
| **Nifty 50 PE** (primary, 40%) | IndexPE | cheap <18 · fair 18-22 · expensive 22-24 · frothy >24 |
| **Nifty 500 PE** (breadth, 15%) | IndexPE | judged vs its own 5-yr median |
| **Buffett indicator** (mkt-cap/GDP, 25%) | CEIC | <75 undervalued · 75-115 fair · >115 overvalued |
| **Market Mood (MMI)** (contrarian, 20%) | Tickertape (keyless JSON) | fear = buy, greed = caution |

Composite = weighted mean buy-attractiveness (renormalised over available
indicators; a failed source is recorded as `n/a`, never fabricated).
Verdict: score ≥70 STRONG BUY · 55-70 ACCUMULATE · 40-55 HOLD-SIP-ONLY · <40 CAUTION.

## Stack

- **Python scraper** (`src/nifty_signal/`) — httpx sources with per-indicator
  failover, zone classification + scoring, g4f commentary (template fallback),
  Telegram + ntfy notify, git-as-DB (`data/latest.json` + `data/history/`).
- **Astro dark dashboard** (`web/`) — a trading-desk signal light + per-indicator
  score meters + score-history sparkline. Reads `../data/latest.json` at build.
- **GitHub Actions** — daily at 1pm IST (`30 7 * * *`) + manual dispatch.

## Run

```bash
pip install -e ".[dev]"
python -m pytest -q
python -m nifty_signal --data data -v          # read + write + notify
python -m nifty_signal --no-notify --no-llm     # offline dry run
cd web && npm install && npm run build
```

Notify config (env only, never hardcoded): `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `NTFY_TOPIC` (+ optional `NTFY_BASE_URL/USER/PASSWORD`).

Not investment advice — a valuation-timing signal, not a trade call.
