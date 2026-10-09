"""VoiceCircle API entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .cors import parse_origins
from .db import init_db
from .errors import register_error_handlers
from .routers import companion, core, detection, practice, system, voice

log = logging.getLogger("voicecircle")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from .services import storage

    await storage.ensure_buckets()
    sched = None
    if settings.SCHEDULER_ENABLED:
        from .jobs import start_scheduler

        sched = start_scheduler()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Backend for VoiceCircle: voice enrollment, practice scam calls, deepfake checks and Hugh companion calls.",
    lifespan=lifespan,
)
origins, origin_regex = parse_origins(settings.FRONTEND_ORIGIN)
if settings.APP_ENV == "dev":
    local = r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?"
    origin_regex = f"{origin_regex}|{local}" if origin_regex else local
log.info("CORS allowed origins: %s regex: %s", origins or ["*"], origin_regex)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ([] if origin_regex else ["*"]),
    allow_origin_regex=origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)


@app.middleware("http")
async def log_rejected_preflight(request, call_next):
    response = await call_next(request)
    if request.method == "OPTIONS" and response.status_code == 400 and request.headers.get("origin"):
        log.warning(
            "CORS preflight rejected for Origin %r. Add it to FRONTEND_ORIGIN (allowed now: %s)",
            request.headers["origin"], ", ".join(origins) or "*",
        )
    return response

for r in (core.router, voice.router, practice.router, detection.router, companion.router, system.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def root():
    return {"name": settings.APP_NAME, "docs": "/docs", "health": "/api/v1/health"}
