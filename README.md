# VoiceCircle

Protect older adults from AI voice scams using the voices of the people they already trust.

VoiceCircle has four parts:

| Pillar | What it does |
| --- | --- |
| **Voice Circle** | Family members record a 30–60 s voice sample (with explicit consent). It becomes a voice profile in Resemble AI. |
| **Scam Training** | Places a real phone call (Twilio) to the senior in a cloned family voice, running a safe scam script at Easy / Medium / Hard. It scores how they responded and always ends by explaining it was practice. |
| **Deepfake Check** | Upload a suspicious recording. You get a plain-language verdict: REAL, FAKE, NOT THEM or NOT SURE. It uses AI-voice detection plus a speaker match against the enrolled voice. |
| **Hugh** | A friendly daily companion call. It tracks speaking pace, answer time, filler words, recall and mood against the senior's own baseline, and alerts family when something changes. |

Built for **ForgeHacks 2026** (AI + Cybersecurity, AI + Healthcare).

```
voicecircle/
├── api/                  FastAPI backend (Python 3.11+)
│   ├── app/              routers, services (twilio, resemble, llm, metrics…), ORM models
│   ├── tests/            123 pytest tests covering every endpoint
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
cd api && pytest -q          # 123 backend tests (every endpoint + webhook, scheduler, metrics, scoring, safety)
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
| `test_system.py` (18) | Twilio signature check (incl. Twilio's documented example), full live practice call through TwiML (Play → Gather → disclosure → Hangup → status callback → SMS), safety stop, silence wrap-up on Hugh calls, no-answer, cancel via REST, Messaging Service SMS, TwiML escaping, idempotency, media tokens, demo seed/reset, scheduler |
| `test_units.py` (22) | scoring classifier, sensitive-number guard, metrics maths, decision thresholds, audio validation, state encoding |

## Live mode (real calls)

Set `MOCK_PROVIDERS=false` in `api/.env` and fill in:

| Service | Variables | Notes |
| --- | --- | --- |
| **Twilio** | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, optional `TWILIO_MESSAGING_SERVICE_SID`, `TWILIO_SAY_VOICE`, `TWILIO_SPEECH_LANGUAGE` | Get a Twilio number. You don't need to configure any webhook in the console: each call passes its own `Url`/`StatusCallback` (`/api/v1/webhooks/twilio/voice|gather|status`). Webhooks are verified with `X-Twilio-Signature`, so `PUBLIC_BASE_URL` must be exactly the https URL Twilio calls. Enable the senior's country under Voice > Settings > Geo permissions. On a trial account you can only call and text verified numbers. |
| **Resemble AI** | `RESEMBLE_API_KEY`, `RESEMBLE_PROJECT_UUID`, `RESEMBLE_FALLBACK_VOICE_UUID` | Creating voices through the API needs a Resemble plan that includes API voice creation (Business tier at the time of writing). Deepfake detection and identity endpoints may also need plan access. Check your dashboard. |
| **LLM** (optional) | `LLM_PROVIDER` (`openai` or `anthropic`), `LLM_API_KEY`, `LLM_MODEL` | Generates adaptive scam lines, scores calls and drives Hugh. Without a key, scripted lines and the keyword classifier are used. |
| **Public URL** | `PUBLIC_BASE_URL` | Twilio and Resemble must reach your API over https. For local testing use `ngrok http 8000` or `cloudflared tunnel`. |
| **Scheduler** | `SCHEDULER_ENABLED=true` | Places daily Hugh calls at each senior's local time and starts scheduled practice calls. |

### Supabase (optional, for production)

1. Run `supabase/migrations/001_init.sql` in the SQL editor. It creates the tables, enables RLS and adds 3 private storage buckets. If you ran an older Telnyx version of it, also run `002_twilio_rename.sql`.
2. API: `DATABASE_URL=postgresql+asyncpg://…`, `AUTH_MODE=supabase`, `SUPABASE_URL`, `SUPABASE_JWT_SECRET`. Use `STORAGE_BACKEND=supabase` with `SUPABASE_SERVICE_ROLE_KEY`.
3. Web: `SUPABASE_URL`, `SUPABASE_ANON_KEY`. The login page switches to magic-link email automatically.

### Deploy

- API: `api/Dockerfile` (includes ffmpeg) or `render.yaml` (Render blueprint).
- Web: `npm run build`, then host `web/dist` on Vercel, Netlify or Cloudflare Pages with `API_BASE_URL=https://<your-api>`. Set `FRONTEND_ORIGIN` on the API to the site URL for CORS (comma-separated; trailing slashes are ignored; `https://your-app-*.vercel.app` covers preview deploys). Rejected origins are logged.

## Architecture

```
 Browser (React)  ──REST/JSON──▶  FastAPI  ──▶  DB (SQLite / Supabase Postgres)
      ▲  polling                   │   │──▶  Storage (local / Supabase)
      │                            │   ├──▶  Resemble AI: clone, synthesize, detect, identity
      │                            │   ├──▶  LLM: scam lines, scoring, Hugh replies, summaries
      │                            ▼   └──▶  Twilio REST: dial, hang up, SMS
      └──────── SMS alerts ◀── Twilio ──webhooks──▶ /api/v1/webhooks/twilio/{voice,gather,status} → TwiML
```

- **Call engine** (`app/services/calls.py`): an event-driven state machine for practice and Hugh calls. It handles `call.answered`, playback/speak ended, transcription and hangup. Twilio webhooks and the mock event bus feed the same handler, so mock mode exercises the real logic. In live mode each webhook runs the engine inside a TwiML context: actions become `<Play>`, `<Say>`, `<Gather input="speech">` and `<Hangup/>` verbs in the reply (`app/services/twilio.py`).
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
