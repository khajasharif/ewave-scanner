# Wave 3 Screener

Daily-refreshed shortlist of US stocks that are currently mid-way through what
the app's heuristic identifies as **Elliott Wave 3 of an impulse move, with a
confirmed volume surge**. Built for EODHD (data) + Render (hosting).

**Read this first:** Elliott Wave counting is subjective — there's no
official algorithm, and any mechanical screener (this one included) will
produce false positives and miss real setups. Treat the shortlist as a
starting point for manual review, not a signal to trade on. See
`app/wave_detector.py` for the exact rules used.

## How it works

```
┌────────────────┐   daily, 1 bulk    ┌──────────────┐
│  Render Cron    │──── API call ────▶│   Postgres    │
│  ewave-daily-   │   + wave scan     │  (price_bars, │
│  scan           │                   │  scan_results)│
└────────────────┘                    └──────┬───────┘
                                              │ reads only
                                              ▼
                                       ┌──────────────┐
                                       │  Render Web   │
                                       │  ewave-web    │──▶ you, in a browser
                                       │  (FastAPI)    │
                                       └──────────────┘
```

- **One-time backfill** (`app/backfill.py`) pulls the full US common-stock
  list and ~420 days of daily history per ticker into Postgres. This is the
  only step that makes one API call per ticker (~8,000+ calls) — run it once,
  and again occasionally (e.g. monthly) to pick up new listings.
- **Daily cron job** (`app/scan_job.py`) makes exactly **one** bulk API call
  (`eod-bulk-last-day`) to fetch the whole market's latest bar, appends it,
  then re-runs the wave/volume heuristic on every ticker and writes matches
  to `scan_results`.
- **Web app** (`app/main.py`) only ever reads `scan_results` — it never hits
  EODHD live, so page loads are instant regardless of universe size.

## 1. Deploy to Render

1. Push this folder to a GitHub repo.
2. In the Render dashboard: **New → Blueprint**, point it at the repo. Render
   reads `render.yaml` and provisions three things:
   - `ewave-web` — the web service
   - `ewave-daily-scan` — a Cron Job (runs weekdays at 21:45 UTC — see the
     note in `render.yaml` about shifting it for EST/EDT)
   - `ewave-db` — a managed Postgres database, wired into both services via
     `DATABASE_URL`
3. Render will prompt for the one variable marked `sync: false`:
   **`EODHD_API_KEY`** — paste your EODHD key. Set it on *both* services
   (web and cron) when prompted, or add it once under each service's
   Environment tab.
4. Deploy. The web service will come up immediately, showing the "no scan
   yet" empty state — that's expected.

## 2. Run the one-time backfill

The cron job only *appends* new days — it needs history to work with first.
From the Render dashboard, open the `ewave-web` (or `ewave-daily-scan`)
service's **Shell** tab and run:

```bash
python -m app.backfill
```

This takes a while (thousands of API calls, throttled to
`BACKFILL_CONCURRENCY` concurrent requests — 10 by default). You can test
with a smaller slice first:

```bash
python -m app.backfill --limit=200
```

Once backfill finishes, either wait for the next scheduled cron run or
trigger it immediately from the same shell:

```bash
python -m app.scan_job
```

Refresh the web app — your shortlist should now appear.

## 3. Tuning the screen

All of these are environment variables (already wired into `render.yaml`,
edit values there or in the Render dashboard):

| Variable | Default | What it does |
|---|---|---|
| `ZIGZAG_PCT` | `0.07` | Minimum % swing to count as a wave leg. Lower = more (noisier) pivots; higher = only major swings. |
| `VOLUME_SURGE_MULT` | `1.5` | How much higher average volume during the wave-3 leg must be vs. the baseline before wave 2, to count as "huge volume". |
| `MIN_DOLLAR_VOLUME` | `5000000` | Filters out illiquid/penny names by latest-day dollar volume. |
| `MIN_BARS` | `120` | Minimum days of history required before a ticker is eligible. |
| `BACKFILL_DAYS` | `420` | How much history to pull per ticker during backfill. |

## 4. Local development

```bash
cp .env.example .env        # fill in EODHD_API_KEY; sqlite is fine locally
pip install -r requirements.txt
python -m app.backfill --limit=100   # small test slice
python -m app.scan_job
uvicorn app.main:app --reload
```

Visit http://localhost:8000.

## Notes / limitations

- The wave detector only looks for **bullish** impulses (wave 1 up, wave 2
  down, wave 3 breaking out). Bearish (downside) impulses aren't currently
  flagged — extending `detect_wave3` to the mirror case is straightforward if
  you want it.
- EODHD's `eod-bulk-last-day` and `exchange-symbol-list` endpoints are billed
  per your plan's terms — check your EODHD plan's rate limits if backfill
  seems slow; `BACKFILL_CONCURRENCY` controls how many requests run in
  parallel.
- Render's Cron Job schedule is UTC and fixed (no DST auto-adjustment) —
  the default `45 21 * * 1-5` targets just after the 4pm ET close during
  EDT; nudge it an hour later for EST months if you want it pinned to the
  close year-round.
