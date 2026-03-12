# Congrats Agent v1 — Status

## What's Built & Working

### Core Pipeline
- CSV upload → parses MarathonGuide.com format (`OverallPlace`, `FirstName`, `LastName`, `Sex`, `FinalTime`, etc.)
- Age groups derived automatically from `Age` field
- Gender/age group places calculated when missing
- Race name extracted from filename (e.g. `results 23-1_02 - Atlanta Marathon.csv` → `Atlanta Marathon`)
- Extracts **top 3 Male + top 3 Female overall** (up to 6 entries per batch)

### AI Handle Finding (Two-Channel)
- **Channel 1 — Serper.dev**: 3 Google queries per runner (Instagram, Facebook, general marathon)
- **Channel 2 — Claude web search**: `claude-sonnet-4-6` with `web_search_20250305` tool
- **Analysis step**: `claude-haiku-4-5-20251001` reconciles both channels, scores signals, returns best match with confidence (high/medium/low)
- URL validation rejects non-profile URLs (photos, reels, event pages, organizations)
- **Serper results cached** to `data/search_cache.json` — Claude analysis always re-runs
- Cache size shown on upload page with a Clear Cache button

### Post Copy Generation
- `claude-haiku-4-5-20251001` generates Instagram (≤280 chars) + Facebook (2-3 sentences) copy
- **Only generated when handles are found** — skipped entirely if no Instagram or Facebook found
- Per-platform: only writes copy for platforms where a handle was found

### Review UI
- Upload page at `http://localhost:8080`
- All 6 runners processed **in parallel** (ThreadPoolExecutor) — ~20–30s total instead of ~2 min
- Entries sorted by overall finish place after parallel processing completes
- Background thread processes runners after upload — browser shows live progress page
- Dashboard shows all entries with status badges (pending/approved/edited/skipped)
  - Progress bar polls every 5s; stops polling once batch is complete
- **Entries with no handles are auto-skipped** — never presented for review
- Per-entry review page: edit handle, Instagram text, Facebook text, reviewer notes
- Approve or Skip — automatically advances to next pending entry with handles
- Confidence badge colors: green=high, yellow=medium, gray=low, red=not found
- Breadcrumb navigation on all pages: Start → Batch Review → [Runner Name] → Batch Complete
- "Recently Approved Posts" panel on home page (in-memory, lost on restart)

---

## Environment
- **Server**: `python run.py` → `http://localhost:8080`
- **Port 5000 blocked** by macOS AirPlay Receiver — always use 8080
- **Python 3.12** via venv at `congrats-agent/venv312/` (Homebrew install)
- **`.env`** file at `congrats-agent/.env` (hidden file — Cmd+Shift+. to show in Finder)

## Keys in .env
- `ANTHROPIC_API_KEY` — set ✅
- `SERPER_API_KEY` — set ✅
- `SECRET_KEY` — **must be set before production deployment**

---

## Pre-Production Checklist
*(Server, hosting, and infrastructure already in place)*

- [ ] **Persistent storage** — all session data is in-memory and lost on server restart
  - `get_recent_approved()` in `session_store.py` reads from memory
  - Replace `session_store.py` with a DB-backed implementation using the existing company database
  - Update `upload_page` and `approve_entry` routes accordingly
- [ ] **SECRET_KEY** — set a strong random value in the server environment
- [ ] **API keys** — move `ANTHROPIC_API_KEY` and `SERPER_API_KEY` to the server's secrets manager
- [ ] **WSGI server** — replace `python run.py` with `gunicorn "app.main:create_app()"` in the deploy config
- [ ] **Reverse proxy** — point an internal URL at the app (port 8080)
- [ ] **Handle finding quality** — real-world accuracy TBD; prompt tuning may be needed

---

## Key Files
```
congrats-agent/
├── run.py                        # Start server (port 8080)
├── app/
│   ├── config.py                 # Loads .env
│   ├── models.py                 # Finisher, ReviewEntry, ReviewSession, HandleSuggestion, PostCopy
│   ├── ingestion/
│   │   ├── csv_reader.py         # Parses MarathonGuide CSV format
│   │   └── extractor.py          # Extracts top 3 M + top 3 F
│   ├── ai/
│   │   ├── claude_client.py      # Anthropic SDK wrapper + retry (complete + complete_with_web_search)
│   │   ├── handle_finder.py      # find_handles() two-channel + generate_post_copy()
│   │   ├── web_searcher.py       # Serper queries + URL validation
│   │   └── search_cache.py       # JSON cache (data/search_cache.json)
│   └── review/
│       ├── session_store.py      # In-memory session store (thread-safe)
│       └── routes.py             # All Flask routes
├── templates/                    # base, upload, processing, review, review_entry, complete
├── static/
│   ├── style.css
│   └── review.js                 # Auto-dismiss alerts
├── tests/
│   ├── test_extractor.py         # 8 tests
│   └── test_handle_finder.py     # 19 tests
├── data/
│   ├── sample_results.csv        # Mock CSV for testing
│   └── search_cache.json         # Auto-created after first run
└── .env                          # API keys (hidden file)
```

## Sample CSV
Real file used for testing: `/Users/dmitriershov/Downloads/results 23-1_02 - Atlanta Marathon.csv`
Format: `OverallPlace,Bib,FirstName,LastName,Sex,SexPlace,Age,AgeGroup,AgeGroupPlace,City,State,Country,FinalTime,ChipFinalTime,MarathonID,RaceDate`
