from datetime import timedelta

from app.db import now
from app.models import (
    Booking,
    BookingStatus,
    Relation,
    ServiceType,
    Slot,
    Subject,
    TestResult,
    WaitlistEntry,
    WaitlistStatus,
)
from app.services import waitlist as waitlist_svc

from .conftest import auth, tomorrow_at


def _join(client, user, subject, result, day, start_hour=9, end_hour=18):
    return client.post(
        "/api/waitlist",
        json={
            "subject_id": subject.id,
            "result_id": result.id,
            "desired_date": day.isoformat(),
            "start_hour": start_hour,
            "end_hour": end_hour,
            "contact_phone": "010-2222-3333",
        },
        headers=auth(user),
    )


def _book(client, user, slot, subject, result):
    return client.post(
        "/api/bookings",
        json={"slot_id": slot.id, "subject_id": subject.id, "result_id": result.id, "contact_phone": "010-1234-5678"},
        headers=auth(user),
    )


def test_cancellation_offers_slot_to_first_waiter_and_holds_it(client, f, db):
    c = f.counselor()
    slot = f.slot(c, tomorrow_at(14))
    booker, bs, br = f.customer_with_result()
    waiter1, w1s, w1r = f.customer_with_result()
    waiter2, w2s, w2r = f.customer_with_result()
    outsider, xs, xr = f.customer_with_result()

    booking_id = _book(client, booker, slot, bs, br).json()["id"]
    day = tomorrow_at(14).date()
    e1 = _join(client, waiter1, w1s, w1r, day).json()
    e2 = _join(client, waiter2, w2s, w2r, day).json()
    assert e1["status"] == e2["status"] == "WAITING"

    client.post(f"/api/bookings/{booking_id}/cancel", json={}, headers=auth(booker))

    db.expire_all()
    assert db.get(WaitlistEntry, e1["id"]).status == WaitlistStatus.OFFERED
    assert db.get(WaitlistEntry, e2["id"]).status == WaitlistStatus.WAITING  # 순차 제안
    # 제안 중인 슬롯은 다른 고객이 가로챌 수 없다
    assert _book(client, outsider, slot, xs, xr).json()["detail"]["code"] == "SLOT_TAKEN"

    res = client.post(f"/api/waitlist/{e1['id']}/accept", headers=auth(waiter1))
    assert res.status_code == 200, res.text
    db.expire_all()
    assert db.get(WaitlistEntry, e1["id"]).status == WaitlistStatus.BOOKED
    assert db.get(Slot, slot.id).hold_until is None


def test_expired_offer_passes_to_next_waiter(client, f, db):
    c = f.counselor()
    slot = f.slot(c, tomorrow_at(15))
    w1, s1, r1 = f.customer_with_result()
    w2, s2, r2 = f.customer_with_result()
    day = tomorrow_at(15).date()

    # 빈 슬롯이 이미 있으면 대기 신청 즉시 제안된다
    e1 = _join(client, w1, s1, r1, day).json()
    assert e1["status"] == "OFFERED"
    e2 = _join(client, w2, s2, r2, day).json()
    assert e2["status"] == "WAITING"

    entry = db.get(WaitlistEntry, e1["id"])
    entry.offer_expires_at = now() - timedelta(minutes=1)
    db.get(Slot, slot.id).hold_until = now() - timedelta(minutes=1)
    db.commit()

    waitlist_svc.process_expirations(db)

    db.expire_all()
    assert db.get(WaitlistEntry, e1["id"]).status == WaitlistStatus.EXPIRED
    assert db.get(WaitlistEntry, e2["id"]).status == WaitlistStatus.OFFERED
    assert db.get(Slot, slot.id).held_for_waitlist_id == e2["id"]


def test_waitlist_respects_time_window(client, f, db):
    c = f.counselor()
    f.slot(c, tomorrow_at(10))
    u, s, r = f.customer_with_result()
    e = _join(client, u, s, r, tomorrow_at(10).date(), start_hour=15, end_hour=18).json()
    assert e["status"] == "WAITING"  # 10시 슬롯은 희망 시간대(15~18시)가 아님


def test_declined_slot_is_not_offered_again(client, f, db):
    c = f.counselor()
    f.slot(c, tomorrow_at(16))
    u, s, r = f.customer_with_result()
    e = _join(client, u, s, r, tomorrow_at(16).date()).json()
    assert e["status"] == "OFFERED"

    res = client.post(f"/api/waitlist/{e['id']}/decline", headers=auth(u)).json()

    assert res["status"] == "WAITING"
    assert res["offered_slot"] is None


# ---------------------------------------------------------------- 대기 ↔ 기존 예약 (버그 회귀 테스트)

def test_waiter_who_booked_elsewhere_can_accept_offer_as_reschedule(client, f, db):
    """대기 중 다른 시간을 직접 예약한 고객이 제안을 수락하면, 오류 대신 기존 예약이 제안 시간으로 옮겨진다."""
    c = f.counselor()
    wanted = f.slot(c, tomorrow_at(14))
    fallback = f.slot(c, tomorrow_at(17))
    holder, hs, hr = f.customer_with_result()
    waiter, ws, wr = f.customer_with_result()

    holder_booking = _book(client, holder, wanted, hs, hr).json()["id"]
    entry = _join(client, waiter, ws, wr, tomorrow_at(14).date(), 14, 15).json()
    fallback_booking = _book(client, waiter, fallback, ws, wr).json()["id"]  # 일단 다른 시간 확보

    client.post(f"/api/bookings/{holder_booking}/cancel", json={}, headers=auth(holder))
    res = client.post(f"/api/waitlist/{entry['id']}/accept", headers=auth(waiter))

    assert res.status_code == 200, res.text
    assert res.json()["start_at"].startswith(tomorrow_at(14).strftime("%Y-%m-%dT%H"))
    db.expire_all()
    assert db.get(Booking, fallback_booking).status == BookingStatus.CANCELLED
    assert db.get(WaitlistEntry, entry["id"]).status == WaitlistStatus.BOOKED


def test_customer_with_booking_can_wait_for_better_time(client, f, db):
    """이미 예약이 있어도 '더 원하는 시간'으로 대기할 수 있고, 제안 응답에 현재 예약이 함께 표시된다."""
    c = f.counselor()
    current = f.slot(c, tomorrow_at(17))
    u, s, r = f.customer_with_result()
    _book(client, u, current, s, r)
    f.slot(c, tomorrow_at(10))  # 원하는 시간대의 빈자리

    e = _join(client, u, s, r, tomorrow_at(10).date(), 9, 12).json()

    assert e["status"] == "OFFERED"
    assert e["current_booking"]["start_at"].startswith(tomorrow_at(17).strftime("%Y-%m-%dT%H"))


def test_freed_slot_after_reschedule_goes_to_next_waiter(client, f, db):
    """대기 수락으로 옮겨가며 비워진 기존 슬롯은 다음 대기자에게 이어서 제안된다."""
    c = f.counselor()
    early, late = f.slot(c, tomorrow_at(10)), f.slot(c, tomorrow_at(16))
    a, as_, ar = f.customer_with_result()
    b, bs, br = f.customer_with_result()
    day = tomorrow_at(10).date()

    _book(client, a, late, as_, ar)
    ea = _join(client, a, as_, ar, day, 9, 12).json()  # a는 10시를 원함 → 즉시 제안
    eb = _join(client, b, bs, br, day, 15, 18).json()  # b는 16시를 원함(현재 a가 점유)
    assert ea["status"] == "OFFERED" and eb["status"] == "WAITING"

    client.post(f"/api/waitlist/{ea['id']}/accept", headers=auth(a))

    db.expire_all()
    assert db.get(WaitlistEntry, eb["id"]).status == WaitlistStatus.OFFERED
    assert db.get(WaitlistEntry, eb["id"]).offered_slot_id == late.id


def test_offer_skips_waiter_with_conflicting_other_booking(client, f, db):
    """제안 시각에 다른 결과지 상담이 이미 잡힌 고객은 건너뛰고 다음 대기자에게 제안한다(수락 불가능한 제안 방지)."""
    c = f.counselor(specialties=["METABOLIC"])
    c2 = f.counselor(specialties=["FOOD_SENSITIVITY"])
    slot = f.slot(c, tomorrow_at(11))
    other = f.slot(c2, tomorrow_at(11))
    busy, s1, r1 = f.customer_with_result()
    # 같은 계정의 가족 결과지로 같은 시각에 이미 다른 상담이 있음
    s2 = Subject(owner_id=busy.id, name="가족", relation=Relation.SPOUSE, consent_at=now())
    db.add(s2)
    db.flush()
    r2 = TestResult(kit_code="KX", subject_id=s2.id, service_type=ServiceType.FOOD_SENSITIVITY, reported_at=now())
    db.add(r2)
    db.commit()
    holder, hs, hr = f.customer_with_result()
    nxt, ns, nr = f.customer_with_result()

    hb = _book(client, holder, slot, hs, hr).json()["id"]
    _book(client, busy, other, s2, r2)
    e_busy = _join(client, busy, s1, r1, tomorrow_at(11).date(), 11, 12).json()
    e_next = _join(client, nxt, ns, nr, tomorrow_at(11).date(), 11, 12).json()

    client.post(f"/api/bookings/{hb}/cancel", json={}, headers=auth(holder))

    db.expire_all()
    assert db.get(WaitlistEntry, e_busy["id"]).status == WaitlistStatus.WAITING
    assert db.get(WaitlistEntry, e_next["id"]).status == WaitlistStatus.OFFERED
