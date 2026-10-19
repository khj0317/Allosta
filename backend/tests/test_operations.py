"""운영 빈틈 회귀 테스트: 상담사 발급·비활성화, 기록 수정 이력, 로그인 잠금, 지난 날짜 슬롯, 처리 누락 상담."""
from datetime import timedelta

from app.db import now
from app.models import Booking, Notification, NotificationChannel, RecordRevision, Role, User
from app.services import metrics

from .conftest import auth, tomorrow_at

NEW_COUNSELOR = {"name": "허준", "email": "hj@allostar.kr", "phone": "010-7777-0001", "specialties": ["METABOLIC"]}


def _admin(f):
    return f.user(Role.ADMIN)


# ---------------------------------------------------------------- 3. 상담사 계정 발급

def test_admin_issues_counselor_with_temp_password_that_must_be_changed(client, f):
    res = client.post("/api/admin/counselors", json=NEW_COUNSELOR, headers=auth(_admin(f)))
    assert res.status_code == 201, res.text
    temp = res.json()["temp_password"]
    assert res.json()["counselor"]["must_change_password"] is True

    login = client.post("/api/auth/login", json={"email": "hj@allostar.kr", "password": temp}).json()
    assert login["user"]["role"] == "COUNSELOR" and login["user"]["must_change_password"] is True

    h = {"Authorization": f"Bearer {login['access_token']}"}
    changed = client.post("/api/auth/password", json={"current_password": temp, "new_password": "newpass123"}, headers=h)
    assert changed.json()["must_change_password"] is False


def test_only_admin_can_issue_counselors(client, f):
    c = f.counselor()
    assert client.post("/api/admin/counselors", json=NEW_COUNSELOR, headers=auth(c.user)).status_code == 403


def test_cannot_deactivate_counselor_with_upcoming_bookings(client, f):
    c = f.counselor()
    slot = f.slot(c, tomorrow_at(10))
    u, s, r = f.customer_with_result()
    client.post("/api/bookings", json={"slot_id": slot.id, "subject_id": s.id, "result_id": r.id}, headers=auth(u))

    res = client.patch(f"/api/admin/counselors/{c.id}", json={"active": False}, headers=auth(_admin(f)))

    assert res.json()["detail"]["code"] == "HAS_UPCOMING"


def test_deactivated_counselor_cannot_login_or_use_old_token(client, f, db):
    c = f.counselor()
    old = auth(c.user)
    assert client.patch(f"/api/admin/counselors/{c.id}", json={"active": False}, headers=auth(_admin(f))).status_code == 200

    assert client.get("/api/auth/me", headers=old).status_code == 401
    res = client.post("/api/auth/login", json={"email": c.user.email, "password": "pw"})
    assert res.json()["detail"]["code"] == "ACCOUNT_DISABLED"


# ---------------------------------------------------------------- 4. 상담 기록 수정 이력

def _submitted(client, f, db):
    p = f.product()
    c = f.counselor()
    slot = f.slot(c, now() - timedelta(hours=2))
    u, s, r = f.customer_with_result()
    b = Booking(slot_id=slot.id, counselor_id=c.id, customer_id=u.id, subject_id=s.id, result_id=r.id,
                contact_phone=u.phone)
    db.add(b)
    db.commit()
    body = {"concern_tags": ["혈당·당대사"], "summary": "요약", "customer_message": "처음 안내",
            "recommendations": [{"product_id": p.id, "interest_level": "HIGH"}]}
    assert client.post(f"/api/staff/bookings/{b.id}/record/submit", json=body, headers=auth(c.user)).status_code == 200
    return c, u, b, body


def _in_app(db, user_id):
    return [n.title for n in db.query(Notification).filter_by(user_id=user_id, channel=NotificationChannel.IN_APP)]


def test_editing_submitted_record_requires_reason_and_keeps_history(client, f, db):
    c, u, b, body = _submitted(client, f, db)
    edited = {**body, "customer_message": "수정된 안내"}

    no_reason = client.put(f"/api/staff/bookings/{b.id}/record", json=edited, headers=auth(c.user))
    assert no_reason.json()["detail"]["code"] == "EDIT_REASON_REQUIRED"

    ok = client.put(f"/api/staff/bookings/{b.id}/record", json={**edited, "edit_reason": "용량 안내 정정"}, headers=auth(c.user))
    assert ok.status_code == 200

    rev = db.query(RecordRevision).one()
    assert rev.changed_fields == ["customer_message"]
    assert rev.before["customer_message"] == "처음 안내"  # 수정 전 내용 보존
    assert "상담 요약이 수정되었습니다" in _in_app(db, u.id)  # 고객 공개 항목이 바뀌었으니 알림

    detail = client.get(f"/api/staff/bookings/{b.id}", headers=auth(c.user)).json()
    assert detail["revisions"][0]["reason"] == "용량 안내 정정"


def test_internal_only_edit_does_not_notify_customer(client, f, db):
    c, u, b, body = _submitted(client, f, db)
    client.put(f"/api/staff/bookings/{b.id}/record", json={**body, "summary": "내부 메모 보강", "edit_reason": "메모"},
               headers=auth(c.user))
    assert "상담 요약이 수정되었습니다" not in _in_app(db, u.id)
    assert db.query(RecordRevision).one().changed_fields == ["summary"]


def test_record_is_locked_after_edit_window(client, f, db):
    c, u, b, body = _submitted(client, f, db)
    db.refresh(b)
    b.record.submitted_at = now() - timedelta(days=8)
    db.commit()
    res = client.put(f"/api/staff/bookings/{b.id}/record", json={**body, "edit_reason": "늦은 수정"}, headers=auth(c.user))
    assert res.json()["detail"]["code"] == "EDIT_WINDOW_CLOSED"


# ---------------------------------------------------------------- 5. 로그인 잠금

def test_login_locks_after_repeated_failures(client, f, db):
    u = f.user()
    for _ in range(4):
        assert client.post("/api/auth/login", json={"email": u.email, "password": "wrong"}).json()["detail"]["code"] == "INVALID_CREDENTIALS"
    assert client.post("/api/auth/login", json={"email": u.email, "password": "wrong"}).json()["detail"]["code"] == "ACCOUNT_LOCKED"
    # 잠긴 동안에는 맞는 비밀번호도 거부
    assert client.post("/api/auth/login", json={"email": u.email, "password": "pw"}).json()["detail"]["code"] == "ACCOUNT_LOCKED"

    db.expire_all()
    db.get(User, u.id).locked_until = now() - timedelta(seconds=1)
    db.commit()
    assert client.post("/api/auth/login", json={"email": u.email, "password": "pw"}).status_code == 200


def test_unknown_email_gets_same_message(client):
    res = client.post("/api/auth/login", json={"email": "nobody@x.com", "password": "x"})
    assert res.json()["detail"]["code"] == "INVALID_CREDENTIALS"


# ---------------------------------------------------------------- 6. 지난 날짜 슬롯

def test_cannot_create_or_toggle_past_slots(client, f):
    c = f.counselor()
    yesterday = (now() - timedelta(days=1)).date().isoformat()
    res = client.post("/api/staff/slots/bulk", json={"date_from": yesterday, "date_to": yesterday}, headers=auth(c.user))
    assert res.json()["detail"]["code"] == "PAST_DATE"

    past = f.slot(c, now() - timedelta(hours=3))
    res = client.patch(f"/api/staff/slots/{past.id}", json={"status": "BLOCKED"}, headers=auth(c.user))
    assert res.json()["detail"]["code"] == "PAST_SLOT"


# ---------------------------------------------------------------- 7. 처리 누락 상담

def test_old_unprocessed_booking_is_listed_as_overdue_not_upcoming(client, f, db):
    c = f.counselor()
    old = f.slot(c, now() - timedelta(days=20))  # 7일보다 오래된 미처리 상담
    u, s, r = f.customer_with_result()
    db.add(Booking(slot_id=old.id, counselor_id=c.id, customer_id=u.id, subject_id=s.id, result_id=r.id,
                   contact_phone=u.phone))
    db.commit()

    overdue = client.get("/api/staff/bookings/overdue", headers=auth(c.user)).json()
    assert len(overdue) == 1

    summary = metrics.dashboard(db, (now() - timedelta(days=30)).date(), now().date())["summary"]
    assert summary["overdue"] == 1 and summary["upcoming"] == 0
