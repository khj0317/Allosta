"""리마인더 응답·문자 발송 상한·일정 변경 알림 회귀 테스트."""
import re
from datetime import timedelta

from app.db import now
from app.models import Booking, Notification, NotificationChannel, NotificationType, Relation, ServiceType, Subject, TestResult

from .conftest import auth, tomorrow_at


def _book(client, user, slot, subject, result, contact="OWNER"):
    return client.post("/api/bookings", headers=auth(user), json={
        "slot_id": slot.id, "subject_id": subject.id, "result_id": result.id, "contact": contact}).json()


def _sms_bodies(db, booking_id):
    return [n.body for n in db.query(Notification).filter_by(booking_id=booking_id, channel=NotificationChannel.SMS)]


def _token_from_sms(db, booking_id):
    body = next(b for b in _sms_bodies(db, booking_id) if "/c/" in b)
    return re.search(r"/c/([\w-]+)", body).group(1)


# ---------------------------------------------------------------- 1. 로그인 없는 참석 응답

def test_reminder_link_lets_anyone_with_sms_confirm_without_login(client, f, db):
    c = f.counselor()
    slot = f.slot(c, now() + timedelta(days=2))
    u, s, r = f.customer_with_result()
    b = _book(client, u, slot, s, r)
    token = _token_from_sms(db, b["id"])

    info = client.get(f"/api/public/attendance/{token}")  # 인증 헤더 없음
    assert info.status_code == 200 and info.json()["can_respond"] is True
    assert client.post(f"/api/public/attendance/{token}/confirm").status_code == 200
    db.expire_all()
    assert db.get(Booking, b["id"]).attendance_confirmed_at is not None


def test_family_contact_can_say_they_cannot_attend_and_owner_is_told(client, f, db):
    c = f.counselor()
    slot = f.slot(c, now() + timedelta(days=2))
    u = f.user()
    mom = Subject(owner_id=u.id, name="엄마", relation=Relation.PARENT, phone="010-2345-6789", consent_at=now())
    db.add(mom)
    db.flush()
    r = TestResult(kit_code="K-MOM", subject_id=mom.id, service_type=ServiceType.METABOLIC, reported_at=now())
    db.add(r)
    db.commit()
    b = _book(client, u, slot, mom, r, contact="SUBJECT")
    token = _token_from_sms(db, b["id"])

    assert client.post(f"/api/public/attendance/{token}/decline").status_code == 200

    db.expire_all()
    booking = db.get(Booking, b["id"])
    assert booking.attendance_declined_at is not None and booking.attendance_confirmed_at is None
    titles = [n.title for n in db.query(Notification).filter_by(user_id=u.id, channel=NotificationChannel.IN_APP)]
    assert any("통화가 어렵다" in t for t in titles)  # 계정 주인이 일정을 바꿀 수 있게 알림


def test_invalid_or_finished_token_cannot_respond(client, f, db):
    assert client.get("/api/public/attendance/not-a-token").status_code == 404
    c = f.counselor()
    slot = f.slot(c, now() + timedelta(days=2))
    u, s, r = f.customer_with_result()
    b = _book(client, u, slot, s, r)
    token = _token_from_sms(db, b["id"])
    client.post(f"/api/bookings/{b['id']}/cancel", json={}, headers=auth(u))
    assert client.post(f"/api/public/attendance/{token}/confirm").json()["detail"]["code"] == "CANNOT_RESPOND"


def test_token_is_not_stored_in_plain_text(client, f, db):
    c = f.counselor()
    slot = f.slot(c, now() + timedelta(days=2))
    u, s, r = f.customer_with_result()
    b = _book(client, u, slot, s, r)
    token = _token_from_sms(db, b["id"])
    db.expire_all()
    assert db.get(Booking, b["id"]).attendance_token_hash != token


# ---------------------------------------------------------------- 2. 문자 발송 상한

def test_signup_code_has_daily_limit_per_phone(client):
    for _ in range(5):
        assert client.post("/api/auth/phone/send", json={"phone": "010-5555-0000"}).status_code == 200
    res = client.post("/api/auth/phone/send", json={"phone": "010-5555-0000"})
    assert res.json()["detail"]["code"] == "DAILY_LIMIT"


def test_family_code_shares_the_daily_limit(client, f):
    u = f.user()
    sid = client.post("/api/subjects", headers=auth(u), json={
        "name": "엄마", "relation": "PARENT", "birth_date": "1962-09-03", "phone": "010-5555-1111"}).json()["subject"]["id"]
    for _ in range(4):  # 등록 시 1회 + 재발송 4회 = 5회
        assert client.post(f"/api/subjects/{sid}/verification", headers=auth(u)).status_code == 200
    res = client.post(f"/api/subjects/{sid}/verification", headers=auth(u))
    assert res.json()["detail"]["code"] == "DAILY_LIMIT"


# ---------------------------------------------------------------- 4. 일정 변경 알림 1통

def test_reschedule_sends_one_change_message_not_cancel_plus_confirm(client, f, db):
    c = f.counselor()
    a, b_slot = f.slot(c, tomorrow_at(10)), f.slot(c, tomorrow_at(15))
    u, s, r = f.customer_with_result()
    old = _book(client, u, a, s, r)
    new = client.post(f"/api/bookings/{old['id']}/reschedule", json={"slot_id": b_slot.id}, headers=auth(u)).json()

    sms_types = lambda bid: [n.type for n in db.query(Notification).filter_by(booking_id=bid, channel=NotificationChannel.SMS)  # noqa: E731
                             if n.status.value != "CANCELLED"]
    assert NotificationType.BOOKING_CANCELLED not in sms_types(old["id"])
    titles = [n.title for n in db.query(Notification).filter_by(booking_id=new["id"], channel=NotificationChannel.SMS)]
    assert "상담 일정이 변경되었습니다" in titles
    assert "상담 예약이 확정되었습니다" not in titles
