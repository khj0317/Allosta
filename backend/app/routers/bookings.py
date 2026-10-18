"""고객: 예약 가능 슬롯 조회, 예약/변경/취소, 참석 확인, 상담 결과 열람."""
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..errors import forbidden, not_found
from ..models import Booking, Indicator, RecordStatus, ServiceType, Slot
from ..schemas import (
    BookingIn,
    BookingOut,
    CancelIn,
    CustomerRecordOut,
    IndicatorOut,
    ProductOut,
    RescheduleIn,
    SlotOut,
)
from ..security import CustomerUser, DbSession
from ..services import booking as svc

router = APIRouter(prefix="/api", tags=["bookings"])


def booking_out(b: Booking) -> BookingOut:
    return BookingOut.from_booking(b, can_change=svc.is_changeable_by_customer(b))


@router.get("/slots/available", response_model=list[SlotOut])
def list_available(
    db: DbSession,
    service_type: ServiceType,
    date_from: date,
    date_to: date | None = None,
    counselor_id: int | None = None,
):
    date_to = min(date_to or date_from, date_from + timedelta(days=31))
    return [SlotOut.from_slot(s) for s in svc.available_slots(db, service_type, date_from, date_to, counselor_id)]


@router.get("/slots/calendar")
def availability_calendar(db: DbSession, service_type: ServiceType, date_from: date, days: int = Query(28, le=62)):
    """날짜별 남은 슬롯 수. 달력에서 '마감' 날짜를 미리 보여줘 헛걸음을 줄인다."""
    slots = svc.available_slots(db, service_type, date_from, date_from + timedelta(days=days - 1))
    counts: dict[str, int] = defaultdict(int)
    for s in slots:
        counts[s.start_at.date().isoformat()] += 1
    return [
        {"date": (date_from + timedelta(days=i)).isoformat(), "available": counts.get((date_from + timedelta(days=i)).isoformat(), 0)}
        for i in range(days)
    ]


@router.post("/bookings", response_model=BookingOut, status_code=201)
def create_booking(body: BookingIn, user: CustomerUser, db: DbSession):
    b = svc.create_booking(db, user, **body.model_dump())
    return booking_out(b)


@router.get("/bookings/me", response_model=list[BookingOut])
def my_bookings(user: CustomerUser, db: DbSession):
    rows = db.scalars(
        select(Booking)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.customer_id == user.id)
        .options(joinedload(Booking.slot), joinedload(Booking.record))
        .order_by(Slot.start_at.desc())
    ).unique().all()
    return [booking_out(b) for b in rows]


def _own(db, user, booking_id: int) -> Booking:
    b = db.get(Booking, booking_id)
    if b is None:
        raise not_found("예약")
    if b.customer_id != user.id:
        raise forbidden()
    return b


@router.get("/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, user: CustomerUser, db: DbSession):
    return booking_out(_own(db, user, booking_id))


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel(booking_id: int, body: CancelIn, user: CustomerUser, db: DbSession):
    return booking_out(svc.cancel_booking(db, _own(db, user, booking_id), user, body.reason))


@router.post("/bookings/{booking_id}/reschedule", response_model=BookingOut)
def reschedule(booking_id: int, body: RescheduleIn, user: CustomerUser, db: DbSession):
    return booking_out(svc.reschedule_booking(db, _own(db, user, booking_id), user, body.slot_id))


@router.post("/bookings/{booking_id}/confirm-attendance", response_model=BookingOut)
def confirm_attendance(booking_id: int, user: CustomerUser, db: DbSession):
    return booking_out(svc.confirm_attendance(db, _own(db, user, booking_id), user))


@router.get("/bookings/{booking_id}/record", response_model=CustomerRecordOut | None)
def customer_record(booking_id: int, user: CustomerUser, db: DbSession):
    b = _own(db, user, booking_id)
    r = b.record
    if r is None or r.status != RecordStatus.SUBMITTED:
        return None
    indicators = (
        db.scalars(select(Indicator).where(Indicator.id.in_(r.discussed_indicator_ids))).all()
        if r.discussed_indicator_ids
        else []
    )
    return CustomerRecordOut(
        customer_message=r.customer_message,
        lifestyle_advice=r.lifestyle_advice,
        follow_up_needed=r.follow_up_needed,
        follow_up_date=r.follow_up_date,
        discussed_indicators=[IndicatorOut.model_validate(i) for i in indicators],
        recommended_products=[ProductOut.model_validate(x.product) for x in r.recommendations],
        submitted_at=r.submitted_at,
    )
