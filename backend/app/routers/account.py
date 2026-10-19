"""내 계정: 회원 탈퇴."""
from fastapi import APIRouter
from pydantic import BaseModel

from ..security import CustomerUser, DbSession
from ..services import account

router = APIRouter(prefix="/api/me", tags=["account"])


class WithdrawIn(BaseModel):
    password: str


@router.get("/withdrawal")
def withdrawal_preview(user: CustomerUser, db: DbSession):
    """탈퇴하면 취소·삭제되는 것과 익명으로 남는 것을 미리 보여준다."""
    return account.preview(db, user)


@router.post("/withdrawal", status_code=204)
def withdraw(body: WithdrawIn, user: CustomerUser, db: DbSession):
    """비밀번호를 다시 확인한 뒤 탈퇴. 개인정보·건강정보는 즉시 삭제되고 되돌릴 수 없다."""
    account.withdraw(db, user, body.password)
