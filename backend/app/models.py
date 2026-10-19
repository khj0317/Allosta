"""도메인 모델.

핵심 설계 포인트
- 계정(User)과 피검자(Subject)를 분리: 한 계정이 가족 여러 명의 결과에 대해 상담을 신청할 수 있다.
- 슬롯(Slot)을 1급 엔티티로 두고, '활성 예약은 슬롯당 최대 1건'을 DB 부분 유니크 인덱스로 강제한다.
  → 애플리케이션 레벨 체크만으로는 동시 요청 시 중복 예약을 막을 수 없기 때문.
- 상담 기록(ConsultationRecord)은 자유 텍스트가 아닌 구조화된 필드(관심사 태그, 논의 지표, 추천 제품+관심도)로
  저장해 전환율/관심 제품 같은 지표를 집계 가능하게 한다.
- 알림(Notification)은 아웃박스 테이블로 저장 후 스케줄러가 발송 → 발송 실패/재시도/이력 추적 가능.
"""
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, now


def _enum(e: type[StrEnum]):
    # DB에는 문자열로 저장(마이그레이션 시 값 추가가 쉬움)
    return Enum(e, native_enum=False, length=32, validate_strings=True)


class Role(StrEnum):
    CUSTOMER = "CUSTOMER"
    COUNSELOR = "COUNSELOR"
    ADMIN = "ADMIN"


class Relation(StrEnum):
    SELF = "SELF"
    SPOUSE = "SPOUSE"
    PARENT = "PARENT"
    CHILD = "CHILD"
    SIBLING = "SIBLING"
    OTHER = "OTHER"


class ServiceType(StrEnum):
    METABOLIC = "METABOLIC"  # 종합 대사 분석
    FOOD_SENSITIVITY = "FOOD_SENSITIVITY"  # 음식물 과민증
    NUTRIENT_METAL = "NUTRIENT_METAL"  # 영양·중금속 기반 건강 위험도


class IndicatorStatus(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CAUTION = "CAUTION"


class SlotStatus(StrEnum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"  # 상담사가 닫은 슬롯(휴무 등)


class BookingStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


# 슬롯을 점유하는 상태. CANCELLED만 슬롯을 반환한다.
ACTIVE_BOOKING_STATUSES = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED, BookingStatus.NO_SHOW)


class WaitlistStatus(StrEnum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"  # 빈자리가 생겨 선점 제안 중
    BOOKED = "BOOKED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class RecordStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class InterestLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class NotificationType(StrEnum):
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED"
    REMINDER = "REMINDER"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"
    WAITLIST_OFFER = "WAITLIST_OFFER"
    RECORD_SHARED = "RECORD_SHARED"


class NotificationChannel(StrEnum):
    SMS = "SMS"  # 알림톡/SMS (MVP는 콘솔 Mock 발송)
    IN_APP = "IN_APP"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(50))
    # 휴대폰 1개 = 계정 1개. 가입 시 인증번호로 실제 소유를 확인한다.
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    role: Mapped[Role] = mapped_column(_enum(Role))
    # 운영자가 임시 비밀번호로 발급한 계정(상담사 등)은 첫 로그인 후 비밀번호를 바꿔야 한다
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # 로그인 연속 실패 잠금
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    counselor: Mapped["Counselor | None"] = relationship(back_populates="user", uselist=False)


class Counselor(Base):
    __tablename__ = "counselors"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    # 상담 가능한 분석 서비스 목록. 예약 시 결과지 종류와 매칭한다.
    specialties: Mapped[list[str]] = mapped_column(JSON, default=list)
    bio: Mapped[str] = mapped_column(String(300), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="counselor")


class Subject(Base):
    """피검자. 계정 소유자 본인 또는 가족."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    relation: Mapped[Relation] = mapped_column(_enum(Relation))
    # 가족 본인의 휴대폰. 인증번호를 이 번호로 보내 '실제 그 사람이 동의했는지'를 확인한다(본인은 계정 번호 사용).
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 피검자 본인 확인 + 결과 열람·상담 동의 완료 시각.
    # 본인(SELF)은 가입 시 동의, 가족은 휴대폰 인증번호 확인 시점. 이 값이 없으면 결과 연결·예약 불가.
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 휴대폰 인증 진행 상태(코드는 해시로만 저장)
    verify_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verify_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verify_attempts: Mapped[int] = mapped_column(Integer, default=0)
    verify_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    results: Mapped[list["TestResult"]] = relationship(back_populates="subject")


class TestResult(Base):
    """검사 결과지. 실제로는 LIMS/분석 시스템에서 연동되며, 키트 코드로 계정에 연결한다."""

    __tablename__ = "test_results"
    __test__ = False  # pytest 수집 대상 아님

    id: Mapped[int] = mapped_column(primary_key=True)
    kit_code: Mapped[str] = mapped_column(String(30), unique=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"), nullable=True, index=True)
    service_type: Mapped[ServiceType] = mapped_column(_enum(ServiceType))
    reported_at: Mapped[datetime] = mapped_column(DateTime)
    overall_comment: Mapped[str] = mapped_column(Text, default="")
    # 검체 접수 시 등록된 피검자 정보. 값이 있으면 이름·생년월일이 일치하는 피검자에게만 연결할 수 있다.
    # (비어 있으면 미등록 키트 → 처음 연결하는 피검자 정보로 등록)
    registered_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    registered_birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 이름·생년월일은 주변 사람이 쉽게 알 수 있어, 검사자 휴대폰까지 대조해야 본인 결과로 인정한다
    registered_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    subject: Mapped[Subject | None] = relationship(back_populates="results")
    indicators: Mapped[list["Indicator"]] = relationship(
        back_populates="result", order_by="Indicator.id", cascade="all, delete-orphan"
    )


class Indicator(Base):
    __tablename__ = "indicators"

    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("test_results.id"), index=True)
    category: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(80))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    ref_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    ref_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[IndicatorStatus] = mapped_column(_enum(IndicatorStatus))
    description: Mapped[str] = mapped_column(Text, default="")

    result: Mapped[TestResult] = relationship(back_populates="indicators")


class PhoneVerification(Base):
    """가입 전 휴대폰 소유 확인. 확인되면 일회용 토큰을 발급하고, 가입 요청은 이 토큰으로만 그 번호를 쓸 수 있다."""

    __tablename__ = "phone_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)  # 숫자만
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class SmsSendLog(Base):
    """인증번호 문자 발송 기록. 번호당 하루 발송 상한으로 남의 번호에 문자를 퍼붓는 악용을 막는다."""

    __tablename__ = "sms_send_logs"
    __table_args__ = (Index("ix_sms_log_phone_time", "phone", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20))  # 숫자만
    purpose: Mapped[str] = mapped_column(String(20))  # SIGNUP / FAMILY
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class KitClaimFailure(Base):
    """키트 연결 실패 기록. 순번 형식 키트 코드를 대입해 보는 시도를 계정당 하루 횟수로 제한한다."""

    __tablename__ = "kit_claim_failures"
    __table_args__ = (Index("ix_kit_fail_owner_time", "owner_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Slot(Base):
    __tablename__ = "slots"
    __table_args__ = (UniqueConstraint("counselor_id", "start_at", name="uq_slot_counselor_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    counselor_id: Mapped[int] = mapped_column(ForeignKey("counselors.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[SlotStatus] = mapped_column(_enum(SlotStatus), default=SlotStatus.OPEN)
    # 대기자 제안 중인 슬롯은 해당 대기자만 예약 가능
    # (waitlist_entries ↔ slots 순환 FK를 피하기 위해 FK 제약 없이 ID만 보관)
    held_for_waitlist_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hold_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    counselor: Mapped[Counselor] = relationship()


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        # 핵심 불변식: 하나의 슬롯에는 활성(취소되지 않은) 예약이 최대 1건.
        Index(
            "uq_booking_active_slot",
            "slot_id",
            unique=True,
            sqlite_where=text("status != 'CANCELLED'"),
            postgresql_where=text("status != 'CANCELLED'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), index=True)
    counselor_id: Mapped[int] = mapped_column(ForeignKey("counselors.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    result_id: Mapped[int] = mapped_column(ForeignKey("test_results.id"))
    status: Mapped[BookingStatus] = mapped_column(_enum(BookingStatus), default=BookingStatus.CONFIRMED)
    # 상담 전화를 받을 번호(가족 상담 시 계정 번호와 다를 수 있음)
    contact_phone: Mapped[str] = mapped_column(String(20))
    pre_questions: Mapped[str] = mapped_column(Text, default="")
    concern_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 리마인더에 대한 고객 응답(참석 확인). 미확인 예약은 상담사 화면에서 강조된다.
    attendance_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 리마인더 문자에서 '통화가 어려워요'를 누른 시각. 상담사·계정 주인에게 알린다.
    attendance_declined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 문자 링크용 1회 발급 토큰(해시만 저장). 로그인 없이 참석 응답 → 가족 번호로 받아도 응답 가능.
    attendance_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    call_attempts: Mapped[int] = mapped_column(Integer, default=0)
    cancel_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    slot: Mapped[Slot] = relationship()
    counselor: Mapped[Counselor] = relationship()
    customer: Mapped[User] = relationship()
    subject: Mapped[Subject] = relationship()
    result: Mapped[TestResult] = relationship()
    record: Mapped["ConsultationRecord | None"] = relationship(back_populates="booking", uselist=False)


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    result_id: Mapped[int] = mapped_column(ForeignKey("test_results.id"))
    service_type: Mapped[ServiceType] = mapped_column(_enum(ServiceType))
    desired_date: Mapped[date] = mapped_column(Date, index=True)
    # 희망 시간대 [start_hour, end_hour)
    start_hour: Mapped[int] = mapped_column(Integer)
    end_hour: Mapped[int] = mapped_column(Integer)
    counselor_id: Mapped[int | None] = mapped_column(ForeignKey("counselors.id"), nullable=True)
    contact_phone: Mapped[str] = mapped_column(String(20))
    pre_questions: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[WaitlistStatus] = mapped_column(_enum(WaitlistStatus), default=WaitlistStatus.WAITING)
    offered_slot_id: Mapped[int | None] = mapped_column(ForeignKey("slots.id"), nullable=True)
    offer_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 고객이 거절한 슬롯은 다시 제안하지 않는다
    declined_slot_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    subject: Mapped[Subject] = relationship()
    offered_slot: Mapped[Slot | None] = relationship(foreign_keys=[offered_slot_id])


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(30))  # SUPPLEMENT / FOOD / TEST_KIT
    price: Mapped[int] = mapped_column(Integer)
    # 어떤 분석 서비스 상담에서 주로 추천되는지(추천 폼 정렬용)
    related_services: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ConsultationRecord(Base):
    __tablename__ = "consultation_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), unique=True)
    counselor_id: Mapped[int] = mapped_column(ForeignKey("counselors.id"), index=True)
    status: Mapped[RecordStatus] = mapped_column(_enum(RecordStatus), default=RecordStatus.DRAFT)
    # 표준화된 관심사 태그(예: 혈당, 장건강, 체중관리). 자유 텍스트 대신 코드값으로 집계.
    concern_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    discussed_indicator_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")  # 내부용 상담 요약
    customer_message: Mapped[str] = mapped_column(Text, default="")  # 고객에게 공유되는 안내문
    lifestyle_advice: Mapped[str] = mapped_column(Text, default="")
    follow_up_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    booking: Mapped[Booking] = relationship(back_populates="record")
    recommendations: Mapped[list["ProductRecommendation"]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class RecordRevision(Base):
    """제출된 상담 기록의 수정 이력. 고객에게 공유된 뒤 내용이 바뀌면 '누가·언제·왜·무엇을' 남긴다."""

    __tablename__ = "record_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("consultation_records.id"), index=True)
    editor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(300))
    changed_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 수정 전 내용 전체(복원·감사용)
    before: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    editor: Mapped[User] = relationship()


class ProductRecommendation(Base):
    __tablename__ = "product_recommendations"
    __table_args__ = (UniqueConstraint("record_id", "product_id", name="uq_rec_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("consultation_records.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    interest_level: Mapped[InterestLevel] = mapped_column(_enum(InterestLevel))
    note: Mapped[str] = mapped_column(String(300), default="")

    record: Mapped[ConsultationRecord] = relationship(back_populates="recommendations")
    product: Mapped[Product] = relationship()


class Order(Base):
    """커머스(자사몰)에서 웹훅으로 수집한 주문. 상담 전환 귀속 계산에 사용."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_order_id: Mapped[str] = mapped_column(String(50), unique=True)  # 멱등성 키
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ordered_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    total_amount: Mapped[int] = mapped_column(Integer)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class Notification(Base):
    """알림 아웃박스. 예약 트랜잭션 안에서 함께 기록되고, 스케줄러가 scheduled_at 도래 시 발송한다."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notification_due", "status", "scheduled_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), nullable=True, index=True)
    waitlist_id: Mapped[int | None] = mapped_column(ForeignKey("waitlist_entries.id"), nullable=True)
    type: Mapped[NotificationType] = mapped_column(_enum(NotificationType))
    channel: Mapped[NotificationChannel] = mapped_column(_enum(NotificationChannel))
    recipient: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[NotificationStatus] = mapped_column(_enum(NotificationStatus), default=NotificationStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
