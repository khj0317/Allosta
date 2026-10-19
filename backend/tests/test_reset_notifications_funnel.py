"""비밀번호 찾기, 안 읽은 알림, 대시보드 이탈 흐름."""
from datetime import timedelta

from app.db import now
from app.models import Booking, BookingStatus, Notification, NotificationChannel, NotificationStatus, NotificationType, Role, User
from app.services import metrics

from .conftest import auth

# ---------------------------------------------------------------- 비밀번호 찾기


def _reset_flow(client, email, phone, new="newpass99"):
    sent = client.post("/api/auth/password-reset/send", json={"email": email, "phone": phone}).json()
    token = client.post("/api/auth/password-reset/verify", json={"email": email, "phone": phone, "code": sent["demo_code"]}).json()["reset_token"]
    return client.post("/api/auth/password-reset", json={"email": email, "phone": phone, "reset_token": token, "new_password": new})


def test_reset_password_with_phone_code_and_unlock(client, f, db):
    u = f.user()
    u.locked_until = now() + timedelta(minutes=5)  # 잠긴 상태에서도 재설정 가능
    db.commit()

    assert _reset_flow(client, u.email, u.phone).status_code == 200

    login = client.post("/api/auth/login", json={"email": u.email, "password": "newpass99"})
    assert login.status_code == 200


def test_reset_does_not_reveal_whether_account_exists(client, f):
    u = f.user()
    real = client.post("/api/auth/password-reset/send", json={"email": u.email, "phone": u.phone})
    fake = client.post("/api/auth/password-reset/send", json={"email": "nobody@x.com", "phone": "010-9999-0000"})
    wrong_phone = client.post("/api/auth/password-reset/send", json={"email": u.email, "phone": "010-9999-0001"})
    assert real.status_code == fake.status_code == wrong_phone.status_code == 200
    assert fake.json()["sent"] is True and fake.json()["demo_code"] is None  # 실제 문자는 안 감


def test_signup_code_cannot_be_used_for_reset(client, f):
    """가입용 인증으로 받은 토큰으로 남의 비밀번호를 바꿀 수 없다(용도 분리)."""
    u = f.user()
    code = client.post("/api/auth/phone/send", json={"phone": "010-4444-0000"}).json()["demo_code"]
    signup_token = client.post("/api/auth/phone/verify", json={"phone": "010-4444-0000", "code": code}).json()["phone_token"]
    res = client.post("/api/auth/password-reset", json={"email": u.email, "phone": u.phone, "reset_token": signup_token, "new_password": "hack1234"})
    assert res.json()["detail"]["code"] == "PHONE_NOT_VERIFIED"


# ---------------------------------------------------------------- 안 읽은 알림


def _note(db, user, n=1):
    for _ in range(n):
        db.add(Notification(user_id=user.id, type=NotificationType.REMINDER, channel=NotificationChannel.IN_APP,
                            recipient=str(user.id), title="t", body="b", scheduled_at=now(), sent_at=now(),
                            status=NotificationStatus.SENT))
    db.commit()


def test_unread_count_and_read_all(client, f, db):
    u = f.user()
    _note(db, u, 3)
    assert client.get("/api/notifications/unread-count", headers=auth(u)).json()["count"] == 3
    assert client.post("/api/notifications/read-all", headers=auth(u)).json()["read"] == 3
    assert client.get("/api/notifications/unread-count", headers=auth(u)).json()["count"] == 0


# ---------------------------------------------------------------- 이탈 흐름


def test_funnel_counts_only_ended_bookings_and_is_nested(client, f, db):
    c = f.counselor()
    statuses = [BookingStatus.COMPLETED, BookingStatus.COMPLETED, BookingStatus.NO_SHOW, BookingStatus.CANCELLED]
    for i, st in enumerate(statuses):
        slot = f.slot(c, now() - timedelta(days=2, hours=i))
        u, s, r = f.customer_with_result()
        db.add(Booking(slot_id=slot.id, counselor_id=c.id, customer_id=u.id, subject_id=s.id, result_id=r.id,
                       contact_phone=u.phone, status=st, completed_at=now() if st == BookingStatus.COMPLETED else None,
                       attendance_confirmed_at=now() if i == 0 else None))
    future = f.slot(c, now() + timedelta(days=1))
    u, s, r = f.customer_with_result()
    db.add(Booking(slot_id=future.id, counselor_id=c.id, customer_id=u.id, subject_id=s.id, result_id=r.id, contact_phone=u.phone))
    db.commit()

    d = metrics.dashboard(db, (now() - timedelta(days=5)).date(), (now() + timedelta(days=2)).date())
    counts = {s["key"]: s["count"] for s in d["funnel"]}

    assert counts == {"booked": 4, "kept": 3, "completed": 2, "recommended": 0, "purchased": 0}  # 미래 예약 제외
    assert d["attendance_effect"]["confirmed_no_show_rate"] == 0
    assert d["attendance_effect"]["unconfirmed_no_show_rate"] == 0.5
