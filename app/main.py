"""GymTrack AI application factory.

Run locally:  .venv\\Scripts\\python -m uvicorn app.main:app --reload
"""

import logging
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

import app.models  # noqa: F401 - register all models
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import register_error_handlers
from app.modules.attendance.router import router as attendance_router
from app.modules.auth.router import router as auth_router
from app.modules.auth.service import LoginRateLimiter
from app.modules.members.router import router as members_router
from app.modules.workouts.router import router as workouts_router

STATIC_DIR = Path(__file__).parent / "static"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    app = FastAPI(title="GymTrack AI", version="0.1.0")
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.login_limiter = LoginRateLimiter(
        settings.login_max_attempts, timedelta(minutes=settings.login_window_minutes)
    )

    register_error_handlers(app)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            # FastAPI's /docs page loads Swagger UI from a CDN, so it cannot use the strict CSP.
            if name == "Content-Security-Policy" and request.url.path in ("/docs", "/redoc"):
                continue
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for router in (auth_router, members_router, attendance_router, workouts_router):
        app.include_router(router)

    @app.get("/api/health", tags=["ops"])
    def health():
        with app.state.db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
