"""인프로세스 주기 작업: 알림 발송, 대기 제안 만료 처리.

MVP는 단일 인스턴스를 가정해 FastAPI lifespan 안에서 asyncio 태스크로 돌린다.
다중 인스턴스로 확장 시 중복 실행을 막기 위해 별도 워커(Celery beat / Cloud Scheduler)로 분리하고,
알림 선점은 SELECT ... FOR UPDATE SKIP LOCKED로 바꾼다(설계 문서 '확장 고려' 참고).
"""
import asyncio
import logging

from ..db import SessionLocal
from . import notification, waitlist

log = logging.getLogger("allostar.scheduler")


def run_once() -> dict:
    with SessionLocal() as db:
        expired = waitlist.process_expirations(db)
        sent = notification.dispatch_due(db)
    return {"expired": expired, "sent": sent}


async def loop(interval: int) -> None:
    while True:
        try:
            result = await asyncio.to_thread(run_once)
            if any(result.values()):
                log.info("scheduler tick %s", result)
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)
