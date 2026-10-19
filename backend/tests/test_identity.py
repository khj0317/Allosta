"""본인 확인 회귀 테스트.

- 가입 시 본인 휴대폰 인증 → 남의 이름·생년월일로 '본인' 가입해 그 사람의 키트를 가져가는 우회 차단
- 상담 전화번호는 인증된 번호(계정 주인 / 인증된 가족) 중에서만 → 모르는 사람에게 건강 결과를 설명하는 사고 차단
"""
from datetime import date

from app.db import now
from app.models import ServiceType, TestResult

from .conftest import auth, tomorrow_at

BASE = {"email": "x@x.com", "password": "abcd1234", "name": "성춘향", "birth_date": "1962-09-03", "privacy_consent": True}


def _verified_signup(client, phone="010-9999-9999", **over):
    sent = client.post("/api/auth/phone/send", json={"phone": phone}).json()
    token = client.post("/api/auth/phone/verify", json={"phone": phone, "code": sent["demo_code"]}).json()["phone_token"]
    return client.post("/api/auth/signup", json={**BASE, "phone": phone, "phone_token": token, **over})


def test_signup_requires_verified_phone(client):
    res = client.post("/api/auth/signup", json={**BASE, "phone": "010-9999-9999", "phone_token": "forged"})
    assert res.json()["detail"]["code"] == "PHONE_NOT_VERIFIED"
    assert _verified_signup(client).status_code == 201


def test_phone_token_is_bound_to_that_phone(client):
    sent = client.post("/api/auth/phone/send", json={"phone": "010-9999-9999"}).json()
    token = client.post("/api/auth/phone/verify", json={"phone": "010-9999-9999", "code": sent["demo_code"]}).json()["phone_token"]
    res = client.post("/api/auth/signup", json={**BASE, "phone": "010-8888-8888", "phone_token": token})
    assert res.json()["detail"]["code"] == "PHONE_NOT_VERIFIED"


def test_one_account_per_phone(client):
    assert _verified_signup(client).status_code == 201
    res = client.post("/api/auth/phone/send", json={"phone": "01099999999"})
    assert res.json()["detail"]["code"] == "PHONE_TAKEN"


def test_impersonating_signup_cannot_claim_someone_elses_kit(client, db):
    """재현된 우회: 성춘향 이름·생년월일로 '본인' 가입(휴대폰은 자기 것) → 성춘향 명의 키트 연결 시도."""
    db.add(TestResult(kit_code="AL-MOM-1", service_type=ServiceType.METABOLIC, reported_at=now(),
                      registered_name="성춘향", registered_birth_date=date(1962, 9, 3), registered_phone="010-2345-6789"))
    db.commit()
    token = _verified_signup(client).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/subjects", headers=h).json()[0]

    res = client.post(f"/api/subjects/{me['id']}/claim-kit", json={"kit_code": "AL-MOM-1"}, headers=h)

    assert res.json()["detail"]["code"] == "KIT_CLAIM_FAILED"


def test_real_owner_can_claim_own_kit(client, db):
    db.add(TestResult(kit_code="AL-MOM-1", service_type=ServiceType.METABOLIC, reported_at=now(),
                      registered_name="성춘향", registered_birth_date=date(1962, 9, 3), registered_phone="010-2345-6789"))
    db.commit()
    token = _verified_signup(client, phone="010-2345-6789").json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/subjects", headers=h).json()[0]
    res = client.post(f"/api/subjects/{me['id']}/claim-kit", json={"kit_code": "AL-MOM-1"}, headers=h)
    assert [r["kit_code"] for r in res.json()["results"]] == ["AL-MOM-1"]


# ---------------------------------------------------------------- 상담 전화번호

def test_booking_ignores_arbitrary_contact_number(client, f, db):
    """임의 번호를 보내도 무시하고, 선택지(내 번호)로만 정해진다."""
    c = f.counselor()
    slot = f.slot(c, tomorrow_at(10))
    u, s, r = f.customer_with_result()
    res = client.post("/api/bookings", headers=auth(u), json={
        "slot_id": slot.id, "subject_id": s.id, "result_id": r.id, "contact_phone": "010-0000-0000"})
    assert res.status_code == 201
    assert res.json()["contact_phone"] == u.phone


def test_booking_can_call_verified_family_phone(client, f, db):
    from app.models import Relation, Subject

    c = f.counselor()
    slot = f.slot(c, tomorrow_at(11))
    u = f.user()
    mom = Subject(owner_id=u.id, name="엄마", relation=Relation.PARENT, phone="010-2345-6789", consent_at=now())
    db.add(mom)
    db.flush()
    r = TestResult(kit_code="K-MOM", subject_id=mom.id, service_type=ServiceType.METABOLIC, reported_at=now())
    db.add(r)
    db.commit()

    res = client.post("/api/bookings", headers=auth(u), json={
        "slot_id": slot.id, "subject_id": mom.id, "result_id": r.id, "contact": "SUBJECT"})

    assert res.json()["contact_phone"] == "010-2345-6789"


def test_subject_contact_requires_family_with_verified_phone(client, f):
    c = f.counselor()
    slot = f.slot(c, tomorrow_at(12))
    u, s, r = f.customer_with_result()  # 본인 피검자
    res = client.post("/api/bookings", headers=auth(u), json={
        "slot_id": slot.id, "subject_id": s.id, "result_id": r.id, "contact": "SUBJECT"})
    assert res.json()["detail"]["code"] == "CONTACT_NOT_ALLOWED"
