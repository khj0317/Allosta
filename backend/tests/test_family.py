"""가족 등록: 가족 본인 휴대폰 인증을 마쳐야 등록되고, 키트 등록 정보와 일치해야 결과를 연결할 수 있다."""
from datetime import date, timedelta

from app.db import now
from app.models import PhoneVerification, ServiceType, Subject, TestResult

from .conftest import auth

MOM = {"name": "성춘향", "relation": "PARENT", "birth_date": "1962-09-03", "phone": "010-2345-6789"}


def _send(client, user, **over):
    return client.post("/api/subjects/verification", json={**MOM, **over}, headers=auth(user))


def _add(client, user, code=None, **over):
    """인증번호 받기 → 확인까지 한 번에. code를 주면 그 번호로 확인한다."""
    if code is None:
        code = _send(client, user, **over).json()["demo_code"]
    return client.post("/api/subjects", json={**MOM, **over, "code": code}, headers=auth(user))


def _kit(db, code, name="성춘향", birth=(1962, 9, 3)):
    r = TestResult(kit_code=code, service_type=ServiceType.METABOLIC, reported_at=now(),
                   registered_name=name, registered_birth_date=date(*birth) if birth else None)
    db.add(r)
    db.commit()
    return r


def test_family_is_not_added_until_code_verified(client, f, db):
    u = f.user()
    sent = _send(client, u)

    assert sent.status_code == 200, sent.text
    assert sent.json()["demo_code"] and len(sent.json()["demo_code"]) == 6  # 데모 모드에서만 화면에 안내
    assert client.get("/api/subjects", headers=auth(u)).json() == []  # 인증 전에는 목록에 없음

    added = client.post("/api/subjects", json={**MOM, "code": sent.json()["demo_code"]}, headers=auth(u))
    assert added.status_code == 201
    assert added.json()["consent_at"] is not None
    assert added.json()["phone_masked"] == "010-****-6789"


def test_cannot_add_family_without_code(client, f):
    u = f.user()
    assert client.post("/api/subjects", json=MOM, headers=auth(u)).status_code == 422
    assert _add(client, u, code="123456").json()["detail"]["code"] == "CODE_EXPIRED"  # 받은 인증번호 없음


def test_wrong_code_is_rejected_and_attempts_are_limited(client, f, db):
    u = f.user()
    code = _send(client, u).json()["demo_code"]
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(5):
        assert _add(client, u, code=wrong).json()["detail"]["code"] == "CODE_MISMATCH"
    # 시도 횟수를 넘기면 맞는 번호도 거부 → 재발송 필요
    assert _add(client, u, code=code).json()["detail"]["code"] == "TOO_MANY_ATTEMPTS"
    assert client.get("/api/subjects", headers=auth(u)).json() == []


def test_expired_code_is_rejected(client, f, db):
    u = f.user()
    code = _send(client, u).json()["demo_code"]
    db.query(PhoneVerification).update({PhoneVerification.expires_at: now() - timedelta(seconds=1)})
    db.commit()
    assert _add(client, u, code=code).json()["detail"]["code"] == "CODE_EXPIRED"


def test_code_is_bound_to_the_person_in_the_message(client, f):
    """문자에 적힌 사람(이름·생년월일)과 다른 정보로 바꿔 등록할 수 없다."""
    u = f.user()
    code = _send(client, u).json()["demo_code"]
    res = client.post("/api/subjects", json={**MOM, "name": "임꺽정", "code": code}, headers=auth(u))
    assert res.json()["detail"]["code"] == "CODE_MISMATCH"


def test_code_cannot_be_used_by_another_account_or_twice(client, f):
    u, other = f.user(), f.user()
    code = _send(client, u).json()["demo_code"]
    assert _add(client, other, code=code).json()["detail"]["code"] == "CODE_EXPIRED"
    assert _add(client, u, code=code).status_code == 201
    assert _add(client, u, code=code).json()["detail"]["code"] == "PHONE_IN_USE"


def test_family_phone_must_be_their_own(client, f):
    u = f.user()
    assert _send(client, u, phone=u.phone.replace("-", "")).json()["detail"]["code"] == "OWN_PHONE"
    assert _add(client, u).status_code == 201
    assert _send(client, u, name="홍판서", birth_date="1960-01-22").json()["detail"]["code"] == "PHONE_IN_USE"


def test_family_requires_birth_date_and_phone(client, f):
    u = f.user()
    res = client.post("/api/subjects/verification", json={"name": "누구", "relation": "PARENT"}, headers=auth(u))
    assert res.status_code == 422


def test_kit_connects_only_to_registered_person(client, f, db):
    u = f.user()
    sid = _add(client, u).json()["id"]
    _kit(db, "AL-OTHER", name="임꺽정", birth=(1955, 5, 5))  # 다른 사람 앞으로 접수된 키트
    _kit(db, "AL-MOM")

    other = client.post(f"/api/subjects/{sid}/claim-kit", json={"kit_code": "AL-OTHER"}, headers=auth(u))
    mine = client.post(f"/api/subjects/{sid}/claim-kit", json={"kit_code": "al-mom"}, headers=auth(u))

    assert other.json()["detail"]["code"] == "KIT_CLAIM_FAILED"
    assert [r["kit_code"] for r in mine.json()["results"]] == ["AL-MOM"]


def test_unregistered_kit_is_registered_to_first_claimer(client, f, db):
    u = f.user()
    sid = _add(client, u).json()["id"]
    kit = _kit(db, "AL-NEW", name=None, birth=None)

    client.post(f"/api/subjects/{sid}/claim-kit", json={"kit_code": "AL-NEW"}, headers=auth(u))

    db.refresh(kit)
    assert (kit.registered_name, str(kit.registered_birth_date)) == ("성춘향", "1962-09-03")


def test_can_remove_family_without_history(client, f, db):
    u = f.user()
    sid = _add(client, u).json()["id"]
    assert client.delete(f"/api/subjects/{sid}", headers=auth(u)).status_code == 204
    assert client.get("/api/subjects", headers=auth(u)).json() == []
    assert db.query(Subject).count() == 0


def test_demo_dad_hint_can_be_added_and_claims_his_kit(client, f, db):
    """데모 안내의 아버지 정보로 가족 등록 → 그 정보로 접수된 키트가 연결된다."""
    dad = client.get("/api/demo/hints").json()["family"]
    db.add(TestResult(kit_code="AL-DAD", service_type=ServiceType.METABOLIC, reported_at=now(), registered_name=dad["name"],
                      registered_birth_date=date.fromisoformat(dad["birth_date"]), registered_phone=dad["phone"]))
    db.commit()
    u = f.user()
    sid = _add(client, u, **dad).json()["id"]
    res = client.post(f"/api/subjects/{sid}/claim-kit", json={"kit_code": "AL-DAD"}, headers=auth(u))
    assert [r["kit_code"] for r in res.json()["results"]] == ["AL-DAD"]
