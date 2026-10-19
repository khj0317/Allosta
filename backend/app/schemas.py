from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .constants import CONCERN_TAGS, SERVICE_LABELS
from .models import (
    Booking,
    BookingStatus,
    IndicatorStatus,
    InterestLevel,
    NotificationType,
    RecordStatus,
    Relation,
    Role,
    ServiceType,
    Slot,
    SlotStatus,
    WaitlistStatus,
)

Phone = Annotated[str, StringConstraints(pattern=r"^01[0-9]-?\d{3,4}-?\d{4}$")]


def _validate_tags(v: list[str]) -> list[str]:
    unknown = set(v) - set(CONCERN_TAGS)
    if unknown:
        raise ValueError(f"알 수 없는 관심사 태그: {', '.join(unknown)}")
    return list(dict.fromkeys(v))


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth

class LoginIn(BaseModel):
    email: str
    password: str


def _password_policy(v: str) -> str:
    if not (any(c.isalpha() for c in v) and any(c.isdigit() for c in v)):
        raise ValueError("비밀번호는 영문과 숫자를 모두 포함해야 합니다.")
    return v


Password = Annotated[str, StringConstraints(min_length=8, max_length=72)]


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: Password

    @field_validator("new_password")
    @classmethod
    def _policy(cls, v: str) -> str:
        return _password_policy(v)


class SignupIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    password: Annotated[str, StringConstraints(min_length=8, max_length=72)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    phone: Phone
    # /api/auth/phone/verify 에서 받은 일회용 토큰(이 번호의 소유 확인)
    phone_token: str = ""
    # 결과지 피검자 본인 확인·연령대별 상담에 필요해 필수
    birth_date: date
    # 건강정보(민감정보) 수집·이용 동의는 필수
    privacy_consent: bool

    @field_validator("birth_date")
    @classmethod
    def _birth_range(cls, v: date) -> date:
        if v.year < 1900 or v > date.today():
            raise ValueError("생년월일을 다시 확인해주세요.")
        return v

    @field_validator("password")
    @classmethod
    def _policy(cls, v: str) -> str:
        return _password_policy(v)


class PhoneSendIn(BaseModel):
    phone: Phone


class PhoneVerifyIn(BaseModel):
    phone: Phone
    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]


class ResetSendIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3)]
    phone: Phone


class ResetVerifyIn(ResetSendIn):
    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6}$")]


class ResetIn(ResetSendIn):
    reset_token: str
    new_password: Password

    @field_validator("new_password")
    @classmethod
    def _policy(cls, v: str) -> str:
        return _password_policy(v)


class DemoSessionIn(BaseModel):
    role: Role


class UserOut(ORM):
    id: int
    email: str
    name: str
    phone: str
    role: Role
    counselor_id: int | None = None
    must_change_password: bool = False


class TokenOut(BaseModel):
    access_token: str
    user: UserOut


# ---------------------------------------------------------------- subjects / results

class FamilyIn(BaseModel):
    """가족 등록. 가족 본인의 휴대폰으로 인증번호를 보내므로 휴대폰·생년월일이 필수."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    relation: Relation
    birth_date: date
    phone: Phone

    @field_validator("birth_date")
    @classmethod
    def _birth_range(cls, v: date) -> date:
        if v.year < 1900 or v > date.today():
            raise ValueError("생년월일을 다시 확인해주세요.")
        return v


class FamilyAddIn(FamilyIn):
    """가족 본인 휴대폰으로 받은 인증번호까지 맞아야 가족으로 등록된다."""

    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]


class IndicatorOut(ORM):
    id: int
    category: str
    name: str
    value: float
    unit: str
    ref_low: float | None
    ref_high: float | None
    status: IndicatorStatus
    description: str


class ResultSummary(ORM):
    id: int
    kit_code: str
    service_type: ServiceType
    service_label: str = ""
    reported_at: datetime
    abnormal_count: int = 0


class ResultDetail(ResultSummary):
    overall_comment: str
    subject_id: int | None
    subject_name: str | None = None
    indicators: list[IndicatorOut]


class SubjectOut(ORM):
    id: int
    name: str
    birth_date: date | None
    relation: Relation
    phone_masked: str | None = None
    consent_at: datetime | None
    results: list[ResultSummary] = []


class FamilyCodeOut(BaseModel):
    sent: bool = True
    expires_at: datetime
    # 데모 모드에서만 채워진다(실제 문자 발송이 없으므로 화면에 안내). 운영에서는 항상 null.
    demo_code: str | None = None


class ClaimKitIn(BaseModel):
    kit_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=30)]


# ---------------------------------------------------------------- slots

class SlotOut(BaseModel):
    id: int
    counselor_id: int
    counselor_name: str
    start_at: datetime
    end_at: datetime

    @classmethod
    def from_slot(cls, s: Slot) -> "SlotOut":
        return cls(
            id=s.id,
            counselor_id=s.counselor_id,
            counselor_name=s.counselor.user.name,
            start_at=s.start_at,
            end_at=s.end_at,
        )


class StaffSlotOut(SlotOut):
    status: SlotStatus
    booking_id: int | None = None
    booking_customer: str | None = None
    hold_until: datetime | None = None


class SlotBulkIn(BaseModel):
    counselor_id: int | None = None  # 관리자만 지정, 상담사는 본인
    date_from: date
    date_to: date
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    start_time: str = "10:00"
    end_time: str = "18:00"
    # 점심시간 등 제외 구간
    break_start: str | None = "12:00"
    break_end: str | None = "13:00"


class SlotBulkOut(BaseModel):
    created: int
    skipped: int
    waitlist_offers: int


class SlotPatchIn(BaseModel):
    status: SlotStatus


# ---------------------------------------------------------------- bookings

# 상담 전화를 받을 사람. 번호를 직접 받지 않고 '인증된 번호 중 누구의 것'인지만 고른다.
# (자유 입력이면 모르는 사람에게 상담사가 건강 결과를 설명하는 사고가 날 수 있음)
Contact = Literal["OWNER", "SUBJECT"]


class BookingIn(BaseModel):
    slot_id: int
    subject_id: int
    result_id: int
    contact: Contact = "OWNER"
    pre_questions: Annotated[str, StringConstraints(max_length=1000)] = ""
    concern_tags: list[str] = []

    @field_validator("concern_tags")
    @classmethod
    def _known_tags(cls, v: list[str]) -> list[str]:
        return _validate_tags(v)


class RescheduleIn(BaseModel):
    slot_id: int


class CancelIn(BaseModel):
    reason: Annotated[str, StringConstraints(max_length=200)] = ""


class BookingOut(BaseModel):
    id: int
    status: BookingStatus
    start_at: datetime
    end_at: datetime
    counselor_id: int
    counselor_name: str
    customer_id: int
    customer_name: str
    subject_id: int
    subject_name: str
    subject_relation: Relation
    result_id: int
    service_type: ServiceType
    service_label: str
    contact_phone: str
    pre_questions: str
    concern_tags: list[str]
    attendance_confirmed_at: datetime | None
    attendance_declined_at: datetime | None = None
    call_attempts: int
    cancel_reason: str | None
    created_at: datetime
    record_status: RecordStatus | None = None
    can_change: bool = False

    @classmethod
    def from_booking(cls, b: Booking, can_change: bool = False) -> "BookingOut":
        return cls(
            id=b.id,
            status=b.status,
            start_at=b.slot.start_at,
            end_at=b.slot.end_at,
            counselor_id=b.counselor_id,
            counselor_name=b.counselor.user.name,
            customer_id=b.customer_id,
            customer_name=b.customer.name,
            subject_id=b.subject_id,
            subject_name=b.subject.name,
            subject_relation=b.subject.relation,
            result_id=b.result_id,
            service_type=b.result.service_type,
            service_label=SERVICE_LABELS[b.result.service_type],
            contact_phone=b.contact_phone,
            pre_questions=b.pre_questions,
            concern_tags=b.concern_tags or [],
            attendance_confirmed_at=b.attendance_confirmed_at,
            attendance_declined_at=b.attendance_declined_at,
            call_attempts=b.call_attempts,
            cancel_reason=b.cancel_reason,
            created_at=b.created_at,
            record_status=b.record.status if b.record else None,
            can_change=can_change,
        )


# ---------------------------------------------------------------- waitlist

class WaitlistIn(BaseModel):
    subject_id: int
    result_id: int
    desired_date: date
    start_hour: Annotated[int, Field(ge=0, le=23)]
    end_hour: Annotated[int, Field(ge=1, le=24)]
    counselor_id: int | None = None
    contact: Contact = "OWNER"
    pre_questions: Annotated[str, StringConstraints(max_length=1000)] = ""


class WaitlistOut(ORM):
    id: int
    subject_id: int
    subject_name: str = ""
    result_id: int
    service_type: ServiceType
    desired_date: date
    start_hour: int
    end_hour: int
    counselor_id: int | None
    status: WaitlistStatus
    offered_slot: SlotOut | None = None
    # 같은 결과지로 이미 잡아 둔 예약. 있으면 제안 수락 = 이 예약의 일정 변경
    current_booking: SlotOut | None = None
    offer_expires_at: datetime | None
    booking_id: int | None
    created_at: datetime


# ---------------------------------------------------------------- records

class RecommendationIn(BaseModel):
    product_id: int
    interest_level: InterestLevel
    note: Annotated[str, StringConstraints(max_length=300)] = ""


class RecordIn(BaseModel):
    concern_tags: list[str] = []
    discussed_indicator_ids: list[int] = []
    summary: Annotated[str, StringConstraints(max_length=4000)] = ""
    customer_message: Annotated[str, StringConstraints(max_length=4000)] = ""
    lifestyle_advice: Annotated[str, StringConstraints(max_length=2000)] = ""
    follow_up_needed: bool = False
    follow_up_date: date | None = None
    recommendations: list[RecommendationIn] = []
    # 제출된(고객에게 공유된) 기록을 고칠 때만 필수
    edit_reason: Annotated[str, StringConstraints(max_length=300)] = ""

    @field_validator("concern_tags")
    @classmethod
    def _known_tags(cls, v: list[str]) -> list[str]:
        return _validate_tags(v)


class ProductOut(ORM):
    id: int
    sku: str
    name: str
    category: str
    price: int
    related_services: list[str]


class RecommendationOut(ORM):
    product_id: int
    interest_level: InterestLevel
    note: str
    product: ProductOut


class RecordOut(ORM):
    id: int
    booking_id: int
    status: RecordStatus
    concern_tags: list[str]
    discussed_indicator_ids: list[int]
    summary: str
    customer_message: str
    lifestyle_advice: str
    follow_up_needed: bool
    follow_up_date: date | None
    submitted_at: datetime | None
    updated_at: datetime
    recommendations: list[RecommendationOut]


class CustomerRecordOut(BaseModel):
    """고객에게는 내부 메모(summary)·관심도 평가를 노출하지 않는다."""

    customer_message: str
    lifestyle_advice: str
    follow_up_needed: bool
    follow_up_date: date | None
    discussed_indicators: list[IndicatorOut]
    recommended_products: list[ProductOut]
    submitted_at: datetime | None


class RevisionOut(BaseModel):
    id: int
    editor_name: str
    reason: str
    changed_fields: list[str]
    created_at: datetime


class CounselorBookingDetail(BaseModel):
    booking: BookingOut
    result: ResultDetail
    customer_phone: str
    past_bookings: list[BookingOut]
    record: RecordOut | None
    # 제출된 기록을 수정할 수 있는 마지막 시각(지나면 고정)
    record_editable_until: datetime | None = None
    revisions: list[RevisionOut] = []


# ---------------------------------------------------------------- etc

class NotificationOut(ORM):
    id: int
    type: NotificationType
    title: str
    body: str
    booking_id: int | None
    waitlist_id: int | None
    sent_at: datetime | None
    read_at: datetime | None


class OrderItemIn(BaseModel):
    sku: str
    quantity: Annotated[int, Field(ge=1)]
    unit_price: Annotated[int, Field(ge=0)]


class OrderIn(BaseModel):
    external_order_id: str
    customer_email: str
    ordered_at: datetime
    items: list[OrderItemIn]


class CounselorCreateIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    email: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    phone: Phone
    specialties: Annotated[list[ServiceType], Field(min_length=1)]
    bio: Annotated[str, StringConstraints(max_length=300)] = ""


class CounselorPatchIn(BaseModel):
    active: bool | None = None
    specialties: Annotated[list[ServiceType], Field(min_length=1)] | None = None
    bio: Annotated[str, StringConstraints(max_length=300)] | None = None


class CounselorAdminOut(BaseModel):
    id: int
    name: str
    email: str
    phone: str
    specialties: list[ServiceType]
    bio: str
    active: bool
    must_change_password: bool
    upcoming_bookings: int


class CounselorCreatedOut(BaseModel):
    counselor: CounselorAdminOut
    # 한 번만 보여주는 임시 비밀번호. 상담사는 첫 로그인 후 반드시 변경해야 한다.
    temp_password: str


class CounselorOut(BaseModel):
    id: int
    name: str
    specialties: list[ServiceType]
    bio: str
    active: bool
