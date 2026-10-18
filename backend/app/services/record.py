from sqlalchemy.orm import Session

from ..db import now
from ..errors import AppError, forbidden
from ..models import (
    Booking,
    BookingStatus,
    ConsultationRecord,
    Counselor,
    Indicator,
    NotificationType,
    Product,
    ProductRecommendation,
    RecordStatus,
)
from . import notification


def get_booking_for_counselor(db: Session, booking_id: int, counselor: Counselor) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None or booking.counselor_id != counselor.id:
        raise forbidden("본인에게 배정된 상담만 접근할 수 있습니다.")
    return booking


def get_or_create(db: Session, booking: Booking) -> ConsultationRecord:
    if booking.record:
        return booking.record
    record = ConsultationRecord(
        booking_id=booking.id,
        counselor_id=booking.counselor_id,
        # 예약 시 고객이 고른 관심사를 기본값으로 채워 상담사 입력 부담을 줄인다
        concern_tags=list(booking.concern_tags or []),
    )
    db.add(record)
    db.flush()
    db.refresh(booking)
    return record


def save(db: Session, booking: Booking, data) -> ConsultationRecord:
    if booking.status in (BookingStatus.CANCELLED, BookingStatus.NO_SHOW):
        raise AppError(400, "INVALID_STATE", "취소/부재 처리된 상담에는 기록을 작성할 수 없습니다.")
    record = get_or_create(db, booking)

    valid_indicator_ids = {i.id for i in db.query(Indicator.id).filter(Indicator.result_id == booking.result_id)}
    bad = set(data.discussed_indicator_ids) - valid_indicator_ids
    if bad:
        raise AppError(400, "INVALID_INDICATOR", "이 결과지에 없는 지표가 포함되어 있습니다.")

    record.concern_tags = data.concern_tags
    record.discussed_indicator_ids = data.discussed_indicator_ids
    record.summary = data.summary
    record.customer_message = data.customer_message
    record.lifestyle_advice = data.lifestyle_advice
    record.follow_up_needed = data.follow_up_needed
    record.follow_up_date = data.follow_up_date if data.follow_up_needed else None
    record.updated_at = now()

    product_ids = [r.product_id for r in data.recommendations]
    if len(product_ids) != len(set(product_ids)):
        raise AppError(400, "DUPLICATE_PRODUCT", "같은 제품이 중복으로 추가되었습니다.")
    if product_ids and db.query(Product).filter(Product.id.in_(product_ids)).count() != len(product_ids):
        raise AppError(400, "INVALID_PRODUCT", "존재하지 않는 제품이 포함되어 있습니다.")
    record.recommendations.clear()
    db.flush()
    for r in data.recommendations:
        record.recommendations.append(
            ProductRecommendation(product_id=r.product_id, interest_level=r.interest_level, note=r.note)
        )
    db.commit()
    return record


def submit(db: Session, booking: Booking, data) -> ConsultationRecord:
    if booking.slot.start_at > now():
        raise AppError(400, "TOO_EARLY", "상담 시작 이후에 기록을 제출할 수 있습니다.")
    if not data.summary.strip():
        raise AppError(400, "SUMMARY_REQUIRED", "상담 요약은 필수입니다.")
    if not data.concern_tags:
        raise AppError(400, "TAGS_REQUIRED", "관심사 태그를 1개 이상 선택해주세요.")
    first_submit = booking.record is None or booking.record.status != RecordStatus.SUBMITTED
    record = save(db, booking, data)
    if first_submit:
        record.status = RecordStatus.SUBMITTED
        record.submitted_at = now()
        booking.status = BookingStatus.COMPLETED
        booking.completed_at = now()
        notification.enqueue(
            db,
            booking.customer,
            NotificationType.RECORD_SHARED,
            "상담 내용이 정리되었습니다",
            f"{booking.subject.name}님 결과 상담 요약과 추천 사항을 확인해보세요.\n"
            f"{notification.settings.frontend_url}/my/bookings/{booking.id}",
            booking_id=booking.id,
        )
        db.commit()
    return record
