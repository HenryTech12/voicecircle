# VoiceCircle API reference

Base URL: `{API}/api/v1`. All endpoints except `/health`, `/auth/*`, `/webhooks/telnyx` and `/media/*` need `Authorization: Bearer <token>`.

Errors always look like `{"error": {"code": "not_found", "message": "Circle not found", "details": ...}}`.

Interactive docs: `http://localhost:8000/docs` (Swagger) and `/redoc`. The full schema is in `api/openapi.json`.

## System

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Health |

## Auth

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/auth/config` | Auth Config |
| `POST` | `/auth/dev-login` | Dev Login — Passwordless local login for development (AUTH_MODE=local only). |
| `GET` | `/me` | Me |

## Circles

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/circles` | Create Circle |
| `GET` | `/circles` | List Circles |
| `GET` | `/circles/{circle_id}` | Get Circle |
| `PATCH` | `/circles/{circle_id}` | Rename Circle |
| `DELETE` | `/circles/{circle_id}` | Delete Circle |

## Members

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/circles/{circle_id}/members` | Add Member |
| `GET` | `/members/{member_id}` | Get Member |
| `PATCH` | `/members/{member_id}` | Update Member |
| `DELETE` | `/members/{member_id}` | Delete Member |

## Voice

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/voice/prompts` | Voice Prompts |
| `POST` | `/members/{member_id}/voice` | Upload Voice |
| `GET` | `/members/{member_id}/voice` | Voice Status |
| `DELETE` | `/members/{member_id}/voice` | Delete Voice |

## Practice

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/practice/scenarios` | List Scenarios |
| `POST` | `/circles/{circle_id}/practice-calls` | Create Practice Call |
| `GET` | `/circles/{circle_id}/practice-calls` | List Practice Calls |
| `GET` | `/practice-calls/{call_id}` | Get Practice Call |
| `POST` | `/practice-calls/{call_id}/cancel` | Cancel Practice Call |

## Detection

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/circles/{circle_id}/detections` | Create Detection |
| `GET` | `/circles/{circle_id}/detections` | List Detections |
| `GET` | `/detections/{detection_id}` | Get Detection |

## Companion

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/members/{member_id}/companion-calls` | Call Hugh Now |
| `GET` | `/members/{member_id}/companion-calls` | List Companion Calls |
| `GET` | `/companion-calls/{call_id}` | Get Companion Call |
| `GET` | `/members/{member_id}/companion-trends` | Companion Trends |

## Alerts

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/circles/{circle_id}/alerts` | List Alerts |
| `POST` | `/alerts/{alert_id}/ack` | Ack Alert |

## Webhooks

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/webhooks/telnyx` | Telnyx Webhook |

## Simulator

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/dev/calls/{call_id}/say` | Sim Say — Mock mode: pretend the senior said something on the call. |
| `POST` | `/dev/calls/{call_id}/hangup` | Sim Hangup — Mock mode: pretend the senior hung up. |
| `GET` | `/dev/sms` | Sim Sms — Mock mode: SMS messages that would have been sent. |

## Demo

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/demo/seed` | Demo Seed — Create a fully populated demo circle for the current user (DEMO_MODE only). |
| `POST` | `/demo/reset` | Demo Reset — Delete every circle owned by the current user (DEMO_MODE only). |

## Simulator (mock mode only)

`POST /dev/calls/{id}/say {"text": "..."}` makes the senior say something on a simulated call, for either a practice call or a Hugh call id. `POST /dev/calls/{id}/hangup` makes the senior hang up. `GET /dev/sms` lists the SMS messages that would have been sent.
