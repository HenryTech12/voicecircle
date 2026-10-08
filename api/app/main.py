"""VoiceCircle API entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .errors import register_error_handlers
from .routers import companion, core, detection, practice, system, voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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
origins = [o.strip() for o in settings.FRONTEND_ORIGIN.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?" if settings.APP_ENV == "dev" else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)

for r in (core.router, voice.router, practice.router, detection.router, companion.router, system.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def root():
    return {"name": settings.APP_NAME, "docs": "/docs", "health": "/api/v1/health"}
