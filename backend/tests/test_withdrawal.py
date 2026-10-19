"""회원 탈퇴: 개인정보·건강정보는 지우고, 예약·주문은 익명으로 남긴다."""
from dataclasses import replace
from datetime import timedelta

from app.config import settings
from app.db import now
from app.models import (
    Booking,
    BookingStatus,
    ConsultationRecord,
    Indicator,
    Notification,
    Order,
    RecordStatus,
    Role,
    Slot,
    Subject,
    TestResult,
    User,
    WaitlistEntry,
    WaitlistStatus,
)
from app import constants
from app.services import phone as phone_svc

from .conftest import auth


def _withdraw(client, u, password="pw"):
    return client.post("/api/me/withdrawal", json={"password": password}, headers=auth(u))


def _booking(db, c, u, s, r, start, **kw):
    slot = Slot(counselor_id=c.id, start_at=start, end_at=start + timedelta(minutes=30))
    db.add(slot)
    db.flush()
    b = Booking(slot_id=slot.id, counselor_id=c.id, customer_id=u.id, subject_id=s.id, result_id=r.id,
                contact_phone=u.phone, pre_questions="혈당이 걱정돼요", **kw)
    db.add(b)
    db.commit()
    return b


def test_withdrawal_erases_personal_and_health_data_but_keeps_anonymous_stats(client, f, db):
    c = f.counselor()
    u, s, r = f.customer_with_result()
    past = _booking(db, c, u, s, r, now() - timedelta(days=3), status=BookingStatus.COMPLETED, completed_at=now())
    db.add(ConsultationRecord(booking_id=past.id, counselor_id=c.id, status=RecordStatus.SUBMITTED,
                              summary="공복혈당 높음", customer_message="식후 산책", concern_tags=["혈당"]))
    db.add(Order(external_order_id="O-1", customer_id=u.id, ordered_at=now(), total_amount=30000))
    db.add(Notification(user_id=u.id, type="REMINDER", channel="IN_APP", recipient=str(u.id), title="t", body="b",
                        scheduled_at=now()))
    db.commit()
    token_headers, uid, phone = auth(u), u.id, u.phone

    assert _withdraw(client, u).status_code == 204
    db.expire_all()

    user = db.get(User, uid)
    assert user.withdrawn_at and user.name == "탈퇴회원" and user.email.endswith("@deleted.invalid")
    assert client.get("/api/auth/me", headers=token_headers).status_code == 401  # 발급된 토큰도 무효
    assert db.get(Subject, s.id).name == "탈퇴회원" and db.get(Subject, s.id).birth_date is None
    assert db.query(Indicator).filter_by(result_id=r.id).count() == 0
    rec = db.query(ConsultationRecord).one()
    assert (rec.summary, rec.customer_message, rec.concern_tags) == ("", "", ["혈당"])  # 본문 삭제, 집계용 태그만
    b = db.get(Booking, past.id)
    assert (b.status, b.contact_phone, b.pre_questions) == (BookingStatus.COMPLETED, "", "")
    assert db.query(Order).filter_by(customer_id=uid).count() == 1  # 주문은 법정 보존(익명)
    assert db.query(Notification).filter_by(user_id=uid).count() == 0
    assert not phone_svc.phone_taken(db, phone)  # 같은 번호로 다시 가입 가능


def test_withdrawal_requires_password(client, f):
    u = f.user()
    assert _withdraw(client, u, "wrong").json()["detail"]["code"] == "WRONG_PASSWORD"


def test_upcoming_bookings_are_cancelled_and_offered_to_waiters(client, f, db):
    c = f.counselor()
    u, s, r = f.customer_with_result()
    b = _booking(db, c, u, s, r, now() + timedelta(days=2))
    waiter, ws, wr = f.customer_with_result()
    client.post("/api/waitlist", headers=auth(waiter), json={
        "subject_id": ws.id, "result_id": wr.id, "desired_date": b.slot.start_at.date().isoformat(),
        "start_hour": 0, "end_hour": 23})

    preview = client.get("/api/me/withdrawal", headers=auth(u)).json()
    assert preview["upcoming_bookings"] == 1 and preview["blocked_reason"] is None
    assert _withdraw(client, u).status_code == 204

    db.expire_all()
    assert db.get(Booking, b.id).status == BookingStatus.CANCELLED
    assert db.query(WaitlistEntry).filter_by(customer_id=waiter.id).one().status == WaitlistStatus.OFFERED


def test_cannot_withdraw_right_before_a_consultation(client, f, db):
    c = f.counselor()
    u, s, r = f.customer_with_result()
    _booking(db, c, u, s, r, now() + timedelta(hours=1))
    assert client.get("/api/me/withdrawal", headers=auth(u)).json()["blocked_reason"]
    assert _withdraw(client, u).json()["detail"]["code"] == "WITHDRAW_BLOCKED"


def test_own_waitlist_offer_is_released(client, f, db):
    c = f.counselor()
    slot = f.slot(c, now() + timedelta(days=2))
    u, s, r = f.customer_with_result()
    e = client.post("/api/waitlist", headers=auth(u), json={
        "subject_id": s.id, "result_id": r.id, "desired_date": slot.start_at.date().isoformat(),
        "start_hour": 0, "end_hour": 23}).json()
    assert e["status"] == "OFFERED"

    assert _withdraw(client, u).status_code == 204
    db.expire_all()
    assert db.get(WaitlistEntry, e["id"]).status == WaitlistStatus.CANCELLED
    assert db.get(Slot, slot.id).held_for_waitlist_id is None


def test_staff_and_demo_accounts_cannot_withdraw(client, f, db, monkeypatch):
    assert _withdraw(client, f.user(Role.COUNSELOR)).status_code == 403
    demo = f.user()
    demo.email = "customer@allostar.kr"
    db.commit()
    assert _withdraw(client, demo).json()["detail"]["code"] == "WITHDRAW_BLOCKED"
    monkeypatch.setattr(constants, "settings", replace(settings, demo_mode=False))  # 운영에서는 일반 계정
    assert _withdraw(client, demo).status_code == 204


def test_withdrawn_kit_cannot_be_claimed_by_someone_else(client, f, db):
    u, s, r = f.customer_with_result()
    r.kit_code = "AL-WD-0001"
    db.commit()
    _withdraw(client, u)
    db.expire_all()
    other, os_, _ = f.customer_with_result()
    res = client.post(f"/api/subjects/{os_.id}/claim-kit", json={"kit_code": r.kit_code}, headers=auth(other))
    assert res.json()["detail"]["code"] == "KIT_CLAIM_FAILED"
    assert db.get(TestResult, r.id).subject_id == s.id


def test_staff_cannot_process_or_record_withdrawn_customers_consultation(client, f, db):
    """탈퇴 뒤 상담사가 기록을 써서 지운 건강정보가 다시 쌓이거나 탈퇴 고객에게 알림이 나가면 안 된다."""
    c = f.counselor()
    u, s, r = f.customer_with_result()
    unprocessed = _booking(db, c, u, s, r, now() - timedelta(hours=2))  # 시간이 지났는데 처리 안 된 상담
    done = _booking(db, c, u, s, r, now() - timedelta(days=1), status=BookingStatus.COMPLETED, completed_at=now())
    _withdraw(client, u)
    db.expire_all()
    h = auth(c.user)

    assert db.get(Booking, unprocessed.id).status == BookingStatus.CANCELLED  # 처리 누락에 남지 않음
    assert client.get("/api/staff/bookings/overdue", headers=h).json() == []
    detail = client.get(f"/api/staff/bookings/{done.id}", headers=h).json()
    assert detail["customer_phone"] == "" and detail["booking"]["customer_withdrawn"] is True
    res = client.put(f"/api/staff/bookings/{done.id}/record", headers=h, json={"concern_tags": ["혈당·당대사"], "summary": "x"})
    assert res.json()["detail"]["code"] == "CUSTOMER_WITHDRAWN"
    assert client.post(f"/api/staff/bookings/{done.id}/call-attempt", headers=h).json()["detail"]["code"] == "CUSTOMER_WITHDRAWN"
    assert db.query(Notification).count() == 0
