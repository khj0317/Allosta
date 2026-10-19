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
    FamilyAddIn,
    FamilyCodeOut,
    FamilyIn,
    ResultDetail,
    ResultSummary,
    SubjectOut,
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
        results=[result_summary(r) for r in sorted(s.results, key=lambda r: r.reported_at, reverse=True)],
    )


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(user: CustomerUser, db: DbSession):
    subjects = db.scalars(select(Subject).where(Subject.owner_id == user.id).order_by(Subject.id)).all()
    return [subject_out(s) for s in subjects]


@router.post("/subjects/verification", response_model=FamilyCodeOut)
def send_family_code(body: FamilyIn, user: CustomerUser, db: DbSession):
    """가족 등록 1단계: 가족 본인 휴대폰으로 인증번호 발송(아직 등록되지 않음)."""
    code, v = family.request_code(db, user, **body.model_dump())
    return FamilyCodeOut(expires_at=v.expires_at, demo_code=code if settings.demo_mode else None)


@router.post("/subjects", response_model=SubjectOut, status_code=201)
def add_family(body: FamilyAddIn, user: CustomerUser, db: DbSession):
    """가족 등록 2단계: 인증번호가 맞으면 그때 가족으로 등록된다."""
    return subject_out(family.add_family(db, user, **body.model_dump()))


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
