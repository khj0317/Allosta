from dataclasses import replace

from app.db import now
from app.models import Role, ServiceType, TestResult, User
from app.routers import demo as demo_router

def _phone_token(client, phone="010-2222-3333"):
    code = client.post("/api/auth/phone/send", json={"phone": phone}).json()["demo_code"]
    return client.post("/api/auth/phone/verify", json={"phone": phone, "code": code}).json()["phone_token"]


SIGNUP = {
    "email": "New@Example.com ",
    "password": "pass1234",
    "name": "신규고객",
    "phone": "010-2222-3333",
    "birth_date": "1991-04-12",
    "privacy_consent": True,
}


def _signup(client, **over):
    """휴대폰 인증을 거쳐 가입한다(인증 흐름 자체는 test_identity.py에서 검증)."""
    body = {**SIGNUP, **over}
    return client.post("/api/auth/signup", json={**body, "phone_token": _phone_token(client, body["phone"])})


def test_signup_creates_customer_with_self_subject_and_logs_in(client, db):
    res = _signup(client)

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["user"]["role"] == "CUSTOMER"
    assert body["user"]["email"] == "new@example.com"  # 공백 제거 + 소문자 정규화
    subjects = client.get("/api/subjects", headers={"Authorization": f"Bearer {body['access_token']}"}).json()
    assert [(s["relation"], s["name"], s["birth_date"]) for s in subjects] == [("SELF", "신규고객", "1991-04-12")]
    assert subjects[0]["consent_at"] is not None


def test_signup_requires_privacy_consent_and_unique_email(client):
    assert _signup(client, **{"privacy_consent": False}).json()["detail"]["code"] == "CONSENT_REQUIRED"
    assert _signup(client).status_code == 201
    assert _signup(client, **{"email": "new@example.com", "phone": "010-2222-4444"}).json()["detail"]["code"] == "EMAIL_TAKEN"


def test_signup_password_policy(client):
    assert _signup(client, **{"password": "short1"}).status_code == 422
    assert _signup(client, **{"password": "onlyletters"}).status_code == 422


def test_signup_requires_valid_birth_date(client):
    without = {k: v for k, v in SIGNUP.items() if k != "birth_date"}
    assert client.post("/api/auth/signup", json=without).status_code == 422
    assert _signup(client, **{"birth_date": "2999-01-01"}).status_code == 422
    assert _signup(client, **{"birth_date": "1991-02-30"}).status_code == 422


def test_new_customer_can_claim_demo_kit(client, db):
    db.add(TestResult(kit_code="AL-DEMO-01", subject_id=None, service_type=ServiceType.METABOLIC, reported_at=now()))
    db.commit()
    token = _signup(client).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    me = client.get("/api/subjects", headers=h).json()[0]
    kits = lambda: client.get(f"/api/demo/kits?subject_id={me['id']}", headers=h).json()  # noqa: E731
    assert [k["kit_code"] for k in kits()] == ["AL-DEMO-01"]
    claimed = client.post(f"/api/subjects/{me['id']}/claim-kit", json={"kit_code": "al-demo-01"}, headers=h).json()

    assert claimed["results"][0]["kit_code"] == "AL-DEMO-01"
    assert kits() == []  # 연결된 키트는 목록에서 빠진다


def test_demo_session_switches_role_without_password(client, f):
    f.user(Role.ADMIN)
    db_admin = f.db.query(User).filter_by(role=Role.ADMIN).one()
    db_admin.email = "admin@allostar.kr"
    f.db.commit()

    res = client.post("/api/demo/session", json={"role": "ADMIN"})

    assert res.status_code == 200
    assert res.json()["user"]["role"] == "ADMIN"


def test_demo_endpoints_are_off_when_demo_mode_disabled(client, monkeypatch):
    monkeypatch.setattr(demo_router, "settings", replace(demo_router.settings, demo_mode=False))

    assert client.post("/api/demo/session", json={"role": "ADMIN"}).status_code == 404
    assert client.get("/api/demo/kits?subject_id=1").status_code == 404


def test_signup_cannot_create_staff_accounts(client):
    """역할은 입력받지 않는다. 클라이언트가 role을 보내도 고객으로만 가입된다."""
    res = _signup(client, **{"role": "ADMIN"})
    assert res.json()["user"]["role"] == "CUSTOMER"
