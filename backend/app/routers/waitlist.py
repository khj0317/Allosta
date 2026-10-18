from fastapi import APIRouter
from sqlalchemy import select

from ..models import WaitlistEntry, WaitlistStatus
from ..schemas import BookingOut, SlotOut, WaitlistIn, WaitlistOut
from ..security import CustomerUser, DbSession
from ..services import waitlist as svc
from ..services.booking import upcoming_booking_for_result
from .bookings import booking_out

router = APIRouter(prefix="/api/waitlist", tags=["waitlist"])


def waitlist_out(db, e: WaitlistEntry) -> WaitlistOut:
    computed = ("subject_name", "offered_slot", "current_booking")
    data = {k: getattr(e, k) for k in WaitlistOut.model_fields if k not in computed}
    current = (
        upcoming_booking_for_result(db, e.customer_id, e.result_id)
        if e.status in (WaitlistStatus.WAITING, WaitlistStatus.OFFERED)
        else None
    )
    return WaitlistOut(
        **data,
        subject_name=e.subject.name,
        offered_slot=SlotOut.from_slot(e.offered_slot) if e.offered_slot else None,
        current_booking=SlotOut.from_slot(current.slot) if current else None,
    )


@router.post("", response_model=WaitlistOut, status_code=201)
def join(body: WaitlistIn, user: CustomerUser, db: DbSession):
    return waitlist_out(db, svc.join(db, user, **body.model_dump()))


@router.get("/me", response_model=list[WaitlistOut])
def mine(user: CustomerUser, db: DbSession):
    rows = db.scalars(
        select(WaitlistEntry).where(WaitlistEntry.customer_id == user.id).order_by(WaitlistEntry.created_at.desc())
    ).all()
    return [waitlist_out(db, e) for e in rows]


@router.post("/{entry_id}/accept", response_model=BookingOut)
def accept(entry_id: int, user: CustomerUser, db: DbSession):
    return booking_out(svc.accept(db, entry_id, user))


@router.post("/{entry_id}/decline", response_model=WaitlistOut)
def decline(entry_id: int, user: CustomerUser, db: DbSession):
    return waitlist_out(db, svc.decline(db, entry_id, user))


@router.post("/{entry_id}/cancel", response_model=WaitlistOut)
def cancel(entry_id: int, user: CustomerUser, db: DbSession):
    return waitlist_out(db, svc.cancel(db, entry_id, user))
