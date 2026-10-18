from datetime import timedelta

from app.config import settings
from app.db import now
from app.models import Booking, BookingStatus, Role
from app.services import metrics

from .conftest import auth


def _past_booking(f, db, hours_ago=2):
    c = f.counselor()
    slot = f.slot(c, now() - timedelta(hours=hours_ago))
    u, s, r = f.customer_with_result()
    b = Booking(slot_id=slot.id, counselor_id=c.id, customer_id=u.id, subject_id=s.id, result_id=r.id,
                contact_phone="010-1234-5678")
    db.add(b)
    db.commit()
    return c, u, b


def _record_body(product_id=None, **kw):
    body = {
        "concern_tags": ["혈당·당대사"],
        "summary": "내부 메모: 구매 의향 높음",
        "customer_message": "식후 걷기를 권해드렸습니다.",
        "recommendations": [{"product_id": product_id, "interest_level": "HIGH"}] if product_id else [],
    }
    body.update(kw)
    return body


def test_submit_record_completes_booking_and_hides_internal_notes(client, f, db):
    p = f.product()
    c, u, b = _past_booking(f, db)

    res = client.post(f"/api/staff/bookings/{b.id}/record/submit", json=_record_body(p.id), headers=auth(c.user))
    assert res.status_code == 200, res.text
    db.expire_all()
    assert db.get(Booking, b.id).status == BookingStatus.COMPLETED

    customer_view = client.get(f"/api/bookings/{b.id}/record", headers=auth(u)).json()
    assert customer_view["customer_message"] == "식후 걷기를 권해드렸습니다."
    assert "summary" not in customer_view
    assert customer_view["recommended_products"][0]["id"] == p.id


def test_record_requires_summary_and_tags(client, f, db):
    c, _, b = _past_booking(f, db)
    res = client.post(f"/api/staff/bookings/{b.id}/record/submit", json=_record_body(summary=" "), headers=auth(c.user))
    assert res.json()["detail"]["code"] == "SUMMARY_REQUIRED"


def test_other_counselor_cannot_write_record(client, f, db):
    _, _, b = _past_booking(f, db)
    stranger = f.counselor()
    res = client.put(f"/api/staff/bookings/{b.id}/record", json=_record_body(), headers=auth(stranger.user))
    assert res.status_code == 403


def test_no_show_requires_call_attempt(client, f, db):
    c, _, b = _past_booking(f, db)
    h = auth(c.user)
    assert client.post(f"/api/staff/bookings/{b.id}/no-show", headers=h).json()["detail"]["code"] == "CALL_ATTEMPT_REQUIRED"
    client.post(f"/api/staff/bookings/{b.id}/call-attempt", headers=h)
    assert client.post(f"/api/staff/bookings/{b.id}/no-show", headers=h).json()["status"] == "NO_SHOW"


def _ingest(client, email, sku, at, order_id):
    return client.post(
        "/api/integrations/orders",
        headers={"X-API-Key": settings.integration_api_key},
        json={"external_order_id": order_id, "customer_email": email, "ordered_at": at.isoformat(),
              "items": [{"sku": sku, "quantity": 1, "unit_price": 10000}]},
    )


def test_conversion_attribution_window_and_idempotent_webhook(client, f, db):
    recommended = f.product("REC")
    other = f.product("OTHER")
    c, u, b = _past_booking(f, db, hours_ago=24 * 40)
    client.post(f"/api/staff/bookings/{b.id}/record/submit", json=_record_body(recommended.id), headers=auth(c.user))
    db.expire_all()
    done = db.get(Booking, b.id)
    done.completed_at = now() - timedelta(days=40)
    db.commit()

    # 비추천 제품 구매 → 일반 구매 전환만, 추천 전환 아님
    assert _ingest(client, u.email, "OTHER", done.completed_at + timedelta(days=1), "O-1").json()["duplicate"] is False
    d_from, d_to = (now() - timedelta(days=45)).date(), now().date()
    m = metrics.dashboard(db, d_from, d_to)["summary"]
    assert m["conversion_rate"] == 0 and m["any_purchase_rate"] == 1

    # 귀속 기간(30일) 밖의 추천 제품 구매는 전환 아님
    _ingest(client, u.email, "REC", done.completed_at + timedelta(days=31), "O-2")
    assert metrics.dashboard(db, d_from, d_to)["summary"]["conversion_rate"] == 0

    # 기간 내 추천 제품 구매 → 전환. 같은 주문 재전송은 중복 적재되지 않는다.
    _ingest(client, u.email, "REC", done.completed_at + timedelta(days=3), "O-3")
    assert _ingest(client, u.email, "REC", done.completed_at + timedelta(days=3), "O-3").json()["duplicate"] is True
    m = metrics.dashboard(db, d_from, d_to)["summary"]
    assert m["conversion_rate"] == 1
    assert m["attributed_revenue"] == 10000


def test_dashboard_is_admin_only(client, f):
    c = f.counselor()
    admin = f.user(Role.ADMIN)
    q = f"date_from={now().date()}&date_to={now().date()}"
    assert client.get(f"/api/admin/dashboard?{q}", headers=auth(c.user)).status_code == 403
    assert client.get(f"/api/admin/dashboard?{q}", headers=auth(admin)).status_code == 200
