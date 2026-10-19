"""로그인 없이 쓰는 참석 응답(문자 링크).

리마인더의 참석 확인이 로그인을 요구하면 ① 가족 번호로 문자를 받은 사람은 계정이 없어 응답할 수 없고
② 본인도 문자에서 로그인까지 거쳐야 해 응답률이 떨어진다. 노쇼 방지의 핵심 신호이므로 문자 링크 하나로 끝낸다.

- 링크의 토큰은 예약마다 새로 만들고 DB에는 해시만 둔다(추측·DB 유출 대비).
- 할 수 있는 일은 '통화 가능 / 어려워요' 응답뿐이다. 취소·변경·결과 열람은 로그인 후에만 가능.
- 응답 화면에는 개인정보를 최소로만 보여준다(이름·번호 일부 가림).
"""
from fastapi import APIRouter

from ..db import now
from ..errors import AppError
from ..models import Booking, BookingStatus, NotificationType
from ..security import DbSession
from ..services import notification
from ..services.booking import hash_token

router = APIRouter(prefix="/api/public/attendance", tags=["public"])


def _mask_name(name: str) -> str:
    if len(name) <= 1:
        return name
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


def _mask_phone(phone: str) -> str:
    parts = phone.split("-")
    return f"{parts[0]}-****-{parts[-1]}" if len(parts) == 3 else phone


def _get(db, token: str) -> Booking:
    b = db.query(Booking).filter_by(attendance_token_hash=hash_token(token)).one_or_none()
    if b is None:
        raise AppError(404, "NOT_FOUND", "유효하지 않은 링크입니다.")
    return b


def _can_respond(b: Booking) -> bool:
    return b.status == BookingStatus.CONFIRMED and now() < b.slot.end_at


def _out(b: Booking) -> dict:
    return {
        "start_at": b.slot.start_at,
        "end_at": b.slot.end_at,
        "counselor_name": b.counselor.user.name,
        "subject_name": _mask_name(b.subject.name),
        "contact_phone": _mask_phone(b.contact_phone),
        "status": b.status,
        "attendance_confirmed_at": b.attendance_confirmed_at,
        "attendance_declined_at": b.attendance_declined_at,
        "can_respond": _can_respond(b),
    }


def _respondable(db, token: str) -> Booking:
    b = _get(db, token)
    if not _can_respond(b):
        raise AppError(400, "CANNOT_RESPOND", "이미 지났거나 취소된 상담입니다.")
    return b


@router.get("/{token}")
def view(token: str, db: DbSession):
    return _out(_get(db, token))


@router.post("/{token}/confirm")
def confirm(token: str, db: DbSession):
    b = _respondable(db, token)
    b.attendance_confirmed_at = now()
    b.attendance_declined_at = None
    db.commit()
    return _out(b)


@router.post("/{token}/decline")
def decline(token: str, db: DbSession):
    """'통화가 어려워요': 상담사 화면에 표시하고, 계정 주인에게 일정 변경을 안내한다."""
    b = _respondable(db, token)
    first = b.attendance_declined_at is None
    b.attendance_declined_at = now()
    b.attendance_confirmed_at = None
    if first:
        notification.enqueue(
            db,
            b.customer,
            NotificationType.REMINDER,
            "상담 시간에 통화가 어렵다는 응답이 왔습니다",
            f"{notification.fmt_dt(b.slot.start_at)} {b.subject.name}님 상담을 받는 분이 통화가 어렵다고 응답했습니다.\n"
            f"일정을 바꾸시려면: {notification.settings.frontend_url}/my/bookings/{b.id}",
            booking_id=b.id,
        )
    db.commit()
    return _out(b)
