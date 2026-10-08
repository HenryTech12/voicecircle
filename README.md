# VoiceCircle

Protect older adults from AI voice scams using the voices of the people they already trust.

VoiceCircle has four parts:

| Pillar | What it does |
| --- | --- |
| **Voice Circle** | Family members record a 30–60 s voice sample (with explicit consent). It becomes a voice profile in Resemble AI. |
| **Scam Training** | Places a real phone call (Telnyx) to the senior in a cloned family voice, running a safe scam script at Easy / Medium / Hard. It scores how they responded and always ends by explaining it was practice. |
| **Deepfake Check** | Upload a suspicious recording. You get a plain-language verdict: REAL, FAKE, NOT THEM or NOT SURE. It uses AI-voice detection plus a speaker match against the enrolled voice. |
| **Hugh** | A friendly daily companion call. It tracks speaking pace, answer time, filler words, recall and mood against the senior's own baseline, and alerts family when something changes. |

Built for **ForgeHacks 2026** (AI + Cybersecurity, AI + Healthcare).

```
voicecircle/
├── api/                  FastAPI backend (Python 3.11+)
│   ├── app/              routers, services (telnyx, resemble, llm, metrics…), ORM models
│   ├── tests/            106 pytest tests covering every endpoint
│   ├── scripts/          export_openapi.py
│   ├── requirements*.txt, .env.example, Dockerfile
├── web/                  React + TypeScript + Vite + Tailwind frontend
│   └── src/              pages (Login, Onboarding, Home, Voices, Practice, Check, Hugh, Alerts)
├── supabase/migrations/  001_init.sql (Postgres schema, RLS, storage buckets)
├── docs/                 PRD (PDF), API reference, demo script
├── Makefile, render.yaml
```

## Quick start (mock mode, no accounts needed)

Requirements: Python 3.11+, Node 18+, and ffmpeg (used to convert browser recordings).

```bash
# 1. Backend
cd api
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
# API docs: http://localhost:8000/docs

# 2. Frontend (new terminal)
cd web
npm install
cp .env.example .env
npm run dev
# open http://localhost:5173
```

Or with make: `make install`, then `make api` and `make web` in two terminals.

Then:

1. Sign in with any email. Local auth has no password.
2. Either click **Load demo data** to get Grandma Ada's circle with 14 days of history, or go through onboarding: create a circle, add the senior, and record your voice.
3. **Practice**: click **Call … now**. Use the yellow **Call simulator** to answer as the senior (for example "Who is this really?"), or hang up. You get a score, feedback and the full transcript.
4. **Check a call**: upload any audio file. In mock mode, the filename controls the result: names containing `fake`, `clone`, `deepfake` or `synthetic` come back FAKE; `stranger`, `other` or `notthem` come back NOT THEM; `unsure` comes back NOT SURE; anything else comes back REAL. Audio produced by a practice call is always flagged FAKE.
5. **Hugh**: click **Have Hugh call now** and chat through the simulator. The trend charts show the baseline line, and changes raise alerts.
6. **Alerts**: mark alerts as handled.

## Tests

```bash
cd api && pytest -q          # 106 backend tests (every endpoint + webhook, scheduler, metrics, scoring, safety)
cd web && npm test           # frontend unit tests (API client, formatting)
cd web && npm run build      # type-check + production build
```

| Test file | Covers |
| --- | --- |
| `test_auth_circles_members.py` (25) | dev login, JWT checks, `/me`, circle CRUD, members, phone/time/timezone validation, access control between users |
| `test_voice.py` (11) | prompts, consent required, file type/size checks, enrollment success/failure, delete (also removes the Resemble voice) |
| `test_practice.py` (20) | dial → cloned opener, every outcome & score, stand-firm wrap-up, safety stop on digits, max turns, disclosure, one call at a time, cancel, scheduling, no-answer, dial failure, simulator errors |
| `test_detection.py` (9) | REAL / FAKE / NOT THEM / NOT SURE, clones from practice calls detected, provider failure, validation, access |
| `test_companion_alerts.py` (7) | Hugh call flow, metrics, baseline + change flags, wellbeing alerts + SMS, trends, alert list/filter/ack |
| `test_system.py` (12) | Telnyx webhook signature (ed25519), idempotency, media tokens, demo seed/reset, scheduler daily call (once per day), AI-assistant events |
| `test_units.py` (22) | scoring classifier, sensitive-number guard, metrics maths, decision thresholds, audio validation, state encoding |

## Live mode (real calls)

Set `MOCK_PROVIDERS=false` in `api/.env` and fill in:

| Service | Variables | Notes |
| --- | --- | --- |
| **Telnyx** | `TELNYX_API_KEY`, `TELNYX_CONNECTION_ID`, `TELNYX_FROM_NUMBER`, `TELNYX_PUBLIC_KEY`, `TELNYX_MESSAGING_PROFILE_ID` | Create a Call Control application and set its webhook URL to `https://<your-api>/api/v1/webhooks/telnyx`. Buy a number and assign it. Webhooks are verified with your account's public key. |
| **Resemble AI** | `RESEMBLE_API_KEY`, `RESEMBLE_PROJECT_UUID`, `RESEMBLE_FALLBACK_VOICE_UUID` | Creating voices through the API needs a Resemble plan that includes API voice creation (Business tier at the time of writing). Deepfake detection and identity endpoints may also need plan access. Check your dashboard. |
| **LLM** (optional) | `LLM_PROVIDER` (`openai` or `anthropic`), `LLM_API_KEY`, `LLM_MODEL` | Generates adaptive scam lines, scores calls and drives Hugh. Without a key, scripted lines and the keyword classifier are used. |
| **Public URL** | `PUBLIC_BASE_URL` | Telnyx and Resemble must reach your API. For local testing use `ngrok http 8000` or `cloudflared tunnel`. |
| **Scheduler** | `SCHEDULER_ENABLED=true` | Places daily Hugh calls at each senior's local time and starts scheduled practice calls. |

### Supabase (optional, for production)

1. Run `supabase/migrations/001_init.sql` in the SQL editor. It creates the tables, enables RLS and adds 3 private storage buckets.
2. API: `DATABASE_URL=postgresql+asyncpg://…`, `AUTH_MODE=supabase`, `SUPABASE_URL`, `SUPABASE_JWT_SECRET`. Use `STORAGE_BACKEND=supabase` with `SUPABASE_SERVICE_ROLE_KEY`.
3. Web: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`. The login page switches to magic-link email automatically.

### Deploy

- API: `api/Dockerfile` (includes ffmpeg) or `render.yaml` (Render blueprint).
- Web: `npm run build`, then host `web/dist` on Vercel, Netlify or Cloudflare Pages with `VITE_API_BASE_URL=https://<your-api>`. Set `FRONTEND_ORIGIN` on the API to the site URL for CORS.

## Architecture

```
 Browser (React)  ──REST/JSON──▶  FastAPI  ──▶  DB (SQLite / Supabase Postgres)
      ▲  polling                   │   │──▶  Storage (local / Supabase)
      │                            │   ├──▶  Resemble AI: clone, synthesize, detect, identity
      │                            │   ├──▶  LLM: scam lines, scoring, Hugh replies, summaries
      │                            ▼   └──▶  Telnyx: dial, play audio, transcribe, SMS
      └──────── SMS alerts ◀── Telnyx ──webhooks──▶ /api/v1/webhooks/telnyx (signed, idempotent)
```

- **Call engine** (`app/services/calls.py`): an event-driven state machine for practice and Hugh calls. It handles `call.answered`, playback/speak ended, transcription and hangup. Telnyx webhooks and the mock event bus feed the same handler, so mock mode exercises the real logic.
- **Mock providers**: every external call has a realistic simulated version, so the whole app runs and the tests pass offline.
- **Errors** always come back as `{"error": {"code", "message", "details?"}}`.

## Trust & safety

- Voice cloning happens only after the speaker ticks a versioned consent statement. Consent time and version are stored.
- Practice calls always end with a spoken disclosure: "This was a VoiceCircle practice call arranged by your family…".
- **Safety stop**: if the senior starts saying something that looks like a card, bank, PIN or ID number, the call ends right away. Those digits are never sent to the LLM.
- Practice calls have a turn cap and a time cap. Only one practice call per circle can run at a time.
- Deleting a voice also deletes the clone at Resemble. Media is served only through short-lived signed URLs.
- Wellbeing trends are presented as "a nudge to check in", never as a diagnosis.
- All sensitive actions are recorded in `audit_log`.

See `docs/DEMO_SCRIPT.md` for a 3-minute demo walkthrough and `docs/API.md` for the endpoint reference.
