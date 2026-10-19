"""데모 전용 기능. DEMO_MODE=false 이면 모든 엔드포인트가 404를 돌려준다.

평가·시연 시 비밀번호 없이 역할별 데모 계정으로 바로 들어가 흐름을 확인하기 위한 것이다.
운영 환경에서는 반드시 끈다(비밀번호 없이 데모 계정으로 로그인되므로).
"""
from fastapi import APIRouter, Depends

from ..config import settings
from ..constants import DEMO_ACCOUNTS, SERVICE_LABELS
from ..errors import AppError
from ..models import TestResult, User
from ..schemas import DemoSessionIn, TokenOut
from ..security import CustomerUser, DbSession, create_token
from ..services import family
from .auth import to_user_out

# 시드가 만들어 두는 미연결 키트. 새로 가입한 계정이 바로 결과지를 연결해 볼 수 있다.
DEMO_KIT_PREFIX = "AL-DEMO-"


def _require_demo_mode() -> None:
    if not settings.demo_mode:
        raise AppError(404, "NOT_FOUND", "데모 모드가 꺼져 있습니다.")


router = APIRouter(prefix="/api/demo", tags=["demo"], dependencies=[Depends(_require_demo_mode)])


@router.post("/session", response_model=TokenOut)
def demo_session(body: DemoSessionIn, db: DbSession):
    user = db.query(User).filter_by(email=DEMO_ACCOUNTS[body.role]).one_or_none()
    if user is None:
        raise AppError(404, "DEMO_ACCOUNT_MISSING", "데모 계정이 없습니다. python -m app.seed 를 실행해주세요.")
    return TokenOut(access_token=create_token(user), user=to_user_out(user))


@router.get("/kits")
def demo_kits(db: DbSession, user: CustomerUser, subject_id: int):
    """이 피검자에게 연결할 수 있는 데모 키트: 미등록 키트 + 이 피검자 이름·생년월일로 등록된 키트."""
    subject = family.own_subject(db, user, subject_id)
    rows = (
        db.query(TestResult)
        .filter(TestResult.kit_code.like(f"{DEMO_KIT_PREFIX}%"), TestResult.subject_id.is_(None))
        .order_by(TestResult.kit_code)
        .all()
    )
    # 이 사람 앞으로 등록된 키트를 먼저 보여준다
    rows.sort(key=lambda r: r.registered_name is None)
    return [
        {"kit_code": r.kit_code, "service_label": SERVICE_LABELS[r.service_type], "registered": r.registered_name is not None}
        for r in rows
        if family.kit_matches(r, subject)
    ]


@router.get("/hints")
def demo_hints(db: DbSession):
    """실제 문자가 가지 않는 데모 환경에서 화면에 채워 넣을 수 있는 시연용 정보.

    - reset: 비밀번호 찾기 시연용 계정의 이메일·가입 휴대폰(공용 데모 계정은 비밀번호 변경이 막혀 있어 따로 둠)
    - family: 시드에서 가족 등록을 하지 않은 데모 아버지(키트 AL-DEMO-00이 이 정보로 접수돼 있음)
    """
    from ..seed import DEMO_DAD, DEMO_RESET_ACCOUNT

    account = db.query(User).filter_by(email=DEMO_RESET_ACCOUNT["email"]).one_or_none()
    return {
        "reset": {"email": account.email, "phone": account.phone} if account else None,
        "family": {**DEMO_DAD, "relation": DEMO_DAD["relation"].value, "birth_date": DEMO_DAD["birth_date"].isoformat()},
    }
