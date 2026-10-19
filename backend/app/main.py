import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import DEV_INTEGRATION_KEY, DEV_JWT_SECRET, Settings, settings
from .db import Base, engine
from .routers import account, admin_counselors, auth, bookings, common, customer, demo, integrations, public, staff, waitlist
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
    account.router,
):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok"}


def mount_frontend(application: FastAPI, static_dir: str) -> None:
    """빌드된 React 앱을 같은 서버에서 서빙한다(단일 컨테이너 배포용).

    /api·/docs는 위에서 먼저 등록된 라우트가 처리하고, 나머지 경로는 파일이 있으면 그 파일,
    없으면 index.html을 돌려준다(새로고침·문자 링크로 /c/... 같은 화면 주소에 바로 들어와도 동작).
    """
    root = Path(static_dir).resolve()
    index = root / "index.html"
    if not index.is_file():
        log.warning("STATIC_DIR=%s 에 index.html이 없어 화면 서빙을 건너뜁니다.", static_dir)
        return

    @application.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        target = (root / path).resolve()
        if path and target.is_file() and root in target.parents:
            return FileResponse(target)
        if path.startswith("assets/"):
            # 재배포 후 예전 번들 파일을 요청하면 화면(HTML) 대신 404 → 브라우저가 스크립트 오류로 헷갈리지 않게
            raise HTTPException(404)
        return FileResponse(index)


if settings.static_dir:
    mount_frontend(app, settings.static_dir)
