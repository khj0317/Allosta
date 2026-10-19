"""가입 전 본인 휴대폰 확인.

흐름: 번호 입력 → 인증번호 발송 → 인증번호 확인 → 일회용 phone_token 발급 → 가입 요청에 토큰 첨부.
토큰은 그 번호에만 묶이고(다른 번호로 가입 불가) 30분 안에 한 번만 쓸 수 있다.
번호·코드·토큰은 모두 해시로만 저장한다.
"""
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import now
from ..errors import AppError
from ..models import PhoneVerification, SmsSendLog, User
from . import notification

TOKEN_MINUTES = 30


def digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def normalize(phone: str) -> str:
    """저장용 표준 형식 010-1234-5678 (10자리는 010-123-4567). 같은 번호가 다른 표기로 중복 저장되지 않게 한다."""
    d = digits(phone)
    mid = 6 if len(d) == 10 else 7
    return f"{d[:3]}-{d[3:mid]}-{d[mid:]}"


def same_phone(a: str | None, b: str | None) -> bool:
    return bool(a and b) and digits(a) == digits(b)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def phone_taken(db: Session, phone: str) -> bool:
    return db.query(User).filter_by(phone=normalize(phone)).count() > 0


def record_sms_send(db: Session, phone: str, purpose: str) -> None:
    """인증번호 문자 1건 발송 전에 호출. 같은 번호로 하루 상한을 넘기면 거부한다(가입·가족 인증 합산).

    30초 재발송 간격만으로는 남의 번호로 하루 종일 문자를 보내는 악용(비용·스팸)을 막지 못한다.
    """
    d = digits(phone)
    since = now() - timedelta(days=1)
    sent = db.query(SmsSendLog).filter(SmsSendLog.phone == d, SmsSendLog.created_at >= since).count()
    if sent >= settings.sms_daily_limit_per_phone:
        raise AppError(429, "DAILY_LIMIT", "이 번호로 오늘 보낼 수 있는 인증번호를 모두 사용했습니다. 내일 다시 시도해주세요.")
    db.add(SmsSendLog(phone=d, purpose=purpose))


SIGNUP = "SIGNUP"
RESET = "RESET"  # 비밀번호 재설정


def _latest(db: Session, d: str, purpose: str) -> PhoneVerification | None:
    return db.scalars(
        select(PhoneVerification)
        .where(PhoneVerification.phone == d, PhoneVerification.purpose == purpose)
        .order_by(PhoneVerification.id.desc())
    ).first()


def send(db: Session, phone: str, purpose: str = SIGNUP) -> str:
    """인증번호 발송. 용도(가입/재설정)별로 따로 관리해 한 용도의 인증을 다른 용도에 쓸 수 없게 한다."""
    d = digits(phone)
    if purpose == SIGNUP and phone_taken(db, d):
        raise AppError(409, "PHONE_TAKEN", "이미 가입된 휴대폰 번호입니다. 로그인해주세요.")
    last = _latest(db, d, purpose)
    if last and now() - last.created_at < timedelta(seconds=settings.family_code_resend_seconds):
        raise AppError(429, "TOO_SOON", "잠시 후 다시 요청해주세요.")
    record_sms_send(db, phone, purpose)
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        PhoneVerification(
            phone=d,
            purpose=purpose,
            code_hash=_h(f"{d}:{code}"),
            expires_at=now() + timedelta(minutes=settings.family_code_minutes),
        )
    )
    db.commit()
    label = "비밀번호 재설정" if purpose == RESET else "휴대폰 인증"
    notification.sms_sender.send(
        phone,
        f"[알로스타] {label}",
        f"인증번호 {code} 를 입력해주세요. ({settings.family_code_minutes}분 이내)"
        + ("\n본인이 요청하지 않았다면 이 문자를 무시하세요." if purpose == RESET else ""),
    )
    return code


def verify(db: Session, phone: str, code: str, purpose: str = SIGNUP) -> str:
    d = digits(phone)
    v = _latest(db, d, purpose)
    if v is None or v.expires_at < now():
        raise AppError(400, "CODE_EXPIRED", "인증번호가 만료되었습니다. 다시 받아주세요.")
    if v.attempts >= settings.family_code_max_attempts:
        raise AppError(429, "TOO_MANY_ATTEMPTS", "입력 횟수를 초과했습니다. 인증번호를 다시 받아주세요.")
    v.attempts += 1
    if not hmac.compare_digest(v.code_hash, _h(f"{d}:{code}")):
        db.commit()
        left = settings.family_code_max_attempts - v.attempts
        raise AppError(400, "CODE_MISMATCH", f"인증번호가 일치하지 않습니다. (남은 횟수 {left}회)")
    token = secrets.token_urlsafe(24)
    v.verified_at = now()
    v.token_hash = _h(token)
    v.expires_at = now() + timedelta(minutes=TOKEN_MINUTES)
    db.commit()
    return token


def consume_token(db: Session, phone: str, token: str, purpose: str = SIGNUP) -> None:
    """인증 후 발급한 일회용 토큰 검증. 그 번호·그 용도로 확인된, 만료·사용 전 토큰이어야 한다."""
    v = db.scalars(select(PhoneVerification).where(PhoneVerification.token_hash == _h(token or ""))).first()
    if v is None or v.phone != digits(phone) or v.purpose != purpose or v.used_at is not None or v.expires_at < now():
        raise AppError(400, "PHONE_NOT_VERIFIED", "휴대폰 인증을 먼저 완료해주세요.")
    v.used_at = now()
