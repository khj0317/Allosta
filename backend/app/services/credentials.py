"""비밀번호 확인과 연속 실패 잠금.

로그인뿐 아니라 '로그인한 상태에서 비밀번호를 다시 확인하는 곳'(비밀번호 변경·회원 탈퇴)도 같은 실패 횟수를 쓴다.
따로 두면 훔친 로그인 토큰으로 이 화면들에서 비밀번호를 무제한 대입해 계정을 빼앗거나 탈퇴시킬 수 있다.
잠기면 로그인도 함께 막히지만, 진짜 주인은 휴대폰 인증(비밀번호 찾기)으로 바로 풀 수 있다.
"""
from datetime import timedelta

from sqlalchemy.orm import Session

from ..config import settings
from ..db import now
from ..errors import AppError
from ..models import User
from ..security import verify_password


def lock_message(user: User) -> str:
    mins = max(1, int((user.locked_until - now()).total_seconds() // 60) + 1)
    return f"비밀번호를 {settings.login_max_failures}회 틀려 잠겼습니다. 약 {mins}분 후 다시 시도하거나 비밀번호 찾기로 풀어주세요."


def assert_not_locked(user: User) -> None:
    if user.locked_until and user.locked_until > now():
        raise AppError(423, "ACCOUNT_LOCKED", lock_message(user))


def check_password(db: Session, user: User, password: str, *, status: int, code: str, message: str) -> None:
    """맞으면 실패 횟수 초기화, 틀리면 횟수를 올리고 한도에 닿으면 잠근다. 틀린 경우 AppError."""
    assert_not_locked(user)
    if verify_password(password, user.password_hash):
        user.failed_logins = 0
        user.locked_until = None
        return
    user.failed_logins += 1
    if user.failed_logins >= settings.login_max_failures:
        user.locked_until = now() + timedelta(minutes=settings.login_lock_minutes)
        user.failed_logins = 0
        db.commit()
        raise AppError(423, "ACCOUNT_LOCKED", lock_message(user))
    db.commit()
    left = settings.login_max_failures - user.failed_logins
    raise AppError(status, code, f"{message} ({left}회 더 틀리면 잠깁니다)")
