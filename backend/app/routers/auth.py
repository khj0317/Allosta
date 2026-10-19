from datetime import timedelta

from fastapi import APIRouter

from ..db import now
from ..errors import AppError
from ..models import Relation, Role, Subject, User
from ..config import settings
from ..schemas import (
    LoginIn,
    PasswordChangeIn,
    PhoneSendIn,
    PhoneVerifyIn,
    ResetIn,
    ResetSendIn,
    ResetVerifyIn,
    SignupIn,
    TokenOut,
    UserOut,
)
from ..security import CurrentUser, DbSession, create_token, hash_password, verify_password
from ..services import phone as phone_svc

router = APIRouter(prefix="/api/auth", tags=["auth"])


def to_user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.counselor_id = user.counselor.id if user.counselor else None
    return out


def _lock_message(user: User) -> str:
    mins = max(1, int((user.locked_until - now()).total_seconds() // 60) + 1)
    return f"로그인에 {settings.login_max_failures}회 실패해 잠겼습니다. 약 {mins}분 후 다시 시도해주세요."


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DbSession):
    """비밀번호 무차별 대입 방지: 계정별 연속 실패 N회면 M분 잠금. 성공하면 실패 횟수 초기화."""
    user = db.query(User).filter_by(email=body.email.strip().lower()).one_or_none()
    if user is None:
        # 가입 여부를 알려주지 않도록 비밀번호 오류와 같은 메시지
        raise AppError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.")
    if user.locked_until and user.locked_until > now():
        raise AppError(423, "ACCOUNT_LOCKED", _lock_message(user))
    if not verify_password(body.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= settings.login_max_failures:
            user.locked_until = now() + timedelta(minutes=settings.login_lock_minutes)
            user.failed_logins = 0
            db.commit()
            raise AppError(423, "ACCOUNT_LOCKED", _lock_message(user))
        db.commit()
        left = settings.login_max_failures - user.failed_logins
        raise AppError(401, "INVALID_CREDENTIALS", f"이메일 또는 비밀번호가 올바르지 않습니다. ({left}회 더 틀리면 잠깁니다)")
    if user.counselor and not user.counselor.active:
        raise AppError(403, "ACCOUNT_DISABLED", "비활성화된 상담사 계정입니다. 운영 관리자에게 문의해주세요.")
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return TokenOut(access_token=create_token(user), user=to_user_out(user))


def _reset_target(db, email: str, phone: str) -> User | None:
    """이메일과 가입 휴대폰이 모두 맞는 계정. 하나라도 다르면 None(어느 쪽이 틀렸는지는 알려주지 않음)."""
    user = db.query(User).filter_by(email=email).one_or_none()
    return user if user and phone_svc.same_phone(user.phone, phone) else None


@router.post("/password-reset/send")
def reset_send(body: ResetSendIn, db: DbSession):
    """비밀번호 찾기 1단계: 가입한 휴대폰으로 인증번호 발송.

    이메일·번호가 맞지 않아도 같은 응답을 돌려줘 가입 여부를 알 수 없게 한다(문자는 실제 계정 번호로만 감).
    """
    user = _reset_target(db, body.email, body.phone)
    code = phone_svc.send(db, user.phone, phone_svc.RESET) if user else None
    return {"sent": True, "demo_code": code if settings.demo_mode else None}


@router.post("/password-reset/verify")
def reset_verify(body: ResetVerifyIn, db: DbSession):
    if _reset_target(db, body.email, body.phone) is None:
        raise AppError(400, "CODE_MISMATCH", "인증번호가 일치하지 않습니다.")
    return {"reset_token": phone_svc.verify(db, body.phone, body.code, phone_svc.RESET)}


@router.post("/password-reset")
def reset_password(body: ResetIn, db: DbSession):
    """비밀번호 찾기 3단계: 휴대폰 인증 토큰으로 새 비밀번호 설정. 잠금도 함께 풀린다."""
    user = _reset_target(db, body.email, body.phone)
    if user is None:
        raise AppError(400, "PHONE_NOT_VERIFIED", "휴대폰 인증을 먼저 완료해주세요.")
    phone_svc.consume_token(db, body.phone, body.reset_token, phone_svc.RESET)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return {"ok": True}


@router.post("/password", response_model=UserOut)
def change_password(body: PasswordChangeIn, user: CurrentUser, db: DbSession):
    """비밀번호 변경. 운영자가 발급한 임시 비밀번호 계정은 첫 로그인 후 반드시 여기서 바꾼다."""
    if not verify_password(body.current_password, user.password_hash):
        raise AppError(400, "WRONG_PASSWORD", "현재 비밀번호가 올바르지 않습니다.")
    if body.current_password == body.new_password:
        raise AppError(400, "SAME_PASSWORD", "새 비밀번호는 현재 비밀번호와 달라야 합니다.")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    return to_user_out(user)


@router.post("/phone/send")
def send_phone_code(body: PhoneSendIn, db: DbSession):
    """가입용 휴대폰 인증번호 발송. 이미 가입된 번호면 거부(휴대폰 1개 = 계정 1개)."""
    code = phone_svc.send(db, body.phone)
    return {"sent": True, "demo_code": code if settings.demo_mode else None}


@router.post("/phone/verify")
def verify_phone_code(body: PhoneVerifyIn, db: DbSession):
    return {"phone_token": phone_svc.verify(db, body.phone, body.code)}


@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn, db: DbSession):
    """고객 회원가입. 상담사·관리자 계정은 가입이 아니라 운영자가 발급한다(권한 상승 방지).

    가입과 동시에 '본인' 피검자를 만들어, 바로 키트 코드로 결과지를 연결할 수 있게 한다.
    """
    if not body.privacy_consent:
        raise AppError(400, "CONSENT_REQUIRED", "건강정보 수집·이용에 동의해야 가입할 수 있습니다.")
    if db.query(User).filter_by(email=body.email).count():
        raise AppError(409, "EMAIL_TAKEN", "이미 가입된 이메일입니다.")
    if phone_svc.phone_taken(db, body.phone):
        raise AppError(409, "PHONE_TAKEN", "이미 가입된 휴대폰 번호입니다.")
    # 이름·생년월일은 누구나 입력할 수 있으므로, 휴대폰 소유 확인이 끝난 번호로만 가입시킨다
    phone_svc.consume_token(db, body.phone, body.phone_token)
    phone = phone_svc.normalize(body.phone)
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        phone=phone,
        phone_verified_at=now(),
        role=Role.CUSTOMER,
    )
    db.add(user)
    db.flush()
    db.add(
        Subject(
            owner_id=user.id, name=body.name, birth_date=body.birth_date, relation=Relation.SELF,
            phone=phone, consent_at=now(),
        )
    )
    db.commit()
    return TokenOut(access_token=create_token(user), user=to_user_out(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return to_user_out(user)
