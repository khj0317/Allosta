"""공통: 메타데이터(서비스 종류/관심사 태그), 제품 카탈로그, 상담사 목록, 인앱 알림."""
from fastapi import APIRouter
from sqlalchemy import select

from ..config import settings
from ..constants import CONCERN_TAGS, RELATION_LABELS, SERVICE_LABELS
from ..db import now
from ..errors import not_found
from ..models import Counselor, Notification, NotificationChannel, NotificationStatus, Product
from ..schemas import CounselorOut, NotificationOut, ProductOut
from ..security import CurrentUser, DbSession

router = APIRouter(prefix="/api", tags=["common"])


@router.get("/meta")
def meta():
    return {
        "service_types": [{"value": k.value, "label": v} for k, v in SERVICE_LABELS.items()],
        "concern_tags": CONCERN_TAGS,
        "relations": [{"value": k, "label": v} for k, v in RELATION_LABELS.items()],
        "demo_mode": settings.demo_mode,
    }


@router.get("/products", response_model=list[ProductOut])
def products(db: DbSession):
    return db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.category, Product.id)).all()


@router.get("/counselors", response_model=list[CounselorOut])
def counselors(db: DbSession):
    rows = db.scalars(select(Counselor).where(Counselor.active.is_(True)).order_by(Counselor.id)).all()
    return [
        CounselorOut(id=c.id, name=c.user.name, specialties=c.specialties, bio=c.bio, active=c.active) for c in rows
    ]


def _in_app_sent(user):
    return (
        Notification.user_id == user.id,
        Notification.channel == NotificationChannel.IN_APP,
        Notification.status == NotificationStatus.SENT,
    )


@router.get("/notifications/unread-count")
def unread_count(user: CurrentUser, db: DbSession):
    """상단 메뉴의 안 읽은 알림 개수."""
    return {"count": db.query(Notification).filter(*_in_app_sent(user), Notification.read_at.is_(None)).count()}


@router.post("/notifications/read-all")
def read_all(user: CurrentUser, db: DbSession):
    n = 0
    for row in db.query(Notification).filter(*_in_app_sent(user), Notification.read_at.is_(None)):
        row.read_at = now()
        n += 1
    db.commit()
    return {"read": n}


@router.get("/notifications/me", response_model=list[NotificationOut])
def my_notifications(user: CurrentUser, db: DbSession):
    return db.scalars(
        select(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.status == NotificationStatus.SENT,
        )
        .order_by(Notification.sent_at.desc())
        .limit(50)
    ).all()


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, user: CurrentUser, db: DbSession):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise not_found("알림")
    n.read_at = n.read_at or now()
    db.commit()
    return n
