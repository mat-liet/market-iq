import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
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
    return app


app = create_app()
