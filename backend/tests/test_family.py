"""가족 등록: 가족 본인 휴대폰 인증 + 키트 등록 정보 대조로 '진짜 가족'만 결과를 연결·상담할 수 있다."""
from datetime import date, timedelta

from app.db import now
from app.models import ServiceType, Subject, TestResult

from .conftest import auth

MOM = {"name": "성춘향", "relation": "PARENT", "birth_date": "1962-09-03", "phone": "010-2345-6789"}


def _add(client, user, **over):
    return client.post("/api/subjects", json={**MOM, **over}, headers=auth(user))


def _kit(db, code, name="성춘향", birth=(1962, 9, 3)):
    r = TestResult(kit_code=code, service_type=ServiceType.METABOLIC, reported_at=now(),
                   registered_name=name, registered_birth_date=date(*birth) if birth else None)
    db.add(r)
    db.commit()
    return r


def test_family_is_pending_until_code_verified(client, f, db):
    u = f.user()
    res = _add(client, u)

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["subject"]["consent_at"] is None
    assert body["subject"]["phone_masked"] == "010-****-6789"
    assert body["demo_code"] and len(body["demo_code"]) == 6  # 데모 모드에서만 화면에 안내

    sid = body["subject"]["id"]
    verified = client.post(f"/api/subjects/{sid}/verify", json={"code": body["demo_code"]}, headers=auth(u))
    assert verified.status_code == 200
    assert verified.json()["consent_at"] is not None


def test_wrong_code_is_rejected_and_attempts_are_limited(client, f, db):
    u = f.user()
    body = _add(client, u).json()
    sid, code = body["subject"]["id"], body["demo_code"]
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(5):
        assert client.post(f"/api/subjects/{sid}/verify", json={"code": wrong}, headers=auth(u)).json()["detail"]["code"] == "CODE_MISMATCH"
    # 시도 횟수를 넘기면 맞는 번호도 거부 → 재발송 필요
    assert client.post(f"/api/subjects/{sid}/verify", json={"code": code}, headers=auth(u)).json()["detail"]["code"] == "TOO_MANY_ATTEMPTS"


def test_expired_code_is_rejected(client, f, db):
    u = f.user()
    body = _add(client, u).json()
    s = db.get(Subject, body["subject"]["id"])
    s.verify_expires_at = now() - timedelta(seconds=1)
    db.commit()
    res = client.post(f"/api/subjects/{s.id}/verify", json={"code": body["demo_code"]}, headers=auth(u))
    assert res.json()["detail"]["code"] == "CODE_EXPIRED"


def test_family_phone_must_be_their_own(client, f):
    u = f.user()
    assert _add(client, u, phone=u.phone.replace("-", "")).json()["detail"]["code"] == "OWN_PHONE"
    assert _add(client, u).status_code == 201
    assert _add(client, u, name="홍판서", birth_date="1960-01-22").json()["detail"]["code"] == "PHONE_IN_USE"


def test_family_requires_birth_date_and_phone(client, f):
    u = f.user()
    assert client.post("/api/subjects", json={"name": "누구", "relation": "PARENT"}, headers=auth(u)).status_code == 422


def test_unverified_family_cannot_claim_kit(client, f, db):
    u = f.user()
    sid = _add(client, u).json()["subject"]["id"]
    _kit(db, "AL-K-1")
    res = client.post(f"/api/subjects/{sid}/claim-kit", json={"kit_code": "AL-K-1"}, headers=auth(u))
    assert res.json()["detail"]["code"] == "NOT_VERIFIED"


def test_kit_connects_only_to_registered_person(client, f, db):
    u = f.user()
    body = _add(client, u).json()
    sid = body["subject"]["id"]
    client.post(f"/api/subjects/{sid}/verify", json={"code": body["demo_code"]}, headers=auth(u))
    _kit(db, "AL-OTHER", name="임꺽정", birth=(1955, 5, 5))  # 다른 사람 앞으로 접수된 키트
    _kit(db, "AL-MOM")

    other = client.post(f"/api/subjects/{sid}/claim-kit", json={"kit_code": "AL-OTHER"}, headers=auth(u))
    mine = client.post(f"/api/subjects/{sid}/claim-kit", json={"kit_code": "al-mom"}, headers=auth(u))

    assert other.json()["detail"]["code"] == "KIT_OWNER_MISMATCH"
    assert [r["kit_code"] for r in mine.json()["results"]] == ["AL-MOM"]


def test_unregistered_kit_is_registered_to_first_claimer(client, f, db):
    u = f.user()
    body = _add(client, u).json()
    sid = body["subject"]["id"]
    client.post(f"/api/subjects/{sid}/verify", json={"code": body["demo_code"]}, headers=auth(u))
    kit = _kit(db, "AL-NEW", name=None, birth=None)

    client.post(f"/api/subjects/{sid}/claim-kit", json={"kit_code": "AL-NEW"}, headers=auth(u))

    db.refresh(kit)
    assert (kit.registered_name, str(kit.registered_birth_date)) == ("성춘향", "1962-09-03")


def test_can_remove_family_without_history(client, f, db):
    u = f.user()
    sid = _add(client, u).json()["subject"]["id"]
    assert client.delete(f"/api/subjects/{sid}", headers=auth(u)).status_code == 204
    assert client.get("/api/subjects", headers=auth(u)).json() == []
