"""대기 신청(Waitlist) 서비스.

원하는 시간대가 가득 찬 고객이 이탈하지 않도록 '날짜 + 희망 시간대'로 대기를 걸어두면,
빈자리가 생기는 순간(취소/신규 슬롯 오픈) 선착순 1명에게 슬롯을 일정 시간 선점(hold)해 제안한다.

- 제안 시 동시에 여러 명에게 알리면 먼저 누른 사람만 성공하고 나머지는 실망 → 1명씩 순차 제안.
- 제안 유효시간이 지나면 다음 대기자에게 넘어간다(스케줄러가 처리).
- 이미 같은 결과지로 예약이 있는 고객도 '더 원하는 시간'으로 대기할 수 있다.
  이 경우 제안을 수락하면 새 예약이 아니라 기존 예약을 제안 시간으로 '변경'한다.
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import now
from ..errors import AppError, forbidden
from ..models import (
    Booking,
    BookingStatus,
    NotificationType,
    Slot,
    SlotStatus,
    User,
    WaitlistEntry,
    WaitlistStatus,
)
from . import booking as booking_service
from . import notification


def join(
    db: Session,
    customer: User,
    *,
    subject_id: int,
    result_id: int,
    desired_date: date,
    start_hour: int,
    end_hour: int,
    counselor_id: int | None,
    contact: str = "OWNER",
    pre_questions: str = "",
) -> WaitlistEntry:
    subject, result = booking_service.load_subject_and_result(db, customer, subject_id, result_id)
    contact_phone = booking_service.resolve_contact_phone(customer, subject, contact)
    if desired_date < now().date():
        raise AppError(400, "INVALID_DATE", "지난 날짜에는 대기 신청할 수 없습니다.")
    if not (0 <= start_hour < end_hour <= 24):
        raise AppError(400, "INVALID_RANGE", "희망 시간대를 확인해주세요.")
    dup = db.scalars(
        select(WaitlistEntry).where(
            WaitlistEntry.customer_id == customer.id,
            WaitlistEntry.result_id == result_id,
            WaitlistEntry.desired_date == desired_date,
            WaitlistEntry.status.in_([WaitlistStatus.WAITING, WaitlistStatus.OFFERED]),
        )
    ).first()
    if dup:
        raise AppError(409, "ALREADY_WAITING", "이미 같은 날짜로 대기 신청하셨습니다.")

    entry = WaitlistEntry(
        customer_id=customer.id,
        subject_id=subject_id,
        result_id=result_id,
        service_type=result.service_type,
        desired_date=desired_date,
        start_hour=start_hour,
        end_hour=end_hour,
        counselor_id=counselor_id,
        contact_phone=contact_phone,
        pre_questions=pre_questions,
    )
    db.add(entry)
    db.flush()
    # 신청 시점에 이미 조건에 맞는 빈 슬롯이 있으면 바로 제안
    for slot in booking_service.available_slots(db, result.service_type, desired_date, desired_date, counselor_id):
        if _matches(entry, slot) and _can_accept(db, entry, slot):
            _offer(db, entry, slot)
            break
    db.commit()
    return entry


def _matches(entry: WaitlistEntry, slot: Slot) -> bool:
    return (
        slot.start_at.date() == entry.desired_date
        and entry.start_hour <= slot.start_at.hour < entry.end_hour
        and entry.service_type.value in slot.counselor.specialties
        and (entry.counselor_id is None or entry.counselor_id == slot.counselor_id)
        and slot.id not in (entry.declined_slot_ids or [])
    )


def _can_accept(db: Session, entry: WaitlistEntry, slot: Slot) -> bool:
    """제안해도 고객이 실제로 수락할 수 있는가. 수락 불가능한 제안은 슬롯만 묶어 다른 대기자의 기회를 뺏는다."""
    current = booking_service.upcoming_booking_for_result(db, entry.customer_id, entry.result_id)
    if current is not None and not booking_service.is_changeable_by_customer(current):
        return False  # 기존 예약이 변경 마감(시작 N시간 전)을 지나 옮길 수 없음
    return not booking_service.has_time_conflict(db, entry.customer_id, slot, current.id if current else None)


def _slot_is_offerable(db: Session, slot: Slot) -> bool:
    t = now()
    if slot.status != SlotStatus.OPEN or slot.start_at < t + timedelta(minutes=settings.booking_lead_minutes):
        return False
    if slot.hold_until and slot.hold_until > t:
        return False
    taken = db.scalars(
        select(Booking.id).where(Booking.slot_id == slot.id, Booking.status != BookingStatus.CANCELLED)
    ).first()
    return taken is None


def _offer(db: Session, entry: WaitlistEntry, slot: Slot) -> None:
    t = now()
    # 제안 유효시간: 기본 N분, 단 예약 마감(리드타임) 이전까지로 제한
    expires = min(
        t + timedelta(minutes=settings.waitlist_offer_minutes),
        slot.start_at - timedelta(minutes=settings.booking_lead_minutes),
    )
    entry.status = WaitlistStatus.OFFERED
    entry.offered_slot_id = slot.id
    entry.offer_expires_at = expires
    slot.held_for_waitlist_id = entry.id
    slot.hold_until = expires
    customer = db.get(User, entry.customer_id)
    notification.enqueue(
        db,
        customer,
        NotificationType.WAITLIST_OFFER,
        "기다리시던 상담 시간에 자리가 났습니다",
        f"{notification.fmt_dt(slot.start_at)} {slot.counselor.user.name} 상담사\n"
        f"{expires:%H:%M}까지 확정하지 않으면 다음 대기자에게 넘어갑니다.\n"
        f"{settings.frontend_url}/my/bookings",
        waitlist_id=entry.id,
        sms_to=entry.contact_phone,
    )


def offer_slot(db: Session, slot: Slot) -> WaitlistEntry | None:
    """빈 슬롯을 조건이 맞는 가장 오래된 대기자에게 제안한다. 커밋은 호출자 책임."""
    if not _slot_is_offerable(db, slot):
        return None
    candidates = db.scalars(
        select(WaitlistEntry)
        .where(
            WaitlistEntry.status == WaitlistStatus.WAITING,
            WaitlistEntry.desired_date == slot.start_at.date(),
        )
        .order_by(WaitlistEntry.created_at, WaitlistEntry.id)
    ).all()
    for entry in candidates:
        if _matches(entry, slot) and _can_accept(db, entry, slot):
            _offer(db, entry, slot)
            return entry
    return None


def _get_own(db: Session, entry_id: int, customer: User) -> WaitlistEntry:
    entry = db.get(WaitlistEntry, entry_id)
    if entry is None or entry.customer_id != customer.id:
        raise forbidden()
    return entry


def _release(db: Session, entry: WaitlistEntry) -> Slot | None:
    slot = db.get(Slot, entry.offered_slot_id) if entry.offered_slot_id else None
    if slot and slot.held_for_waitlist_id == entry.id:
        slot.held_for_waitlist_id = None
        slot.hold_until = None
    entry.offered_slot_id = None
    entry.offer_expires_at = None
    return slot


def accept(db: Session, entry_id: int, customer: User) -> Booking:
    entry = _get_own(db, entry_id, customer)
    if entry.status != WaitlistStatus.OFFERED or entry.offer_expires_at is None or entry.offer_expires_at < now():
        raise AppError(400, "OFFER_EXPIRED", "제안 유효시간이 지났습니다.")
    current = booking_service.upcoming_booking_for_result(db, customer.id, entry.result_id)
    if current is not None:
        # 대기 중 다른 시간을 이미 예약해 둔 경우: 그 예약을 제안 시간으로 옮긴다(비워진 시간은 다음 대기자에게)
        booking = booking_service.reschedule_booking(
            db, current, customer, entry.offered_slot_id, waitlist_entry=entry, commit=False
        )
    else:
        booking = booking_service.create_booking(
            db,
            customer,
            slot_id=entry.offered_slot_id,
            subject_id=entry.subject_id,
            result_id=entry.result_id,
            contact_phone=entry.contact_phone,
            pre_questions=entry.pre_questions,
            waitlist_entry=entry,
            commit=False,
        )
    entry.status = WaitlistStatus.BOOKED
    entry.booking_id = booking.id
    db.commit()
    return booking


def decline(db: Session, entry_id: int, customer: User) -> WaitlistEntry:
    """이번 제안만 거절하고 계속 대기한다. 슬롯은 다음 대기자에게 넘어간다."""
    entry = _get_own(db, entry_id, customer)
    if entry.status != WaitlistStatus.OFFERED:
        raise AppError(400, "INVALID_STATE", "제안 중인 대기가 아닙니다.")
    entry.declined_slot_ids = [*(entry.declined_slot_ids or []), entry.offered_slot_id]
    slot = _release(db, entry)
    entry.status = WaitlistStatus.WAITING
    db.flush()
    if slot:
        offer_slot(db, slot)
    db.commit()
    return entry


def cancel(db: Session, entry_id: int, customer: User) -> WaitlistEntry:
    entry = _get_own(db, entry_id, customer)
    if entry.status not in (WaitlistStatus.WAITING, WaitlistStatus.OFFERED):
        raise AppError(400, "INVALID_STATE", "취소할 수 없는 상태입니다.")
    slot = _release(db, entry)
    entry.status = WaitlistStatus.CANCELLED
    db.flush()
    if slot:
        offer_slot(db, slot)
    db.commit()
    return entry


def process_expirations(db: Session) -> int:
    """스케줄러: 응답 없는 제안 만료 → 다음 대기자에게 넘김, 지난 날짜 대기 만료."""
    t = now()
    count = 0
    for entry in db.scalars(
        select(WaitlistEntry).where(
            WaitlistEntry.status == WaitlistStatus.OFFERED, WaitlistEntry.offer_expires_at < t
        )
    ).all():
        slot = _release(db, entry)
        entry.status = WaitlistStatus.EXPIRED
        db.flush()
        if slot:
            offer_slot(db, slot)
        count += 1
    for entry in db.scalars(
        select(WaitlistEntry).where(
            WaitlistEntry.status == WaitlistStatus.WAITING, WaitlistEntry.desired_date < t.date()
        )
    ).all():
        entry.status = WaitlistStatus.EXPIRED
        count += 1
    db.commit()
    return count
