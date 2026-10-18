"""고객: 피검자(본인/가족) 관리·가족 휴대폰 인증, 결과지 연결/조회."""
import re

from fastapi import APIRouter
from sqlalchemy import select

from ..config import settings
from ..constants import SERVICE_LABELS
from ..errors import forbidden, not_found
from ..models import Booking, IndicatorStatus, Role, Subject, TestResult
from ..schemas import (
    ClaimKitIn,
    FamilyCodeOut,
    FamilyIn,
    ResultDetail,
    ResultSummary,
    SubjectOut,
    VerifyCodeIn,
)
from ..security import CurrentUser, CustomerUser, DbSession
from ..services import family

router = APIRouter(prefix="/api", tags=["customer"])


def result_summary(r: TestResult) -> ResultSummary:
    out = ResultSummary.model_validate(r)
    out.service_label = SERVICE_LABELS[r.service_type]
    out.abnormal_count = sum(i.status != IndicatorStatus.NORMAL for i in r.indicators)
    return out


def result_detail(r: TestResult) -> ResultDetail:
    return ResultDetail(
        **result_summary(r).model_dump(),
        overall_comment=r.overall_comment,
        subject_id=r.subject_id,
        subject_name=r.subject.name if r.subject else None,
        indicators=r.indicators,
    )


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    d = re.sub(r"\D", "", phone)
    return f"{d[:3]}-****-{d[-4:]}" if len(d) >= 10 else phone


def subject_out(s: Subject) -> SubjectOut:
    return SubjectOut(
        id=s.id,
        name=s.name,
        birth_date=s.birth_date,
        relation=s.relation,
        phone_masked=_mask_phone(s.phone),
        consent_at=s.consent_at,
        verify_expires_at=None if s.consent_at else s.verify_expires_at,
        results=[result_summary(r) for r in sorted(s.results, key=lambda r: r.reported_at, reverse=True)],
    )


def _code_out(s: Subject, code: str) -> FamilyCodeOut:
    return FamilyCodeOut(subject=subject_out(s), demo_code=code if settings.demo_mode else None)


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(user: CustomerUser, db: DbSession):
    subjects = db.scalars(select(Subject).where(Subject.owner_id == user.id).order_by(Subject.id)).all()
    return [subject_out(s) for s in subjects]


@router.post("/subjects", response_model=FamilyCodeOut, status_code=201)
def add_family(body: FamilyIn, user: CustomerUser, db: DbSession):
    """가족 등록 → 가족 본인 휴대폰으로 인증번호 발송. 인증 전에는 결과 연결·예약 불가."""
    s, code = family.add_family(db, user, **body.model_dump())
    return _code_out(s, code)


@router.post("/subjects/{subject_id}/verification", response_model=FamilyCodeOut)
def resend_code(subject_id: int, user: CustomerUser, db: DbSession):
    s, code = family.resend_code(db, user, subject_id)
    return _code_out(s, code)


@router.post("/subjects/{subject_id}/verify", response_model=SubjectOut)
def verify_family(subject_id: int, body: VerifyCodeIn, user: CustomerUser, db: DbSession):
    return subject_out(family.verify(db, user, subject_id, body.code))


@router.delete("/subjects/{subject_id}", status_code=204)
def remove_family(subject_id: int, user: CustomerUser, db: DbSession):
    family.remove_family(db, user, subject_id)


@router.post("/subjects/{subject_id}/claim-kit", response_model=SubjectOut)
def claim_kit(subject_id: int, body: ClaimKitIn, user: CustomerUser, db: DbSession):
    """키트 코드로 결과지를 피검자에 연결. 키트에 등록된 이름·생년월일과 일치해야 한다."""
    return subject_out(family.claim_kit(db, user, subject_id, body.kit_code))


@router.get("/results/{result_id}", response_model=ResultDetail)
def get_result(result_id: int, user: CurrentUser, db: DbSession):
    r = db.get(TestResult, result_id)
    if r is None:
        raise not_found("검사 결과")
    if user.role == Role.CUSTOMER:
        if r.subject is None or r.subject.owner_id != user.id:
            raise forbidden()
    elif user.role == Role.COUNSELOR:
        # 상담사는 본인에게 예약된 결과지만 열람(최소 권한 원칙)
        assigned = db.query(Booking).filter_by(result_id=r.id, counselor_id=user.counselor.id).count()
        if not assigned:
            raise forbidden("배정된 상담의 결과지만 열람할 수 있습니다.")
    return result_detail(r)
