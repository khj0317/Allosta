"""비밀번호를 바꾸면 다른 기기 로그인이 끊기고, 로그인 상태의 비밀번호 확인도 시도 횟수로 잠긴다."""
from .conftest import auth


def _change(client, headers, current, new="newpass99"):
    return client.post("/api/auth/password", json={"current_password": current, "new_password": new}, headers=headers)


def test_password_change_logs_out_other_devices_but_keeps_this_one(client, f):
    u = f.user()
    phone, laptop = auth(u), auth(u)  # 두 기기에서 로그인

    res = _change(client, laptop, "pw")
    assert res.status_code == 200
    new_headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    assert client.get("/api/auth/me", headers=phone).status_code == 401  # 다른 기기(혹은 탈취된 토큰) 끊김
    assert client.get("/api/auth/me", headers=laptop).status_code == 401  # 바꾸기 전 토큰도 무효
    assert client.get("/api/auth/me", headers=new_headers).status_code == 200  # 지금 기기는 새 토큰으로 유지


def test_password_reset_logs_out_everywhere(client, f):
    u = f.user()
    old = auth(u)
    sent = client.post("/api/auth/password-reset/send", json={"email": u.email, "phone": u.phone}).json()
    token = client.post("/api/auth/password-reset/verify", json={"email": u.email, "phone": u.phone, "code": sent["demo_code"]}).json()["reset_token"]
    client.post("/api/auth/password-reset", json={"email": u.email, "phone": u.phone, "reset_token": token, "new_password": "newpass99"})
    assert client.get("/api/auth/me", headers=old).status_code == 401


def test_password_guessing_with_a_stolen_token_is_locked(client, f):
    u = f.user()
    h = auth(u)
    for _ in range(4):
        assert _change(client, h, "guess000").json()["detail"]["code"] == "WRONG_PASSWORD"
    assert _change(client, h, "guess000").json()["detail"]["code"] == "ACCOUNT_LOCKED"
    # 잠긴 동안은 맞는 비밀번호도, 탈퇴도 거부
    assert _change(client, h, "pw").json()["detail"]["code"] == "ACCOUNT_LOCKED"
    assert client.post("/api/me/withdrawal", json={"password": "pw"}, headers=h).json()["detail"]["code"] == "ACCOUNT_LOCKED"


def test_withdrawal_password_failures_share_the_login_counter(client, f):
    u = f.user()
    h = auth(u)
    for _ in range(3):
        client.post("/api/me/withdrawal", json={"password": "guess000"}, headers=h)
    for _ in range(2):
        res = client.post("/api/auth/login", json={"email": u.email, "password": "guess000"})
    assert res.json()["detail"]["code"] == "ACCOUNT_LOCKED"  # 탈퇴 화면 3회 + 로그인 2회 = 5회


def test_shared_demo_accounts_are_protected_in_demo_mode(client, f, db):
    """공개 데모 주소에서 한 사람이 데모 계정을 바꿔 다른 평가자의 시연을 깨뜨리지 못한다."""
    from app.models import Counselor, Role

    customer = f.user()
    customer.email = "customer@allostar.kr"
    c = f.counselor()
    c.user.email = "counselor1@allostar.kr"
    db.commit()
    assert _change(client, auth(customer), "pw").json()["detail"]["code"] == "DEMO_ACCOUNT"
    sent = client.post("/api/auth/password-reset/send", json={"email": customer.email, "phone": customer.phone})
    assert sent.json()["detail"]["code"] == "DEMO_ACCOUNT"
    res = client.patch(f"/api/admin/counselors/{c.id}", json={"active": False}, headers=auth(f.user(Role.ADMIN)))
    assert res.json()["detail"]["code"] == "DEMO_ACCOUNT"
    assert db.get(Counselor, c.id).active
