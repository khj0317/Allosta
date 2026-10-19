"""상담사/관리자: 일정, 상담 상세, 통화 시도·부재 처리, 상담 기록, 슬롯 관리, 대시보드."""
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..config import settings
from ..db import now
from ..errors import AppError, forbidden, not_found
from ..models import Booking, BookingStatus, Counselor, RecordRevision, Role, Slot, SlotStatus, User
from ..schemas import (
    BookingOut,
    CancelIn,
    CounselorBookingDetail,
    RecordIn,
    RecordOut,
    RevisionOut,
    SlotBulkIn,
    SlotBulkOut,
    SlotPatchIn,
    StaffSlotOut,
)
from ..security import AdminUser, CurrentCounselor, DbSession, StaffUser
from ..services import booking as booking_svc
from ..services import metrics
from ..services import record as record_svc
from ..services import waitlist as waitlist_svc
from .bookings import booking_out
from .customer import result_detail

router = APIRouter(prefix="/api/staff", tags=["staff"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


def _scope_counselor_id(user: User, requested: int | None) -> int | None:
    """상담사는 항상 본인 데이터로 한정, 관리자는 선택 필터."""
    if user.role == Role.COUNSELOR:
        return user.counselor.id
    return requested


def _staff_booking(db, user: User, booking_id: int) -> Booking:
    b = db.get(Booking, booking_id)
    if b is None:
        raise not_found("예약")
    if user.role == Role.COUNSELOR and b.counselor_id != user.counselor.id:
        raise forbidden("본인에게 배정된 상담만 접근할 수 있습니다.")
    return b


@router.get("/bookings/overdue", response_model=list[BookingOut])
def overdue_bookings(user: StaffUser, db: DbSession, counselor_id: int | None = None):
    """상담 시간이 지났는데 완료(기록 제출)·부재 처리가 안 된 예약. 기간 제한 없이 모두 보여준다.

    처리되지 않으면 고객은 요약을 못 받고, 대시보드에서는 '예정'으로 잘못 집계된다.
    """
    stmt = (
        select(Booking)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.status == BookingStatus.CONFIRMED, Slot.end_at <= now())
        .options(joinedload(Booking.slot), joinedload(Booking.record))
        .order_by(Slot.start_at)
    )
    cid = _scope_counselor_id(user, counselor_id)
    if cid:
        stmt = stmt.where(Booking.counselor_id == cid)
    return [booking_out(b) for b in db.scalars(stmt).unique().all()]


@router.get("/bookings", response_model=list[BookingOut])
def list_bookings(
    user: StaffUser,
    db: DbSession,
    date_from: date,
    date_to: date,
    counselor_id: int | None = None,
    status: BookingStatus | None = None,
):
    stmt = (
        select(Booking)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(
            Slot.start_at >= datetime.combine(date_from, time.min),
            Slot.start_at < datetime.combine(date_to + timedelta(days=1), time.min),
        )
        .options(joinedload(Booking.slot), joinedload(Booking.record))
        .order_by(Slot.start_at)
    )
    cid = _scope_counselor_id(user, counselor_id)
    if cid:
        stmt = stmt.where(Booking.counselor_id == cid)
    if status:
        stmt = stmt.where(Booking.status == status)
    return [booking_out(b) for b in db.scalars(stmt).unique().all()]


@router.get("/bookings/{booking_id}", response_model=CounselorBookingDetail)
def booking_detail(booking_id: int, user: StaffUser, db: DbSession):
    b = _staff_booking(db, user, booking_id)
    # 같은 피검자의 지난 상담 이력: 상담사가 바뀌어도 맥락이 이어지도록
    past = db.scalars(
        select(Booking)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.subject_id == b.subject_id, Booking.id != b.id, Booking.status == BookingStatus.COMPLETED)
        .order_by(Slot.start_at.desc())
    ).all()
    return CounselorBookingDetail(
        booking=booking_out(b),
        result=result_detail(b.result),
        customer_phone=b.customer.phone,
        past_bookings=[booking_out(p) for p in past],
        record=RecordOut.model_validate(b.record) if b.record else None,
        record_editable_until=record_svc.editable_until(b.record) if b.record else None,
        revisions=[
            RevisionOut(id=r.id, editor_name=r.editor.name, reason=r.reason, changed_fields=r.changed_fields,
                        created_at=r.created_at)
            for r in db.scalars(
                select(RecordRevision).where(RecordRevision.record_id == b.record.id).order_by(RecordRevision.id.desc())
            )
        ] if b.record else [],
    )


@router.post("/bookings/{booking_id}/call-attempt", response_model=BookingOut)
def call_attempt(booking_id: int, user: StaffUser, db: DbSession):
    return booking_out(booking_svc.record_call_attempt(db, _staff_booking(db, user, booking_id)))


@router.post("/bookings/{booking_id}/no-show", response_model=BookingOut)
def no_show(booking_id: int, user: StaffUser, db: DbSession):
    return booking_out(booking_svc.mark_no_show(db, _staff_booking(db, user, booking_id)))


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
def staff_cancel(booking_id: int, body: CancelIn, user: StaffUser, db: DbSession):
    if not body.reason.strip():
        raise AppError(400, "REASON_REQUIRED", "운영자 취소 시 사유는 필수입니다(고객에게 안내됨).")
    return booking_out(booking_svc.cancel_booking(db, _staff_booking(db, user, booking_id), user, body.reason))


# ---------------------------------------------------------------- 상담 기록 (상담사 본인만)

@router.put("/bookings/{booking_id}/record", response_model=RecordOut)
def save_record(booking_id: int, body: RecordIn, counselor: CurrentCounselor, db: DbSession):
    b = record_svc.get_booking_for_counselor(db, booking_id, counselor)
    return record_svc.save(db, b, body, counselor.user)


@router.post("/bookings/{booking_id}/record/submit", response_model=RecordOut)
def submit_record(booking_id: int, body: RecordIn, counselor: CurrentCounselor, db: DbSession):
    b = record_svc.get_booking_for_counselor(db, booking_id, counselor)
    return record_svc.submit(db, b, body, counselor.user)


# ---------------------------------------------------------------- 슬롯 관리

@router.get("/slots", response_model=list[StaffSlotOut])
def list_slots(user: StaffUser, db: DbSession, date_from: date, date_to: date, counselor_id: int | None = None):
    stmt = (
        select(Slot)
        .where(
            Slot.start_at >= datetime.combine(date_from, time.min),
            Slot.start_at < datetime.combine(date_to + timedelta(days=1), time.min),
        )
        .options(joinedload(Slot.counselor).joinedload(Counselor.user))
        .order_by(Slot.start_at, Slot.counselor_id)
    )
    cid = _scope_counselor_id(user, counselor_id)
    if cid:
        stmt = stmt.where(Slot.counselor_id == cid)
    slots = db.scalars(stmt).unique().all()
    active = {
        b.slot_id: b
        for b in db.scalars(
            select(Booking).where(
                Booking.slot_id.in_([s.id for s in slots]), Booking.status != BookingStatus.CANCELLED
            )
        ).all()
    } if slots else {}
    out = []
    for s in slots:
        b = active.get(s.id)
        out.append(
            StaffSlotOut(
                **_slot_fields(s),
                status=s.status,
                booking_id=b.id if b else None,
                booking_customer=b.customer.name if b else None,
                hold_until=s.hold_until,
            )
        )
    return out


def _slot_fields(s: Slot) -> dict:
    return {
        "id": s.id,
        "counselor_id": s.counselor_id,
        "counselor_name": s.counselor.user.name,
        "start_at": s.start_at,
        "end_at": s.end_at,
    }


def _parse_hm(v: str) -> time:
    try:
        h, m = v.split(":")
        return time(int(h), int(m))
    except ValueError:
        raise AppError(400, "INVALID_TIME", f"시간 형식이 올바르지 않습니다: {v}")


@router.post("/slots/bulk", response_model=SlotBulkOut)
def bulk_create_slots(body: SlotBulkIn, user: StaffUser, db: DbSession):
    """근무 템플릿(요일·근무시간·휴게시간)으로 슬롯을 일괄 생성. 기존 슬롯과 겹치면 건너뛴다(멱등)."""
    cid = _scope_counselor_id(user, body.counselor_id)
    if cid is None:
        raise AppError(400, "COUNSELOR_REQUIRED", "상담사를 선택해주세요.")
    target = db.get(Counselor, cid)
    if target is None:
        raise not_found("상담사")
    if not target.active:
        raise AppError(400, "COUNSELOR_INACTIVE", "비활성화된 상담사의 상담 시간은 만들 수 없습니다.")
    if body.date_to < body.date_from or (body.date_to - body.date_from).days > 62:
        raise AppError(400, "INVALID_RANGE", "기간은 최대 62일까지 지정할 수 있습니다.")
    if body.date_from < now().date():
        raise AppError(400, "PAST_DATE", "지난 날짜에는 상담 시간을 만들 수 없습니다.")

    start_t, end_t = _parse_hm(body.start_time), _parse_hm(body.end_time)
    brk = (
        (_parse_hm(body.break_start), _parse_hm(body.break_end)) if body.break_start and body.break_end else None
    )
    step = timedelta(minutes=settings.slot_minutes)
    existing = set(
        db.scalars(
            select(Slot.start_at).where(
                Slot.counselor_id == cid,
                Slot.start_at >= datetime.combine(body.date_from, time.min),
                Slot.start_at < datetime.combine(body.date_to + timedelta(days=1), time.min),
            )
        ).all()
    )
    created: list[Slot] = []
    skipped = 0
    d = body.date_from
    while d <= body.date_to:
        if d.weekday() in body.weekdays:
            cur = datetime.combine(d, start_t)
            while cur + step <= datetime.combine(d, end_t):
                in_break = brk and datetime.combine(d, brk[0]) <= cur < datetime.combine(d, brk[1])
                if in_break:
                    cur += step
                    continue
                if cur in existing:
                    skipped += 1
                else:
                    slot = Slot(counselor_id=cid, start_at=cur, end_at=cur + step)
                    db.add(slot)
                    created.append(slot)
                cur += step
        d += timedelta(days=1)
    db.flush()
    # 새로 열린 슬롯을 대기자에게 우선 제안 → 대기 고객 회수
    offers = sum(1 for s in created if waitlist_svc.offer_slot(db, s))
    db.commit()
    return SlotBulkOut(created=len(created), skipped=skipped, waitlist_offers=offers)


@router.patch("/slots/{slot_id}", response_model=StaffSlotOut)
def patch_slot(slot_id: int, body: SlotPatchIn, user: StaffUser, db: DbSession):
    s = db.get(Slot, slot_id)
    if s is None:
        raise not_found("슬롯")
    if s.start_at <= now():
        raise AppError(400, "PAST_SLOT", "이미 지난 시간은 열거나 닫을 수 없습니다.")
    if body.status == SlotStatus.OPEN and not s.counselor.active:
        raise AppError(400, "COUNSELOR_INACTIVE", "비활성화된 상담사의 시간은 열 수 없습니다.")
    if user.role == Role.COUNSELOR and s.counselor_id != user.counselor.id:
        raise forbidden()
    booked = db.scalars(
        select(Booking).where(Booking.slot_id == s.id, Booking.status != BookingStatus.CANCELLED)
    ).first()
    if body.status == SlotStatus.BLOCKED and booked:
        raise AppError(409, "SLOT_BOOKED", "예약이 있는 슬롯은 닫을 수 없습니다. 예약을 먼저 취소(사유 안내)해주세요.")
    if body.status == SlotStatus.BLOCKED and s.held_for_waitlist_id:
        raise AppError(409, "SLOT_HELD", "대기자에게 제안 중인 슬롯입니다. 제안 만료 후 다시 시도해주세요.")
    s.status = body.status
    db.flush()
    if body.status == SlotStatus.OPEN:
        waitlist_svc.offer_slot(db, s)
    db.commit()
    return StaffSlotOut(**_slot_fields(s), status=s.status, hold_until=s.hold_until)


# ---------------------------------------------------------------- 대시보드

@admin_router.get("/dashboard")
def dashboard(user: AdminUser, db: DbSession, date_from: date, date_to: date):
    if date_to < date_from or (date_to - date_from).days > 180:
        raise AppError(400, "INVALID_RANGE", "기간은 최대 180일까지 조회할 수 있습니다.")
    return metrics.dashboard(db, date_from, date_to)
