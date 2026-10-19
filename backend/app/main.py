import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import DEV_INTEGRATION_KEY, DEV_JWT_SECRET, Settings, settings
from .db import Base, engine
from .routers import admin_counselors, auth, bookings, common, customer, demo, integrations, public, staff, waitlist
from .services import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


log = logging.getLogger("allostar")


def validate_settings(s: Settings) -> None:
    """운영(데모 아님)에서 저장소에 공개된 기본 비밀키로 켜지는 것을 막는다.

    기본 JWT 키를 그대로 쓰면 누구나 관리자 로그인 토큰을 만들 수 있고, 기본 연동 키면 가짜 주문을 넣을 수 있다.
    """
    weak = []
    if s.jwt_secret == DEV_JWT_SECRET or len(s.jwt_secret) < 32:
        weak.append("JWT_SECRET(32자 이상)")
    if s.integration_api_key == DEV_INTEGRATION_KEY or len(s.integration_api_key) < 16:
        weak.append("INTEGRATION_API_KEY(16자 이상)")
    if not weak:
        return
    if s.demo_mode:
        log.warning("데모 모드: 개발용 기본 키 사용 중 (%s). 운영 배포 전 반드시 바꾸세요.", ", ".join(weak))
        return
    raise RuntimeError(f"운영 모드에서 개발용 기본 키로는 시작할 수 없습니다. 환경변수를 설정하세요: {', '.join(weak)}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_settings(settings)
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
    admin_counselors.router,
    integrations.router,
    demo.router,
    public.router,
):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok"}
