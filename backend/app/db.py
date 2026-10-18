from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# 한국은 서머타임이 없어 고정 오프셋으로 충분(Windows에 tzdata 의존성 불필요)
KST = timezone(timedelta(hours=9), "KST")


def now() -> datetime:
    """서비스 기준 현재 시각(KST, naive).

    상담은 국내 전화 상담만 다루므로 모든 일시를 KST naive datetime으로 저장한다.
    해외 고객/다지역 상담사로 확장 시 UTC 저장 + 표시 시 변환으로 바꿔야 한다(설계 문서 참고).
    테스트에서 시간을 고정할 수 있도록 함수로 감싼다.
    """
    return datetime.now(KST).replace(tzinfo=None, microsecond=0)


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
