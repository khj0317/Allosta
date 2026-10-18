from typing import Any

from fastapi import HTTPException


class AppError(HTTPException):
    """프론트엔드가 code로 분기할 수 있도록 {code, message, extra} 형태로 응답한다."""

    def __init__(self, status_code: int, code: str, message: str, **extra: Any):
        super().__init__(status_code=status_code, detail={"code": code, "message": message, **extra})


def not_found(what: str) -> AppError:
    return AppError(404, "NOT_FOUND", f"{what}을(를) 찾을 수 없습니다.")


def forbidden(message: str = "접근 권한이 없습니다.") -> AppError:
    return AppError(403, "FORBIDDEN", message)
