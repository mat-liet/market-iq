import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.services.errors import UnknownThemeError
from app.workers.scheduler import build_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if os.environ.get("ENABLE_SCHEDULER", "true").lower() != "false":
        scheduler = build_scheduler()
        scheduler.start()
        app.state.scheduler = scheduler
    else:
        app.state.scheduler = None

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Market Narrative Intelligence — Phase 1", lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(UnknownThemeError)
    async def _unknown_theme(request: Request, exc: UnknownThemeError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return app


app = create_app()
