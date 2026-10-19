"""회귀 테스트: 일괄 생성 시 중복 제안, 비활성 상담사 시간, 기본 비밀키로 기동, 키트 코드 추측."""
from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.config import settings
from app.db import now
from app.main import validate_settings
from app.models import Notification, NotificationChannel, NotificationType, Role, ServiceType, Slot, TestResult, WaitlistEntry, WaitlistStatus

from .conftest import auth


def _join(client, user, subject, result, day):
    return client.post("/api/waitlist", headers=auth(user), json={
        "subject_id": subject.id, "result_id": result.id, "desired_date": day.isoformat(), "start_hour": 9, "end_hour": 18}).json()


def _bulk(client, user, counselor_id, day):
    return client.post("/api/staff/slots/bulk", headers=auth(user), json={
        "counselor_id": counselor_id, "date_from": day.isoformat(), "date_to": day.isoformat(), "weekdays": list(range(7))})


# ---------------------------------------------------------------- A. 일괄 생성 시 대기자 1명에게 1번만 제안

def test_bulk_slots_offer_each_waiter_once_and_hold_one_slot(client, f, db):
    c = f.counselor()
    u, s, r = f.customer_with_result()
    day = (now() + timedelta(days=3)).date()
    _join(client, u, s, r, day)

    res = _bulk(client, f.user(Role.ADMIN), c.id, day).json()

    assert res["created"] > 1 and res["waitlist_offers"] == 1
    offers = db.query(Notification).filter_by(type=NotificationType.WAITLIST_OFFER, channel=NotificationChannel.SMS).count()
    assert offers == 1
    assert db.query(Slot).filter(Slot.held_for_waitlist_id.isnot(None)).count() == 1


def test_bulk_slots_spread_offers_across_waiters(client, f, db):
    c = f.counselor()
    day = (now() + timedelta(days=3)).date()
    waiters = [f.customer_with_result() for _ in range(3)]
    for u, s, r in waiters:
        _join(client, u, s, r, day)

    res = _bulk(client, f.user(Role.ADMIN), c.id, day).json()

    assert res["waitlist_offers"] == 3  # 3명에게 서로 다른 시간 1개씩
    held = [s.held_for_waitlist_id for s in db.query(Slot).filter(Slot.held_for_waitlist_id.isnot(None))]
    assert len(held) == len(set(held)) == 3


# ---------------------------------------------------------------- B. 비활성 상담사

def test_cannot_create_or_open_slots_for_inactive_counselor(client, f, db):
    c = f.counselor()
    slot = f.slot(c, now() + timedelta(days=2))
    slot.status = "BLOCKED"
    c.active = False
    db.commit()
    admin = f.user(Role.ADMIN)

    assert _bulk(client, admin, c.id, (now() + timedelta(days=3)).date()).json()["detail"]["code"] == "COUNSELOR_INACTIVE"
    res = client.patch(f"/api/staff/slots/{slot.id}", json={"status": "OPEN"}, headers=auth(admin))
    assert res.json()["detail"]["code"] == "COUNSELOR_INACTIVE"


def test_deactivation_releases_pending_offers_to_waiting(client, f, db):
    c = f.counselor()
    slot = f.slot(c, now() + timedelta(days=2))
    u, s, r = f.customer_with_result()
    e = _join(client, u, s, r, slot.start_at.date())
    assert e["status"] == "OFFERED"  # 빈 시간이 있어 바로 제안됨

    assert client.patch(f"/api/admin/counselors/{c.id}", json={"active": False}, headers=auth(f.user(Role.ADMIN))).status_code == 200

    db.expire_all()
    assert db.get(WaitlistEntry, e["id"]).status == WaitlistStatus.WAITING  # 수락 불가능한 제안은 거둬들임
    assert db.get(Slot, slot.id).held_for_waitlist_id is None


# ---------------------------------------------------------------- C. 기본 비밀키로 운영 기동 금지

def test_server_refuses_default_secrets_outside_demo_mode():
    prod = replace(settings, demo_mode=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_settings(prod)
    validate_settings(replace(prod, jwt_secret="x" * 40, integration_api_key="y" * 24))  # 바꾸면 통과
    validate_settings(replace(settings, demo_mode=True))  # 데모에서는 경고만


# ---------------------------------------------------------------- D. 키트 코드 추측 방지

def _kit(db, code, name="남", birth=date(1955, 5, 5)):
    db.add(TestResult(kit_code=code, service_type=ServiceType.METABOLIC, reported_at=now(),
                      registered_name=name, registered_birth_date=birth, registered_phone="010-9999-1234"))
    db.commit()


def test_kit_errors_do_not_reveal_which_codes_exist(client, f, db):
    u, s, _ = f.customer_with_result()
    _kit(db, "AL-EXISTS-1")
    missing = client.post(f"/api/subjects/{s.id}/claim-kit", json={"kit_code": "AL-NOPE-9"}, headers=auth(u)).json()["detail"]
    mismatch = client.post(f"/api/subjects/{s.id}/claim-kit", json={"kit_code": "AL-EXISTS-1"}, headers=auth(u)).json()["detail"]
    assert missing["code"] == mismatch["code"] == "KIT_CLAIM_FAILED"
    assert missing["message"] == mismatch["message"]


def test_kit_claim_failures_are_limited_per_day(client, f, db):
    u, s, _ = f.customer_with_result()
    for i in range(10):
        assert client.post(f"/api/subjects/{s.id}/claim-kit", json={"kit_code": f"AL-GUESS-{i}"}, headers=auth(u)).json()["detail"]["code"] == "KIT_CLAIM_FAILED"
    res = client.post(f"/api/subjects/{s.id}/claim-kit", json={"kit_code": "AL-GUESS-X"}, headers=auth(u))
    assert res.status_code == 429 and res.json()["detail"]["code"] == "TOO_MANY_KIT_ATTEMPTS"


# ---------------------------------------------------------------- 단일 컨테이너 배포: 화면 서빙

def test_frontend_is_served_with_spa_fallback(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.main import mount_frontend

    (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("x", encoding="utf-8")
    web = FastAPI()
    mount_frontend(web, str(tmp_path))
    c = TestClient(web)

    assert c.get("/assets/app.js").text == "console.log(1)"
    assert "root" in c.get("/c/some-token").text  # 화면 주소로 바로 들어와도 index.html
    assert c.get("/api/nope").status_code == 404  # 없는 API는 화면 대신 404
    assert c.get("/assets/old-build.js").status_code == 404  # 재배포 후 예전 번들 요청
    assert "root" in c.get("/../secret.txt").text  # 폴더 밖 파일은 내보내지 않음
