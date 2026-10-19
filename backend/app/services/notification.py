"""알림 아웃박스 + 발송기.

예약/취소와 같은 트랜잭션에서 Notification 행을 함께 INSERT 하고(아웃박스 패턴),
스케줄러가 scheduled_at이 도래한 PENDING 알림을 발송한다.
→ 외부 SMS API 장애가 예약 트랜잭션을 실패시키지 않으며, 발송 이력/재시도가 DB에 남는다.
"""
import logging
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import now
from ..models import (
    Booking,
    BookingStatus,
    Notification,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    User,
)

log = logging.getLogger("allostar.notify")


class SmsSender(Protocol):
    def send(self, to: str, title: str, body: str) -> None: ...


class ConsoleSmsSender:
    """MVP용 Mock. 운영 시 카카오 알림톡/NHN Cloud SMS 구현체로 교체한다."""

    def send(self, to: str, title: str, body: str) -> None:
        log.info("[SMS] to=%s | %s | %s", to, title, body.replace("\n", " / "))


sms_sender: SmsSender = ConsoleSmsSender()


def fmt_dt(dt: datetime) -> str:
    wd = "월화수목금토일"[dt.weekday()]
    return f"{dt.month}/{dt.day}({wd}) {dt:%H:%M}"


def enqueue(
    db: Session,
    user: User,
    type_: NotificationType,
    title: str,
    body: str,
    *,
    scheduled_at: datetime | None = None,
    booking_id: int | None = None,
    waitlist_id: int | None = None,
    sms_to: str | None = None,
) -> None:
    """SMS + 인앱 알림을 함께 적재한다."""
    at = scheduled_at or now()
    for channel, recipient in (
        (NotificationChannel.SMS, sms_to or user.phone),
        (NotificationChannel.IN_APP, str(user.id)),
    ):
        db.add(
            Notification(
                user_id=user.id,
                booking_id=booking_id,
                waitlist_id=waitlist_id,
                type=type_,
                channel=channel,
                recipient=recipient,
                title=title,
                body=body,
                scheduled_at=at,
            )
        )


def attendance_link(token: str) -> str:
    """문자로 받은 사람이 로그인 없이 참석 응답하는 링크(가족 번호로 받아도 응답 가능)."""
    return f"{settings.frontend_url}/c/{token}"


def schedule_for_new_booking(db: Session, booking: Booking, token: str, *, rescheduled_from: datetime | None = None) -> None:
    """확정(또는 일정 변경) 알림 1통 + 리마인더. 일정 변경이면 '취소'와 '확정' 2통 대신 '변경' 1통만 보낸다."""
    start = booking.slot.start_at
    counselor_name = booking.counselor.user.name
    link = attendance_link(token)
    if rescheduled_from:
        title = "상담 일정이 변경되었습니다"
        body = (
            f"{fmt_dt(rescheduled_from)} → {fmt_dt(start)}로 변경되었습니다.\n"
            f"{counselor_name} 상담사가 {booking.contact_phone}로 전화드립니다.\n참석 확인: {link}"
        )
    else:
        title = "상담 예약이 확정되었습니다"
        body = (
            f"{fmt_dt(start)} {counselor_name} 상담사가 {booking.contact_phone}로 전화드립니다.\n"
            f"피검자: {booking.subject.name}\n참석 확인: {link}"
        )
    enqueue(db, booking.customer, NotificationType.BOOKING_CONFIRMED, title, body,
            booking_id=booking.id, sms_to=booking.contact_phone)
    for offset in settings.reminder_offsets_minutes:
        at = start - timedelta(minutes=offset)
        if at <= now():
            continue
        when = "내일" if offset >= 1440 else f"{offset // 60}시간 후" if offset >= 60 else f"{offset}분 후"
        enqueue(
            db,
            booking.customer,
            NotificationType.REMINDER,
            f"[리마인더] {when} 상담이 예정되어 있습니다",
            f"{fmt_dt(start)} {booking.contact_phone}로 전화드립니다.\n"
            f"아래 링크에서 '통화 가능' 또는 '어려워요'를 눌러주세요(로그인 필요 없음).\n{link}",
            scheduled_at=at,
            booking_id=booking.id,
            sms_to=booking.contact_phone,
        )


def cancel_pending_for_booking(db: Session, booking_id: int) -> None:
    for n in db.scalars(
        select(Notification).where(
            Notification.booking_id == booking_id, Notification.status == NotificationStatus.PENDING
        )
    ):
        n.status = NotificationStatus.CANCELLED


def dispatch_due(db: Session, limit: int = 200) -> int:
    """도래한 알림 발송. 스케줄러가 주기적으로 호출한다."""
    due = db.scalars(
        select(Notification)
        .where(Notification.status == NotificationStatus.PENDING, Notification.scheduled_at <= now())
        .order_by(Notification.scheduled_at)
        .limit(limit)
    ).all()
    sent = 0
    for n in due:
        # 방어: 리마인더 발송 시점에 예약이 더 이상 유효하지 않으면 발송하지 않는다
        if n.type == NotificationType.REMINDER and n.booking_id:
            booking = db.get(Booking, n.booking_id)
            if booking is None or booking.status != BookingStatus.CONFIRMED:
                n.status = NotificationStatus.CANCELLED
                continue
        try:
            if n.channel == NotificationChannel.SMS:
                sms_sender.send(n.recipient, n.title, n.body)
            n.status = NotificationStatus.SENT
            n.sent_at = now()
            sent += 1
        except Exception:  # 외부 발송 실패는 기록만 하고 다음 주기에 운영자가 확인
            log.exception("notification %s failed", n.id)
            n.status = NotificationStatus.FAILED
    db.commit()
    return sent
