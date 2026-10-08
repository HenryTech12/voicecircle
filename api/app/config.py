"""Application settings loaded from environment variables (.env supported)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_ENV: str = "dev"
    APP_NAME: str = "VoiceCircle API"
    PUBLIC_BASE_URL: str = "http://localhost:8000"  # public https URL Twilio/Resemble can reach
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    DEMO_MODE: bool = True

    # Mock mode: every provider returns realistic fake data, no credentials needed
    MOCK_PROVIDERS: bool = True
    MOCK_EVENT_DELAY: float = 1.0  # seconds between simulated call events (0 = inline)
    MOCK_AUTO_SENIOR: bool = False  # if true, a scripted senior answers mock calls

    # Database: SQLite for local dev/tests, Postgres (Supabase) in production
    # e.g. postgresql+asyncpg://postgres:<pw>@db.<ref>.supabase.co:5432/postgres
    DATABASE_URL: str = "sqlite+aiosqlite:///./voicecircle.db"

    # Auth: "local" (built-in email login, for dev) or "supabase" (verify Supabase JWTs)
    AUTH_MODE: str = "local"
    LOCAL_JWT_SECRET: str = "dev-secret-change-me-please-32-bytes-min"
    SUPABASE_URL: str = ""
    SUPABASE_JWT_SECRET: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Storage: "local" (files on disk) or "supabase" (Supabase Storage)
    STORAGE_BACKEND: str = "local"
    STORAGE_DIR: str = "./storage"
    MEDIA_URL_TTL_SECONDS: int = 600
    MAX_UPLOAD_MB: int = 20

    # Twilio (Programmable Voice + Messaging)
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""  # also used to verify X-Twilio-Signature on webhooks
    TWILIO_FROM_NUMBER: str = ""  # your Twilio number, E.164
    TWILIO_MESSAGING_SERVICE_SID: str = ""  # optional; used instead of From for SMS
    TWILIO_SAY_VOICE: str = "Polly.Joanna-Neural"  # neutral voice for disclosures and Hugh
    TWILIO_SPEECH_LANGUAGE: str = "en-US"
    TWILIO_GATHER_TIMEOUT: int = 6  # seconds to wait for the senior to start speaking
    TWILIO_MAX_SILENCES: int = 3  # silent turns in a row before the call wraps up

    # Resemble AI
    RESEMBLE_API_KEY: str = ""
    RESEMBLE_PROJECT_UUID: str = ""
    RESEMBLE_FALLBACK_VOICE_UUID: str = ""  # used for disclosures / Hugh fallback
    IDENTITY_DISTANCE_LOWER_IS_BETTER: bool = True

    # LLM
    LLM_PROVIDER: str = "openai"  # openai | anthropic
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"

    # Thresholds
    DETECT_FAKE_THRESHOLD: float = 0.5
    DETECT_UNSURE_MARGIN: float = 0.1
    SPEAKER_MATCH_THRESHOLD: float = 0.75
    PRACTICE_MAX_TURNS: int = 8
    PRACTICE_MAX_SECONDS: int = 240

    # Scheduler (daily companion calls)
    SCHEDULER_ENABLED: bool = False

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
