from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import now
from app.models import Booking, BookingStatus, Notification, NotificationType, Relation, ServiceType

from .conftest import auth, tomorrow_at


def _book(client, user, slot, subject, result, **kw):
    body = {"slot_id": slot.id, "subject_id": subject.id, "result_id": result.id, "contact_phone": "010-1234-5678", **kw}
    return client.post("/api/bookings", json=body, headers=auth(user))


def test_booking_creates_confirmation_and_reminders(client, f, db):
    c = f.counselor()
    slot = f.slot(c, now() + timedelta(days=2))
    u, s, r = f.customer_with_result()

    res = _book(client, u, slot, s, r, concern_tags=["혈당·당대사"])

    assert res.status_code == 201, res.text
    types = [n.type for n in db.query(Notification).filter_by(booking_id=res.json()["id"], channel="SMS")]
    assert types.count(NotificationType.BOOKING_CONFIRMED) == 1
    assert types.count(NotificationType.REMINDER) == 2  # D-1, 1시간 전


def test_second_booking_on_same_slot_gets_409_with_alternatives(client, f):
    c1, c2 = f.counselor(), f.counselor()
    start = tomorrow_at(14)
    slot = f.slot(c1, start)
    f.slot(c2, start)  # 같은 시각 다른 상담사 → 1순위 대안
    u1, s1, r1 = f.customer_with_result()
    u2, s2, r2 = f.customer_with_result()

    assert _book(client, u1, slot, s1, r1).status_code == 201
    res = _book(client, u2, slot, s2, r2)

    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "SLOT_TAKEN"
    assert detail["alternatives"][0]["counselor_id"] == c2.id
    assert detail["alternatives"][0]["start_at"].startswith(start.strftime("%Y-%m-%dT%H:%M"))


def test_db_partial_unique_index_blocks_double_booking(f, db):
    """애플리케이션 검증을 우회한 동시 INSERT도 DB가 막는다."""
    c = f.counselor()
    slot = f.slot(c, tomorrow_at(10))
    u1, s1, r1 = f.customer_with_result()
    u2, s2, r2 = f.customer_with_result()
    common = dict(slot_id=slot.id, counselor_id=c.id, contact_phone="010-0000-0000")
    db.add(Booking(customer_id=u1.id, subject_id=s1.id, result_id=r1.id, **common))
    db.commit()
    db.add(Booking(customer_id=u2.id, subject_id=s2.id, result_id=r2.id, **common))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 취소된 예약은 슬롯을 점유하지 않는다
    first = db.query(Booking).one()
    first.status = BookingStatus.CANCELLED
    db.commit()
    db.add(Booking(customer_id=u2.id, subject_id=s2.id, result_id=r2.id, **common))
    db.commit()


def test_family_result_requires_consent(client, f, db):
    c = f.counselor()
    slot = f.slot(c, tomorrow_at(11))
    u, s, r = f.customer_with_result(relation=Relation.PARENT, consent=False)

    res = _book(client, u, slot, s, r)
    assert res.json()["detail"]["code"] == "CONSENT_REQUIRED"

    # 가족 본인 휴대폰 인증을 마치면(consent_at) 예약 가능
    s.consent_at = now()
    db.commit()
    assert _book(client, u, slot, s, r).status_code == 201


def test_counselor_specialty_must_match_result(client, f):
    c = f.counselor(specialties=["FOOD_SENSITIVITY"])
    slot = f.slot(c, tomorrow_at(11))
    u, s, r = f.customer_with_result(service=ServiceType.METABOLIC)
    assert _book(client, u, slot, s, r).json()["detail"]["code"] == "COUNSELOR_MISMATCH"


def test_one_upcoming_booking_per_result(client, f):
    c = f.counselor()
    a, b = f.slot(c, tomorrow_at(10)), f.slot(c, tomorrow_at(15))
    u, s, r = f.customer_with_result()
    assert _book(client, u, a, s, r).status_code == 201
    assert _book(client, u, b, s, r).json()["detail"]["code"] == "ALREADY_BOOKED"


def test_customer_cannot_cancel_after_deadline(client, f):
    c = f.counselor()
    slot = f.slot(c, now() + timedelta(hours=2))  # 리드타임(1h) 이후, 취소 마감(3h) 이내
    u, s, r = f.customer_with_result()
    booking_id = _book(client, u, slot, s, r).json()["id"]

    res = client.post(f"/api/bookings/{booking_id}/cancel", json={}, headers=auth(u))
    assert res.json()["detail"]["code"] == "DEADLINE_PASSED"


def test_reschedule_keeps_original_when_new_slot_taken(client, f, db):
    c = f.counselor()
    original, target = f.slot(c, tomorrow_at(10)), f.slot(c, tomorrow_at(11))
    u, s, r = f.customer_with_result()
    other, os_, or_ = f.customer_with_result()
    booking_id = _book(client, u, original, s, r).json()["id"]
    assert _book(client, other, target, os_, or_).status_code == 201

    res = client.post(f"/api/bookings/{booking_id}/reschedule", json={"slot_id": target.id}, headers=auth(u))

    assert res.status_code == 409
    db.expire_all()
    assert db.get(Booking, booking_id).status == BookingStatus.CONFIRMED


def test_reschedule_moves_booking(client, f, db):
    c = f.counselor()
    original, target = f.slot(c, tomorrow_at(10)), f.slot(c, tomorrow_at(11))
    u, s, r = f.customer_with_result()
    booking_id = _book(client, u, original, s, r).json()["id"]

    res = client.post(f"/api/bookings/{booking_id}/reschedule", json={"slot_id": target.id}, headers=auth(u))

    assert res.status_code == 200, res.text
    db.expire_all()
    assert db.get(Booking, booking_id).status == BookingStatus.CANCELLED
    assert res.json()["start_at"].startswith(tomorrow_at(11).strftime("%Y-%m-%dT%H"))
