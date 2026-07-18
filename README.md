# StadiumSaathi — Smart Stadium & Tournament Operations Platform

> A GenAI command layer serving three real personas on match day — Fan,
> Volunteer, and Command Center — from one shared live stadium-state feed,
> built for FIFA World Cup 2026 stadium operations.

---

## Chosen Vertical

**Smart Stadiums & Tournament Operations** — specifically: navigation,
crowd management, multilingual assistance, and real-time operational
decision support, unified around one coherent match-day data model rather
than treated as separate disconnected features.

---

## Target Users

| Persona | Need |
|---|---|
| **Fan** | Multilingual, instant answers to "where do I go / what's crowded / where's the nearest accessible facility" |
| **Volunteer / Staff** | Fast, calm, structured guidance the moment an incident is reported, without waiting for a supervisor |
| **Organizer (Command Center)** | A live read on crowd hotspots across zones and a concrete, actionable next step — not just a raw dashboard of numbers |

---

## Why Three Personas, One System

Most single-feature submissions solve one narrow problem. StadiumSaathi
instead models the **same match day** from three vantage points, all reading
from **one shared simulated live stadium state** (zone-by-zone crowd density).
A fan asking "is it crowded near me?" and an organizer seeing "Zone A at 91%"
are looking at the same underlying data — this is what makes it read as one
integrated operations platform rather than three unrelated demos.

---

## Honest Scope Note

FIFA World Cup 2026 stadium sensor data is not publicly available for a
hackathon build. **Crowd density is a clearly-labelled simulated live feed**
(a bounded random walk per zone, refreshed every 8 seconds) standing in for
what would be real turnstile/camera sensor data in production. Everything
built on top of it — the Gemini prompts, the warnings, the recommendations —
is real and would work unchanged against a genuine live feed.

---

## How the Solution Works

### Fan View
Fan checks in with name, seat zone, and preferred language (10 languages
supported). They can then ask Saathi anything in free text; Gemini answers
using the **live zone state** as grounding context, and the UI surfaces an
explicit crowd warning banner if their zone crosses a density threshold.

### Volunteer View
Volunteer signs in with role and zone. They tap an incident category
(Medical, Lost Child, Overcrowding, Security, Facility, Other), optionally
add a description, and Gemini returns **3 concise numbered next steps** plus
an explicit escalation call (Medical / Security / handle locally) — designed
to be read in under 10 seconds during a real incident.

### Command Center View
Organizers see a live density bar per zone (colour-coded normal/busy/
critical), a running **AI-generated recommendation panel** that only fires
when zones cross the high-density threshold (e.g. "Redirect Zone A traffic
to Gate 5"), and a live incident feed aggregating every volunteer report
across the stadium.

### Architecture

```
Fan / Volunteer / Organizer (Browser)
     │
     ▼
Flask App (Cloud Run)
     │
     ├── /api/stadium_state          → Shared live zone density feed
     ├── /api/fan/session            → Create fan session
     ├── /api/fan/ask                → Gemini-grounded Q&A + crowd warning
     ├── /api/volunteer/session      → Create volunteer session
     ├── /api/volunteer/incident     → Gemini incident triage guidance
     ├── /api/command/recommendations → Gemini operational recommendations
     ├── /api/command/incidents      → Live incident log
     └── /health                     → Health check
          │
          └── Google Gemini 2.0 Flash (all AI reasoning across 3 personas)
```

---

## Assumptions Made

- Crowd density is simulated (see Scope Note above), not live sensor data.
- Sessions are in-memory with a 24-hour TTL and lazy cleanup — a production
  version would use Firestore for persistence across instances.
- No Google Maps dependency was used, to avoid a billing-account requirement
  for what is fundamentally indoor zone navigation, not GPS routing.
- Incident log is capped at 200 most-recent entries to bound memory.

---

## Accessibility Commitment

- Skip-to-content link; semantic `<header>`/`<main>`/`<section>` structure.
- `aria-label`, `aria-live`, `role="list"`/`"listitem"` on all dynamic content
  (chat log, incident log, zone heatmap).
- Full keyboard navigation with visible `:focus-visible` outlines.
- `prefers-reduced-motion` respected (the live pulse indicator is disabled).
- WCAG AA colour contrast maintained across the dark stadium theme.

---

## Google Services Used

| Service | Purpose |
|---------|---------|
| **Google Gemini 2.0 Flash** | Fan Q&A, volunteer incident triage, and command-center recommendations — all three personas share one client with retry/backoff logic |
| **Google Cloud Run** | Containerised serverless deployment |

---

## Project Structure

```
stadiumsaathi/
├── app.py                    # Flask routes, security, rate limiting, error mapping
├── env.py                    # Single source of truth for .env loading (see note below)
├── stadium_engine.py          # Shared state, 3-persona logic, crowd simulation
├── gemini_client.py           # Gemini API wrapper with retry/backoff + bounded cache
├── pyproject.toml             # ruff + mypy + pytest configuration
├── requirements.txt
├── Dockerfile
├── .env.example
├── templates/
│   └── index.html             # Structure for all 3 persona views
├── static/
│   ├── css/style.css          # Stadium night-match theme
│   └── js/app.js              # All 3 personas' frontend logic
└── tests/
    ├── conftest.py
    ├── test_stadium_engine.py  # 22 unit tests
    ├── test_app.py             # 20 integration tests
    └── test_gemini_client.py   # 8 unit tests
```

### Code quality tooling

This project is linted with **ruff** (style, import order, common bug
patterns) and type-checked with **mypy**, both configured in
`pyproject.toml`. Install the dev tools and run them locally:

```bash
pip install -r requirements-dev.txt
ruff check .
mypy app.py stadium_engine.py gemini_client.py env.py --ignore-missing-imports
```

One deliberate exception is declared in `pyproject.toml`:
`app.py` imports the `env` module first, out of alphabetical order, because
that import's *side effect* — populating `os.environ` from `.env` — must
run before `gemini_client.py` reads `GEMINI_MODEL` at import time. This is
called out explicitly in `pyproject.toml` so an automatic import-sorter
never silently reorders it and breaks configuration loading.

### A known, documented trade-off: rate limiting under a single worker

`Flask-Limiter` is configured with `storage_uri="memory://"`, which keeps
rate-limit counters in a single process's memory. This is only *correct*
with exactly one Gunicorn worker — with multiple workers (or multiple
Cloud Run instances), each would keep an independent counter and the
effective rate limit would silently multiply. The `Dockerfile` therefore
runs `--workers 1`, trading some request throughput for a rate limiter
that actually enforces what it claims. A production deployment expecting
real concurrent traffic should instead point `storage_uri` at a shared
backend (e.g. Redis).

---

## Local Setup

```bash
git clone https://github.com/YOUR_USERNAME/stadiumsaathi.git
cd stadiumsaathi
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
python app.py
# Visit http://localhost:5000
```

---

## Running Tests

```bash
pytest tests/ -v
# Expected: 50 tests pass
```

---

## Deployment to Google Cloud Run

```bash
gcloud run deploy stadiumsaathi \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=your_key,FLASK_SECRET_KEY=your_secret
```

---

## Built With

Built using **Google Antigravity** — intent-driven, agentic development.

---

## License

MIT
