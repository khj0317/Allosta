from fastapi import APIRouter

from ..db import now
from ..errors import AppError
from ..models import Relation, Role, Subject, User
from ..schemas import LoginIn, SignupIn, TokenOut, UserOut
from ..security import CurrentUser, DbSession, create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def to_user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.counselor_id = user.counselor.id if user.counselor else None
    return out


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DbSession):
    user = db.query(User).filter_by(email=body.email.strip().lower()).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise AppError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.")
    return TokenOut(access_token=create_token(user), user=to_user_out(user))


@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn, db: DbSession):
    """고객 회원가입. 상담사·관리자 계정은 가입이 아니라 운영자가 발급한다(권한 상승 방지).

    가입과 동시에 '본인' 피검자를 만들어, 바로 키트 코드로 결과지를 연결할 수 있게 한다.
    """
    if not body.privacy_consent:
        raise AppError(400, "CONSENT_REQUIRED", "건강정보 수집·이용에 동의해야 가입할 수 있습니다.")
    if db.query(User).filter_by(email=body.email).count():
        raise AppError(409, "EMAIL_TAKEN", "이미 가입된 이메일입니다.")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        phone=body.phone,
        role=Role.CUSTOMER,
    )
    db.add(user)
    db.flush()
    db.add(Subject(owner_id=user.id, name=body.name, birth_date=body.birth_date, relation=Relation.SELF, consent_at=now()))
    db.commit()
    return TokenOut(access_token=create_token(user), user=to_user_out(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return to_user_out(user)
