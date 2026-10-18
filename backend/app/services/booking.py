"""예약 도메인 서비스.

중복 예약 방지 전략(2중 방어)
1) 애플리케이션 검증: 슬롯 상태/선점(hold)/시간 검사 → 사용자에게 친절한 에러 메시지
2) DB 불변식: bookings(slot_id) WHERE status != 'CANCELLED' 부분 유니크 인덱스
   → 동시 요청이 1)을 동시에 통과하더라도 커밋은 단 1건만 성공한다(나머지는 409 + 대안 슬롯 제시).
"""
from datetime import date, datetime, time, timedelta

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..db import now
from ..errors import AppError, forbidden, not_found
from ..models import (
    Booking,
    BookingStatus,
    Counselor,
    NotificationType,
    Relation,
    ServiceType,
    Slot,
    SlotStatus,
    Subject,
    TestResult,
    User,
    WaitlistEntry,
)
from . import notification


# ---------------------------------------------------------------- 조회

def _slot_free_clause():
    return ~exists().where(Booking.slot_id == Slot.id, Booking.status != BookingStatus.CANCELLED)


def available_slots(
    db: Session,
    service_type: ServiceType,
    date_from: date,
    date_to: date,
    counselor_id: int | None = None,
    for_waitlist_id: int | None = None,
) -> list[Slot]:
    """예약 가능한 슬롯: OPEN + 미예약 + 미선점 + 리드타임 이후 + 해당 분석 서비스 전문 상담사."""
    earliest = now() + timedelta(minutes=settings.booking_lead_minutes)
    t = now()
    stmt = (
        select(Slot)
        .join(Counselor, Counselor.id == Slot.counselor_id)
        .options(joinedload(Slot.counselor).joinedload(Counselor.user))
        .where(
            Slot.status == SlotStatus.OPEN,
            Slot.start_at >= max(earliest, datetime.combine(date_from, time.min)),
            Slot.start_at < datetime.combine(date_to + timedelta(days=1), time.min),
            Counselor.active.is_(True),
            _slot_free_clause(),
        )
        .order_by(Slot.start_at, Slot.counselor_id)
    )
    if counselor_id:
        stmt = stmt.where(Slot.counselor_id == counselor_id)
    slots = db.scalars(stmt).unique().all()
    return [
        s
        for s in slots
        if service_type.value in s.counselor.specialties
        and (s.hold_until is None or s.hold_until <= t or (for_waitlist_id and s.held_for_waitlist_id == for_waitlist_id))
    ]


def suggest_alternatives(db: Session, service_type: ServiceType, desired: datetime, limit: int = 6) -> list[Slot]:
    """원하는 시간이 마감됐을 때의 대안: 같은 시각 다른 상담사 → 같은 날 가까운 시각 → 이후 7일 내 가까운 시각."""
    candidates = available_slots(db, service_type, desired.date(), desired.date() + timedelta(days=7))

    def score(s: Slot) -> tuple:
        same_time = s.start_at == desired
        same_day = s.start_at.date() == desired.date()
        return (not same_time, not same_day, abs((s.start_at - desired).total_seconds()))

    return sorted(candidates, key=score)[:limit]


# ---------------------------------------------------------------- 검증

def load_subject_and_result(db: Session, customer: User, subject_id: int, result_id: int) -> tuple[Subject, TestResult]:
    subject = db.get(Subject, subject_id)
    if subject is None or subject.owner_id != customer.id:
        raise not_found("피검자")
    result = db.get(TestResult, result_id)
    if result is None or result.subject_id != subject.id:
        raise not_found("검사 결과")
    if subject.relation != Relation.SELF and subject.consent_at is None:
        raise AppError(
            400, "CONSENT_REQUIRED", f"{subject.name}님의 결과 상담을 위해 피검자 동의 확인이 필요합니다."
        )
    return subject, result


def resolve_contact_phone(customer: User, subject: Subject, contact: str) -> str:
    """상담 전화를 받을 번호: 계정 주인(가입 시 인증) 또는 인증을 마친 가족 본인 번호만 허용."""
    if contact == "SUBJECT":
        if subject.relation == Relation.SELF or not subject.phone or subject.consent_at is None:
            raise AppError(400, "CONTACT_NOT_ALLOWED", "인증된 가족 번호로만 상담 전화를 받을 수 있습니다.")
        return subject.phone
    return customer.phone


def _ensure_no_conflict(db: Session, customer: User, slot: Slot, result: TestResult, exclude_booking_id: int | None):
    base = select(Booking).join(Slot, Slot.id == Booking.slot_id).where(
        Booking.customer_id == customer.id, Booking.status == BookingStatus.CONFIRMED
    )
    if exclude_booking_id:
        base = base.where(Booking.id != exclude_booking_id)
    # 같은 결과지로 이미 진행 예정 예약이 있으면 막는다(슬롯 독점·노쇼 방지). 변경은 reschedule로.
    dup = db.scalars(base.where(Booking.result_id == result.id)).first()
    if dup:
        raise AppError(409, "ALREADY_BOOKED", "이 검사 결과로 이미 예정된 상담이 있습니다. 일정 변경을 이용해주세요.",
                       booking_id=dup.id)
    # 같은 계정이 동일 시간대에 다른 상담을 잡지 못하게 한다(전화는 한 번에 한 통)
    overlap = db.scalars(base.where(Slot.start_at < slot.end_at, Slot.end_at > slot.start_at)).first()
    if overlap:
        raise AppError(409, "TIME_CONFLICT", "같은 시간대에 이미 다른 상담 예약이 있습니다.")


def _slot_conflict_error(db: Session, service_type: ServiceType, desired: datetime) -> AppError:
    from ..schemas import SlotOut  # 순환 import 방지

    alts = suggest_alternatives(db, service_type, desired)
    return AppError(
        409,
        "SLOT_TAKEN",
        "선택하신 시간은 방금 마감되었습니다. 다른 시간을 선택하거나 대기 신청을 해주세요.",
        alternatives=[SlotOut.from_slot(s).model_dump(mode="json") for s in alts],
    )


# ---------------------------------------------------------------- 명령

def create_booking(
    db: Session,
    customer: User,
    *,
    slot_id: int,
    subject_id: int,
    result_id: int,
    contact: str = "OWNER",
    contact_phone: str | None = None,
    pre_questions: str = "",
    concern_tags: list[str] | None = None,
    waitlist_entry: WaitlistEntry | None = None,
    exclude_booking_id: int | None = None,
    commit: bool = True,
) -> Booking:
    """contact_phone은 내부 호출(일정 변경·대기 수락)에서 이미 검증된 번호를 이어받을 때만 쓴다."""
    subject, result = load_subject_and_result(db, customer, subject_id, result_id)
    contact_phone = contact_phone or resolve_contact_phone(customer, subject, contact)
    slot = db.get(Slot, slot_id)
    if slot is None:
        raise not_found("슬롯")
    counselor = slot.counselor
    if result.service_type.value not in counselor.specialties or not counselor.active:
        raise AppError(400, "COUNSELOR_MISMATCH", "선택한 상담사는 해당 분석 서비스 상담을 진행하지 않습니다.")

    t = now()
    if slot.status != SlotStatus.OPEN or slot.start_at < t + timedelta(minutes=settings.booking_lead_minutes):
        raise _slot_conflict_error(db, result.service_type, slot.start_at)
    held_by_other = (
        slot.hold_until is not None
        and slot.hold_until > t
        and (waitlist_entry is None or slot.held_for_waitlist_id != waitlist_entry.id)
    )
    if held_by_other:
        raise _slot_conflict_error(db, result.service_type, slot.start_at)

    _ensure_no_conflict(db, customer, slot, result, exclude_booking_id)

    booking = Booking(
        slot_id=slot.id,
        counselor_id=counselor.id,
        customer_id=customer.id,
        subject_id=subject.id,
        result_id=result.id,
        contact_phone=contact_phone,
        pre_questions=pre_questions,
        concern_tags=concern_tags or [],
    )
    db.add(booking)
    try:
        db.flush()  # 부분 유니크 인덱스 위반이 여기서 감지된다
    except IntegrityError:
        db.rollback()
        raise _slot_conflict_error(db, result.service_type, slot.start_at)

    slot.held_for_waitlist_id = None
    slot.hold_until = None
    db.refresh(booking)
    notification.schedule_for_new_booking(db, booking)
    if commit:
        db.commit()
    return booking


def _assert_customer_owns(booking: Booking, user: User):
    if booking.customer_id != user.id:
        raise forbidden()


def _assert_changeable_by_customer(booking: Booking):
    if booking.status != BookingStatus.CONFIRMED:
        raise AppError(400, "INVALID_STATE", "진행 예정인 예약만 변경/취소할 수 있습니다.")
    if booking.slot.start_at - now() < timedelta(hours=settings.cancel_deadline_hours):
        raise AppError(
            400,
            "DEADLINE_PASSED",
            f"상담 {settings.cancel_deadline_hours}시간 전 이후에는 온라인 변경/취소가 불가합니다. 고객센터로 연락해주세요.",
        )


def cancel_booking(db: Session, booking: Booking, user: User, reason: str = "", commit: bool = True) -> Booking:
    from . import waitlist  # 순환 import 방지

    if user.role.value == "CUSTOMER":
        _assert_customer_owns(booking, user)
        _assert_changeable_by_customer(booking)
    elif booking.status != BookingStatus.CONFIRMED:
        raise AppError(400, "INVALID_STATE", "진행 예정인 예약만 취소할 수 있습니다.")

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now()
    booking.cancel_reason = reason or None
    notification.cancel_pending_for_booking(db, booking.id)
    notification.enqueue(
        db,
        booking.customer,
        NotificationType.BOOKING_CANCELLED,
        "상담 예약이 취소되었습니다",
        f"{notification.fmt_dt(booking.slot.start_at)} 상담 예약이 취소되었습니다."
        + (f"\n사유: {reason}" if reason else ""),
        booking_id=booking.id,
        sms_to=booking.contact_phone,
    )
    db.flush()
    # 빈자리가 생겼으므로 대기자에게 즉시 제안
    waitlist.offer_slot(db, booking.slot)
    if commit:
        db.commit()
    return booking


def reschedule_booking(
    db: Session,
    booking: Booking,
    user: User,
    new_slot_id: int,
    *,
    waitlist_entry: WaitlistEntry | None = None,
    commit: bool = True,
) -> Booking:
    """새 슬롯 예약 성공 시에만 기존 예약을 취소한다(한 트랜잭션). 새 슬롯이 마감이면 기존 예약 유지.

    waitlist_entry: 대기 제안 수락으로 옮기는 경우. 그 대기자에게 선점된 슬롯을 예약할 수 있게 한다.
    """
    _assert_customer_owns(booking, user)
    _assert_changeable_by_customer(booking)
    new_booking = create_booking(
        db,
        user,
        slot_id=new_slot_id,
        subject_id=booking.subject_id,
        result_id=booking.result_id,
        contact_phone=booking.contact_phone,
        pre_questions=booking.pre_questions,
        concern_tags=booking.concern_tags,
        waitlist_entry=waitlist_entry,
        exclude_booking_id=booking.id,
        commit=False,
    )
    cancel_booking(db, booking, user, reason="일정 변경", commit=False)
    if commit:
        db.commit()
    return new_booking


def upcoming_booking_for_result(db: Session, customer_id: int, result_id: int) -> Booking | None:
    """결과지당 진행 예정 예약은 최대 1건(정책)이므로 단건 조회."""
    return db.scalars(
        select(Booking).where(
            Booking.customer_id == customer_id,
            Booking.result_id == result_id,
            Booking.status == BookingStatus.CONFIRMED,
        )
    ).first()


def is_changeable_by_customer(booking: Booking) -> bool:
    return booking.status == BookingStatus.CONFIRMED and booking.slot.start_at - now() >= timedelta(
        hours=settings.cancel_deadline_hours
    )


def has_time_conflict(db: Session, customer_id: int, slot: Slot, exclude_booking_id: int | None = None) -> bool:
    """고객이 이 슬롯 시간대에 (옮길 예약을 제외한) 다른 진행 예정 상담을 갖고 있는가."""
    stmt = (
        select(Booking.id)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(
            Booking.customer_id == customer_id,
            Booking.status == BookingStatus.CONFIRMED,
            Slot.start_at < slot.end_at,
            Slot.end_at > slot.start_at,
        )
    )
    if exclude_booking_id:
        stmt = stmt.where(Booking.id != exclude_booking_id)
    return db.scalars(stmt).first() is not None


def confirm_attendance(db: Session, booking: Booking, user: User) -> Booking:
    _assert_customer_owns(booking, user)
    if booking.status != BookingStatus.CONFIRMED:
        raise AppError(400, "INVALID_STATE", "진행 예정인 예약이 아닙니다.")
    booking.attendance_confirmed_at = booking.attendance_confirmed_at or now()
    db.commit()
    return booking


def record_call_attempt(db: Session, booking: Booking) -> Booking:
    if booking.status != BookingStatus.CONFIRMED:
        raise AppError(400, "INVALID_STATE", "진행 예정인 예약이 아닙니다.")
    booking.call_attempts += 1
    db.commit()
    return booking


def mark_no_show(db: Session, booking: Booking) -> Booking:
    if booking.status != BookingStatus.CONFIRMED:
        raise AppError(400, "INVALID_STATE", "진행 예정인 예약이 아닙니다.")
    if booking.slot.start_at > now():
        raise AppError(400, "TOO_EARLY", "상담 시작 시각 이후에 부재 처리할 수 있습니다.")
    if booking.call_attempts < 1:
        raise AppError(400, "CALL_ATTEMPT_REQUIRED", "부재 처리 전 최소 1회 이상 통화 시도를 기록해주세요.")
    booking.status = BookingStatus.NO_SHOW
    notification.cancel_pending_for_booking(db, booking.id)
    db.commit()
    return booking
