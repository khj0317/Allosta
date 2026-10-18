import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers import auth, bookings, common, customer, demo, integrations, staff, waitlist
from .services import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # MVP: 스키마 자동 생성. 운영 전환 시 Alembic 마이그레이션으로 교체.
    Base.metadata.create_all(engine)
    task = None
    if settings.scheduler_interval_seconds > 0:
        task = asyncio.create_task(scheduler.loop(settings.scheduler_interval_seconds))
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="Allostar 상담 운영 플랫폼 API",
    description="검사 결과 기반 1:1 전화 상담 예약·기록·성과 분석",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth.router,
    common.router,
    customer.router,
    bookings.router,
    waitlist.router,
    staff.router,
    staff.admin_router,
    integrations.router,
    demo.router,
):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok"}
