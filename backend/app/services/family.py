"""가족 피검자 등록·본인 확인·결과 연결.

'진짜 가족만' 등록되도록 두 겹으로 막는다.
1) 가족 본인 휴대폰 인증: 가족의 휴대폰으로 인증번호를 보내고, 가족이 계정 소유자에게 알려준 번호를 입력해야
   그때 가족으로 등록된다(인증 전에는 목록에 생기지 않음). 체크박스 자기 확인과 달리 그 사람의 휴대폰을 가진 실제 인물이 동의했다는 근거가 남는다.
2) 키트 등록 정보 대조: 검체 접수 때 등록된 이름·생년월일과 일치하는 피검자에게만 결과지를 연결한다.
   인증을 통과한 가족이라도 다른 사람의 결과를 가져올 수 없다.
"""
import hashlib
import hmac
import logging
import re
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import now
from ..errors import AppError, not_found
from ..models import Booking, KitClaimFailure, PhoneVerification, Relation, Subject, TestResult, User
from . import notification
from .phone import normalize, record_sms_send, same_phone

log = logging.getLogger("allostar.family")


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)


FAMILY = "FAMILY"


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", "", name)


def _hash(owner_id: int, phone: str, name: str, birth_date, code: str) -> str:
    # 요청한 계정·가족 정보까지 섞는다: 문자에 적힌 사람(이름)과 다른 정보로 등록하거나 다른 계정이 쓰는 것을 막는다
    return hashlib.sha256(f"{owner_id}:{_digits(phone)}:{_norm_name(name)}:{birth_date}:{code}".encode()).hexdigest()


def own_subject(db: Session, user: User, subject_id: int) -> Subject:
    s = db.get(Subject, subject_id)
    if s is None or s.owner_id != user.id:
        raise not_found("피검자")
    return s


def _check_new_family(db: Session, owner: User, relation: Relation, phone: str) -> None:
    if relation == Relation.SELF:
        raise AppError(400, "INVALID_RELATION", "본인은 가입 시 자동으로 등록됩니다.")
    family = db.query(Subject).filter(Subject.owner_id == owner.id, Subject.relation != Relation.SELF).all()
    if len(family) >= settings.max_family_members:
        raise AppError(400, "FAMILY_LIMIT", f"가족은 최대 {settings.max_family_members}명까지 등록할 수 있습니다.")
    if _digits(phone) == _digits(owner.phone):
        raise AppError(400, "OWN_PHONE", "가족 본인의 휴대폰 번호를 입력해주세요. 인증번호가 그 번호로 발송됩니다.")
    if any(f.phone and _digits(f.phone) == _digits(phone) for f in family):
        raise AppError(409, "PHONE_IN_USE", "이미 다른 가족에게 등록된 휴대폰 번호입니다.")


def _latest(db: Session, owner: User, phone: str) -> PhoneVerification | None:
    return db.scalars(
        select(PhoneVerification)
        .where(PhoneVerification.phone == _digits(phone), PhoneVerification.purpose == FAMILY,
               PhoneVerification.owner_id == owner.id)
        .order_by(PhoneVerification.id.desc())
    ).first()


def request_code(db: Session, owner: User, *, name: str, relation: Relation, birth_date, phone: str) -> tuple[str, PhoneVerification]:
    """가족 등록 1단계: 가족 본인 휴대폰으로 인증번호 발송. 아직 가족 목록에는 아무것도 생기지 않는다."""
    _check_new_family(db, owner, relation, phone)
    last = _latest(db, owner, phone)
    if last and now() - last.created_at < timedelta(seconds=settings.family_code_resend_seconds):
        raise AppError(429, "TOO_SOON", "잠시 후 다시 요청해주세요.")
    record_sms_send(db, phone, FAMILY)
    code = f"{secrets.randbelow(1_000_000):06d}"
    v = PhoneVerification(
        phone=_digits(phone),
        purpose=FAMILY,
        owner_id=owner.id,
        code_hash=_hash(owner.id, phone, name, birth_date, code),
        expires_at=now() + timedelta(minutes=settings.family_code_minutes),
    )
    db.add(v)
    db.commit()
    # 수신자가 서비스 회원이 아닐 수 있어 아웃박스(회원 알림함) 대신 발송기로 바로 보낸다.
    notification.sms_sender.send(
        phone,
        "[알로스타] 가족 등록 확인",
        f"{owner.name}님이 회원님({name.strip()})을 가족으로 등록해 검사 결과 상담을 받으려고 합니다.\n"
        f"동의하시면 인증번호 {code} 를 {owner.name}님께 알려주세요. ({settings.family_code_minutes}분 이내)\n"
        f"본인이 요청한 것이 아니라면 이 문자를 무시하세요.",
    )
    return code, v


def add_family(db: Session, owner: User, *, name: str, relation: Relation, birth_date, phone: str, code: str) -> Subject:
    """가족 등록 2단계: 인증번호가 맞아야 그때 가족(동의 완료)으로 등록된다.

    '등록 먼저, 인증은 나중'이면 확인되지 않은 사람이 가족 목록에 남는다. 인증을 등록의 조건으로 묶어
    목록에 있는 가족은 모두 휴대폰 주인이 동의한 사람이 되게 한다.
    """
    _check_new_family(db, owner, relation, phone)
    v = _latest(db, owner, phone)
    if v is None or v.used_at is not None or v.expires_at < now():
        raise AppError(400, "CODE_EXPIRED", "인증번호가 만료되었습니다. 다시 받아주세요.")
    if v.attempts >= settings.family_code_max_attempts:
        raise AppError(429, "TOO_MANY_ATTEMPTS", "입력 횟수를 초과했습니다. 인증번호를 다시 받아주세요.")
    v.attempts += 1
    if not hmac.compare_digest(v.code_hash, _hash(owner.id, phone, name, birth_date, code)):
        db.commit()
        left = settings.family_code_max_attempts - v.attempts
        raise AppError(400, "CODE_MISMATCH", f"인증번호가 일치하지 않습니다. (남은 횟수 {left}회)")
    v.verified_at = v.used_at = now()
    s = Subject(owner_id=owner.id, name=name.strip(), relation=relation, birth_date=birth_date,
                phone=normalize(phone), consent_at=now())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def remove_family(db: Session, owner: User, subject_id: int) -> None:
    s = own_subject(db, owner, subject_id)
    if s.relation == Relation.SELF:
        raise AppError(400, "CANNOT_REMOVE_SELF", "본인 프로필은 삭제할 수 없습니다.")
    if s.results or db.query(Booking).filter_by(subject_id=s.id).count():
        raise AppError(409, "HAS_HISTORY", "결과지나 상담 이력이 있는 가족은 삭제할 수 없습니다.")
    db.delete(s)
    db.commit()


def subject_phone(s: Subject) -> str | None:
    """피검자의 인증된 휴대폰: 본인은 계정(가입 시 인증) 번호, 가족은 가족 인증을 마친 번호."""
    if s.consent_at is None:
        return None
    return s.phone


def kit_matches(r: TestResult, s: Subject) -> bool:
    """키트 접수 때 등록된 검사자 = 이 피검자인가.

    이름·생년월일은 가족·지인이 쉽게 알 수 있어 그것만으로는 '남의 이름으로 본인 가입'을 막지 못한다.
    그래서 등록 휴대폰이 있으면 피검자의 '인증된' 휴대폰과도 일치해야 한다.
    """
    if r.registered_name is None:
        return True  # 미등록 키트
    if _norm_name(r.registered_name) != _norm_name(s.name) or r.registered_birth_date != s.birth_date:
        return False
    return r.registered_phone is None or same_phone(r.registered_phone, subject_phone(s))


KIT_FAIL_MESSAGE = (
    "결과지를 연결하지 못했습니다. 키트 코드를 확인하고, 코드가 맞다면 키트 접수 때 등록한 "
    "이름·생년월일·휴대폰이 이 피검자 정보와 같은지 확인해주세요."
)


def _kit_failures_today(db: Session, owner: User) -> int:
    return db.query(KitClaimFailure).filter(
        KitClaimFailure.owner_id == owner.id, KitClaimFailure.created_at >= now() - timedelta(days=1)
    ).count()


def _fail_kit_claim(db: Session, owner: User) -> AppError:
    db.add(KitClaimFailure(owner_id=owner.id))
    db.commit()
    return AppError(400, "KIT_CLAIM_FAILED", KIT_FAIL_MESSAGE)


def claim_kit(db: Session, owner: User, subject_id: int, kit_code: str) -> Subject:
    """키트 코드로 결과 연결.

    키트 코드는 순번 형식이라 추측하기 쉽다. 그래서
    - '없는 코드 / 남에게 연결된 코드 / 정보 불일치'를 같은 메시지로 응답해 어떤 코드가 존재하는지 알 수 없게 하고
    - 계정당 하루 실패 횟수를 제한한다.
    """
    s = own_subject(db, owner, subject_id)
    if s.consent_at is None:
        raise AppError(400, "NOT_VERIFIED", f"{s.name}님의 휴대폰 인증을 먼저 완료해주세요.")
    if _kit_failures_today(db, owner) >= settings.kit_claim_daily_failures:
        raise AppError(429, "TOO_MANY_KIT_ATTEMPTS", "키트 연결에 여러 번 실패했습니다. 내일 다시 시도하거나 고객센터로 문의해주세요.")
    r = db.query(TestResult).filter_by(kit_code=kit_code.strip().upper()).one_or_none()
    if r is not None and r.subject_id == s.id:
        return s  # 이미 이 피검자에 연결됨(같은 요청 반복)
    if r is None or r.subject_id is not None or not kit_matches(r, s):
        raise _fail_kit_claim(db, owner)
    if r.registered_name is None:
        r.registered_name = s.name
        r.registered_birth_date = s.birth_date
        r.registered_phone = subject_phone(s)
    r.subject_id = s.id
    db.commit()
    db.refresh(s)
    return s
