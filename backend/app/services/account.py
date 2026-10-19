"""회원 탈퇴: 개인정보·건강정보는 즉시 지우고, 통계·법정 보존에 필요한 행만 익명으로 남긴다.

행을 통째로 지우지 않는 이유
- 예약·상담 기록·주문은 상담사 실적, 전환율, 정산의 근거라 외래키로 묶여 있다. 행을 지우면 과거 지표가 바뀐다.
- 주문(계약·결제 기록)은 전자상거래법상 5년 보존 대상이다.
그래서 "누구인지 알 수 있는 값"과 "건강 상태를 알 수 있는 값"만 지우고, 시각·상태·금액 같은 값만 남긴다.

| 즉시 삭제 | 익명으로 보존 |
|---|---|
| 이름·이메일·휴대폰·생년월일(계정·본인·가족), 비밀번호 | 예약 행(시각·상담사·상태) |
| 결과지 지표 수치·종합 코멘트·키트 등록 정보 | 상담 기록 행(상태·관심 태그·제출 시각), 추천 제품 |
| 상담 기록 본문·수정 이력, 사전 질문, 연락처 | 주문(제품·금액·시각) |
| 알림함, 대기 신청 내용, 인증·발송 기록 | |
"""
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import now
from ..errors import AppError
from ..models import (
    Booking,
    BookingStatus,
    ConsultationRecord,
    KitClaimFailure,
    Notification,
    Order,
    PhoneVerification,
    RecordRevision,
    Role,
    Slot,
    SmsSendLog,
    Subject,
    TestResult,
    User,
    WaitlistEntry,
    WaitlistStatus,
)
from ..security import hash_password
from . import booking as booking_service
from . import credentials
from . import notification
from . import waitlist as waitlist_service
from .phone import digits

WITHDRAWN_NAME = "탈퇴회원"
# 데모 시연용 계정은 탈퇴하면 다른 평가자가 시연할 수 없게 되므로 막는다(새로 가입한 계정으로 시험)
DEMO_EMAILS = {"customer@allostar.kr"}


def _upcoming(db: Session, user: User) -> list[Booking]:
    return list(
        db.scalars(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .where(Booking.customer_id == user.id, Booking.status == BookingStatus.CONFIRMED, Slot.end_at > now())
            .order_by(Slot.start_at)
        )
    )


def _imminent(bookings: list[Booking]) -> list[Booking]:
    """곧 시작하거나 진행 중인 상담: 상담사가 이미 전화를 준비하고 있어 온라인으로 취소할 수 없는 예약."""
    limit = now() + timedelta(hours=settings.cancel_deadline_hours)
    return [b for b in bookings if b.slot.start_at < limit]


def _active_waitlists(db: Session, user: User) -> list[WaitlistEntry]:
    return list(
        db.scalars(
            select(WaitlistEntry).where(
                WaitlistEntry.customer_id == user.id,
                WaitlistEntry.status.in_([WaitlistStatus.WAITING, WaitlistStatus.OFFERED]),
            )
        )
    )


def preview(db: Session, user: User) -> dict:
    """탈퇴 전 안내: 무엇이 취소·삭제되고 무엇이 남는지."""
    upcoming = _upcoming(db, user)
    imminent = _imminent(upcoming)
    subjects = db.scalars(select(Subject).where(Subject.owner_id == user.id)).all()
    return {
        "upcoming_bookings": len(upcoming),
        "imminent_bookings": [
            {"id": b.id, "start_at": b.slot.start_at, "counselor_name": b.counselor.user.name} for b in imminent
        ],
        "active_waitlists": len(_active_waitlists(db, user)),
        "family_members": sum(s.relation.value != "SELF" for s in subjects),
        "results": sum(len(s.results) for s in subjects),
        "orders_kept": db.query(Order).filter_by(customer_id=user.id).count(),
        "blocked_reason": _blocked_reason(user, imminent),
    }


def _blocked_reason(user: User, imminent: list[Booking]) -> str | None:
    if settings.demo_mode and user.email in DEMO_EMAILS:
        return "시연용 데모 계정은 탈퇴할 수 없습니다. 새로 가입한 계정으로 시험해주세요."
    if imminent:
        return (
            f"{settings.cancel_deadline_hours}시간 안에 시작하거나 진행 중인 상담이 있어 지금은 탈퇴할 수 없습니다. "
            "상담이 끝난 뒤 다시 시도하거나 고객센터로 연락해주세요."
        )
    return None


def withdraw(db: Session, user: User, password: str) -> None:
    if user.role != Role.CUSTOMER:
        raise AppError(403, "FORBIDDEN", "고객 계정만 탈퇴할 수 있습니다. 상담사·운영자 계정은 관리자가 비활성화합니다.")
    # 비밀번호 확인은 로그인과 같은 실패 횟수로 잠근다(훔친 토큰으로 대입해 탈퇴시키는 것 방지)
    credentials.check_password(db, user, password, status=400, code="WRONG_PASSWORD", message="비밀번호가 올바르지 않습니다.")
    upcoming = _upcoming(db, user)
    reason = _blocked_reason(user, _imminent(upcoming))
    if reason:
        raise AppError(409, "WITHDRAW_BLOCKED", reason)

    # 1) 진행 중인 신청 정리. 대기를 먼저 정리해야 예약 취소로 생긴 빈자리가 본인 대기에 다시 제안되지 않는다.
    freed: list[Slot] = []
    for entry in _active_waitlists(db, user):
        slot = waitlist_service._release(db, entry)
        entry.status = WaitlistStatus.CANCELLED
        if slot:
            freed.append(slot)
    db.flush()
    for b in upcoming:
        # 떠나는 고객에게 취소 문자는 보내지 않는다. 빈자리는 cancel_booking이 다음 대기자에게 제안한다.
        booking_service.cancel_booking(db, b, user, reason="회원 탈퇴", commit=False, notify=False)
    for slot in freed:
        waitlist_service.offer_slot(db, slot)
    # 시간이 지났는데 처리되지 않은 상담: 탈퇴 후에는 처리할 수 없어 '처리 누락'에 영원히 남으므로 탈퇴로 종료한다
    for b in db.scalars(
        select(Booking).join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.customer_id == user.id, Booking.status == BookingStatus.CONFIRMED, Slot.end_at <= now())
    ):
        b.status, b.cancelled_at, b.cancel_reason = BookingStatus.CANCELLED, now(), "회원 탈퇴"

    # 2) 건강정보·개인정보 삭제
    subjects = db.scalars(select(Subject).where(Subject.owner_id == user.id)).all()
    for s in subjects:
        for r in s.results:
            r.indicators.clear()  # delete-orphan: 지표 수치 행 삭제
            r.overall_comment = ""
            r.registered_name = r.registered_birth_date = r.registered_phone = None
        s.name, s.birth_date, s.phone = WITHDRAWN_NAME, None, None

    bookings = db.scalars(select(Booking).where(Booking.customer_id == user.id)).all()
    booking_ids = [b.id for b in bookings]
    for b in bookings:
        b.contact_phone, b.pre_questions, b.cancel_reason = "", "", b.cancel_reason and "회원 탈퇴"
        b.attendance_token_hash = None  # 문자에 남은 참석 응답 링크도 무효화
    records = db.scalars(select(ConsultationRecord).where(ConsultationRecord.booking_id.in_(booking_ids))).all()
    for rec in records:
        rec.summary = rec.customer_message = rec.lifestyle_advice = ""
        rec.discussed_indicator_ids = []
        for rc in rec.recommendations:
            rc.note = ""
    if records:
        db.query(RecordRevision).filter(RecordRevision.record_id.in_([r.id for r in records])).delete(
            synchronize_session=False
        )
    for w in db.scalars(select(WaitlistEntry).where(WaitlistEntry.customer_id == user.id)):
        w.contact_phone, w.pre_questions = "", ""

    # 알림: 본인 알림함 + 이 고객 예약에 대해 상담사에게 간 알림(고객 이름·사유가 들어 있음). 아직 안 보낸 문자도 함께 사라진다.
    db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
    if booking_ids:
        db.query(Notification).filter(Notification.booking_id.in_(booking_ids)).delete(synchronize_session=False)
    phone_digits = digits(user.phone)
    db.query(PhoneVerification).filter(
        (PhoneVerification.owner_id == user.id) | (PhoneVerification.phone == phone_digits)
    ).delete(synchronize_session=False)
    db.query(SmsSendLog).filter(SmsSendLog.phone == phone_digits).delete(synchronize_session=False)
    db.query(KitClaimFailure).filter(KitClaimFailure.owner_id == user.id).delete(synchronize_session=False)

    # 3) 계정 익명화. 같은 이메일·번호로 다시 가입할 수 있도록 고유값은 탈퇴 표식으로 바꾼다.
    user.email = f"withdrawn-{user.id}@deleted.invalid"
    user.phone = f"WD-{user.id}"
    user.name = WITHDRAWN_NAME
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.phone_verified_at = None
    user.failed_logins, user.locked_until = 0, None
    user.withdrawn_at = now()
    db.commit()
    notification.log.info("[ACCOUNT] user=%s withdrawn", user.id)
