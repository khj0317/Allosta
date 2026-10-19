import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Counselor, Role, User

_ITERATIONS = 200_000
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS).hex()
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, iterations, salt, digest = encoded.split("$")
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    return hmac.compare_digest(candidate, digest)


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다.")
    try:
        payload = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 토큰입니다.")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "사용자를 찾을 수 없습니다.")
    # 비활성화된 상담사는 이미 발급된 토큰으로도 접근할 수 없다
    if user.counselor and not user.counselor.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "비활성화된 계정입니다.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "접근 권한이 없습니다.")
        return user

    return checker


CustomerUser = Annotated[User, Depends(require_roles(Role.CUSTOMER))]
StaffUser = Annotated[User, Depends(require_roles(Role.COUNSELOR, Role.ADMIN))]
AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]


def get_current_counselor(db: DbSession, user: Annotated[User, Depends(require_roles(Role.COUNSELOR))]) -> Counselor:
    counselor = db.query(Counselor).filter_by(user_id=user.id).one_or_none()
    if counselor is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "상담사 프로필이 없습니다.")
    return counselor


CurrentCounselor = Annotated[Counselor, Depends(get_current_counselor)]


def verify_integration_key(x_api_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_api_key, settings.integration_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 연동 키입니다.")
