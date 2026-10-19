"""관리자: 상담사 계정 발급·수정·비활성화.

상담사는 회원가입으로 만들 수 없고(권한 상승 방지) 운영자가 발급한다.
발급 시 임시 비밀번호를 한 번만 보여주고, 상담사는 첫 로그인 후 반드시 비밀번호를 바꾼다.
"""
import secrets
import string

from fastapi import APIRouter
from sqlalchemy import func, select

from ..constants import is_protected_demo_account
from ..db import now
from ..errors import AppError, not_found
from ..models import Booking, BookingStatus, Counselor, Role, Slot, User
from ..schemas import CounselorAdminOut, CounselorCreatedOut, CounselorCreateIn, CounselorPatchIn
from ..security import AdminUser, DbSession, hash_password
from ..services import phone as phone_svc
from ..services import waitlist as waitlist_svc

router = APIRouter(prefix="/api/admin/counselors", tags=["admin"])


def _upcoming(db, counselor_id: int) -> int:
    return db.scalar(
        select(func.count(Booking.id))
        .join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.counselor_id == counselor_id, Booking.status == BookingStatus.CONFIRMED, Slot.start_at > now())
    )


def _out(db, c: Counselor) -> CounselorAdminOut:
    return CounselorAdminOut(
        id=c.id,
        name=c.user.name,
        email=c.user.email,
        phone=c.user.phone,
        specialties=c.specialties,
        bio=c.bio,
        active=c.active,
        must_change_password=c.user.must_change_password,
        upcoming_bookings=_upcoming(db, c.id),
    )


def _temp_password() -> str:
    # 정책(영문+숫자 8자 이상)을 항상 만족하도록 영문·숫자를 하나씩 보장
    alphabet = string.ascii_letters + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(8))
    return secrets.choice(string.ascii_letters) + secrets.choice(string.digits) + body


@router.get("", response_model=list[CounselorAdminOut])
def list_counselors(user: AdminUser, db: DbSession):
    rows = db.scalars(select(Counselor).order_by(Counselor.active.desc(), Counselor.id)).all()
    return [_out(db, c) for c in rows]


@router.post("", response_model=CounselorCreatedOut, status_code=201)
def create_counselor(body: CounselorCreateIn, user: AdminUser, db: DbSession):
    if db.query(User).filter_by(email=body.email).count():
        raise AppError(409, "EMAIL_TAKEN", "이미 사용 중인 이메일입니다.")
    if phone_svc.phone_taken(db, body.phone):
        raise AppError(409, "PHONE_TAKEN", "이미 사용 중인 휴대폰 번호입니다.")
    temp = _temp_password()
    u = User(
        email=body.email,
        name=body.name,
        phone=phone_svc.normalize(body.phone),
        role=Role.COUNSELOR,
        password_hash=hash_password(temp),
        must_change_password=True,
    )
    c = Counselor(user=u, specialties=[s.value for s in body.specialties], bio=body.bio)
    db.add(c)
    db.commit()
    return CounselorCreatedOut(counselor=_out(db, c), temp_password=temp)


@router.patch("/{counselor_id}", response_model=CounselorAdminOut)
def update_counselor(counselor_id: int, body: CounselorPatchIn, user: AdminUser, db: DbSession):
    c = db.get(Counselor, counselor_id)
    if c is None:
        raise not_found("상담사")
    if body.active is False and c.active and is_protected_demo_account(c.user.email):
        raise AppError(403, "DEMO_ACCOUNT", "시연용 데모 상담사는 비활성화할 수 없습니다. 새로 발급한 상담사로 시험해주세요.")
    if body.active is False and c.active:
        # 예정 상담이 남은 채로 비활성화하면 고객은 예약을 믿고 기다리는데 전화할 사람이 없어진다
        upcoming = _upcoming(db, c.id)
        if upcoming:
            raise AppError(
                409,
                "HAS_UPCOMING",
                f"예정된 상담 {upcoming}건이 남아 있습니다. 먼저 고객에게 안내 후 운영 취소해주세요.",
                upcoming=upcoming,
            )
    if body.active is not None:
        c.active = body.active
        if not body.active:
            db.flush()
            # 이 상담사 시간으로 제안 중이던 대기는 수락해도 예약이 안 되므로 거둬들인다
            waitlist_svc.release_offers_for_counselor(db, c.id)
    if body.specialties is not None:
        c.specialties = [s.value for s in body.specialties]
    if body.bio is not None:
        c.bio = body.bio
    db.commit()
    return _out(db, c)
