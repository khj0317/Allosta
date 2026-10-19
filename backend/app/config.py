"""애플리케이션 설정.

모든 값은 환경변수로 덮어쓸 수 있다. 운영 정책(리마인더 시점, 대기 제안 유효시간,
전환 귀속 기간 등)을 코드가 아닌 설정으로 둔 이유는 운영팀이 실험적으로 조정할 여지가
큰 값들이기 때문이다.
"""
import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# 저장소에 공개된 개발용 기본값. 데모 모드가 아니면 이 값으로는 서버가 켜지지 않는다(main.validate_settings).
DEV_JWT_SECRET = "dev-only-secret-change-me-in-production-0000"
DEV_INTEGRATION_KEY = "dev-integration-key"


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./allostar.db")
    jwt_secret: str = os.getenv("JWT_SECRET", DEV_JWT_SECRET)
    jwt_expire_minutes: int = _env_int("JWT_EXPIRE_MINUTES", 60 * 12)
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:5173")
    integration_api_key: str = os.getenv("INTEGRATION_API_KEY", DEV_INTEGRATION_KEY)
    # 데모 모드: 데모 계정 바로 입장(비밀번호 없이)과 데모 키트 코드 안내를 켠다. 운영 배포 시 false.
    # 기본은 꺼짐(안전한 기본값). 실행 스크립트(dev.cmd/dev.sh)와 docker-compose에서만 켠다.
    demo_mode: bool = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes")

    # 상담 1회 길이(분). 슬롯 생성의 기본 단위.
    slot_minutes: int = _env_int("SLOT_MINUTES", 30)
    # 상담 시작 N시간 전까지만 고객 직접 취소/변경 허용
    cancel_deadline_hours: int = _env_int("CANCEL_DEADLINE_HOURS", 3)
    # 상담 시작 N분 전까지만 신규 예약 허용(상담사 사전 검토 시간 확보)
    booking_lead_minutes: int = _env_int("BOOKING_LEAD_MINUTES", 60)
    # 리마인더 발송 시점(상담 시작 기준 몇 분 전)
    reminder_offsets_minutes: tuple[int, ...] = field(
        default_factory=lambda: tuple(
            int(x) for x in os.getenv("REMINDER_OFFSETS_MINUTES", "1440,60").split(",")
        )
    )
    # 대기자에게 빈자리를 제안한 뒤 선점(hold)을 유지하는 시간(분)
    waitlist_offer_minutes: int = _env_int("WAITLIST_OFFER_MINUTES", 30)
    # 상담 후 N일 이내 추천 제품 구매 시 상담 전환으로 귀속
    attribution_days: int = _env_int("ATTRIBUTION_DAYS", 30)
    # 가족 휴대폰 인증번호 유효시간(분)·최대 시도 횟수·재발송 간격(초)
    family_code_minutes: int = _env_int("FAMILY_CODE_MINUTES", 10)
    family_code_max_attempts: int = _env_int("FAMILY_CODE_MAX_ATTEMPTS", 5)
    family_code_resend_seconds: int = _env_int("FAMILY_CODE_RESEND_SECONDS", 30)
    # 인증번호 문자: 번호당 하루 최대 발송 횟수(가입·가족 인증 합산)
    sms_daily_limit_per_phone: int = _env_int("SMS_DAILY_LIMIT_PER_PHONE", 5)
    # 키트 연결 실패: 계정당 하루 최대 횟수(키트 코드 대입 추측 방지)
    kit_claim_daily_failures: int = _env_int("KIT_CLAIM_DAILY_FAILURES", 10)
    # 계정당 등록 가능한 가족 수(본인 제외)
    max_family_members: int = _env_int("MAX_FAMILY_MEMBERS", 10)
    # 로그인 연속 실패 잠금: N회 실패 시 M분 잠금
    login_max_failures: int = _env_int("LOGIN_MAX_FAILURES", 5)
    login_lock_minutes: int = _env_int("LOGIN_LOCK_MINUTES", 10)
    # 제출된 상담 기록을 수정할 수 있는 기간(일). 이후에는 고정(의료 상담 기록의 신뢰성)
    record_edit_days: int = _env_int("RECORD_EDIT_DAYS", 7)
    # 백그라운드 스케줄러 주기(초). 0이면 비활성화(테스트용)
    scheduler_interval_seconds: int = _env_int("SCHEDULER_INTERVAL_SECONDS", 20)


settings = Settings()
